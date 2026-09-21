"""Trusted local configuration, subprocess and durable state helpers (POSIX)."""
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION = ROOT / 'templates/automation'
_spec = importlib.util.spec_from_file_location('safe_artifacts', AUTOMATION / 'safe_artifacts.py')
safe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(safe)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def environment(agent=False):
    # Token values and arbitrary inherited build/Git overrides never reach children.
    keys = ['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL']
    if agent:
        keys += ['CODEX_HOME', 'OPENAI_API_KEY']
    env = {key: os.environ[key] for key in keys if key in os.environ}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", GIT_LITERAL_PATHSPECS="1")
    return env


def process(argv, cwd, timeout=60, data=None, log=None, agent=False):
    with (open(log, 'wb') if log else contextlib.nullcontext(subprocess.PIPE)) as output:
        child = subprocess.Popen(argv, cwd=cwd, env=environment(agent), stdin=subprocess.PIPE,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            result, _ = child.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            raise ValueError('Command timed out; process group terminated') from None
        finally:
            # Do not leave background children modifying a supposedly finished workspace.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return child.returncode, result


def git(repo, *args, data=None):
    argv = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
            '-c', 'core.autocrlf=false', '-C', str(repo), *args]
    code, result = process(argv, repo, data=data)
    if code:
        raise ValueError('Git operation failed: ' + args[0])
    return result


def checkout(source, baseline, target):
    # Do not copy local hooks/config or share objects with the worker.
    git(target.parent, 'clone', '--no-local', '--no-checkout', '--', str(source), str(target))
    git(target, 'checkout', '--detach', baseline)
    git(target, 'remote', 'remove', 'origin')


def config(path, allow_expired=False):
    c = safe.load_json(path)
    required = {'gitlab_url', 'project_path', 'project_id', 'repo_path', 'baseline', 'target_branch',
                'allowed_author_ids', 'reviewer_ids', 'allowed_paths', 'checks', 'max_attempts',
                'timeout_seconds', 'max_patch_bytes', 'expires_at'}
    if type(c) is not dict or not required <= set(c) or set(c) - required - {'publication', 'automation'}:
        raise ValueError('Unknown or missing configuration fields')
    u = urlsplit(c['gitlab_url'])
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path:
        raise ValueError('gitlab_url must be an HTTPS origin without path or credentials')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+', c['project_path']):
        raise ValueError('Invalid project path')
    safe.sha(c['baseline'])
    for name in ('project_id', 'max_attempts', 'timeout_seconds', 'max_patch_bytes', 'expires_at'):
        if type(c[name]) is not int or c[name] < 1:
            raise ValueError('Invalid numeric setting: ' + name)
    if c['max_attempts'] > 5 or c['timeout_seconds'] > 3600:
        raise ValueError('Pilot limit: at most 5 attempts and 3600 seconds per command')
    if not allow_expired and c['expires_at'] <= time.time():
        raise ValueError('Project authorization expired')
    for name in ('allowed_author_ids', 'reviewer_ids'):
        if not isinstance(c[name], list) or not c[name] or any(type(i) is not int or i < 1 for i in c[name]):
            raise ValueError('Expected positive user IDs: ' + name)
    if not isinstance(c['allowed_paths'], list) or not c['allowed_paths']:
        raise ValueError('Exact allowed paths are required')
    if len({safe.safe_path(p) for p in c['allowed_paths']}) != len(c['allowed_paths']):
        raise ValueError('Repeated allowed paths')
    if not isinstance(c['checks'], list) or not c['checks']:
        raise ValueError('Required checks missing')
    ids = set()
    for check in c['checks']:
        if set(check) != {'id', 'argv'} or not isinstance(check['id'], str) or not check['id'].strip() or check['id'] in ids:
            raise ValueError('Invalid or repeated check ID')
        ids.add(check['id'])
        if not isinstance(check['argv'], list) or not check['argv'] or any(not isinstance(x, str) or not x or '\0' in x for x in check['argv']):
            raise ValueError('Checks require nonempty argv arrays')
    repo = Path(c['repo_path']).resolve(strict=True)
    c['repo_path'] = str(repo)
    git(repo, 'check-ref-format', '--branch', c['target_branch'])
    git(repo, 'cat-file', '-e', c['baseline'] + '^{commit}')
    from .policy import validate_policy, branch
    if 'publication' in c:
        validate_policy(c['publication'])
        git(repo, 'check-ref-format', '--branch', branch(c, 1))
        if branch(c, 1) == c['target_branch']:
            raise ValueError('Work branch must differ from target')
    if 'automation' in c:
        validate_automation(c['automation'])
    return c


def validate_automation(a):
    keys = {'poll_seconds', 'required_labels', 'baseline_mode', 'fetch_source', 'max_publish_attempts'}
    if not isinstance(a, dict) or set(a) != keys:
        raise ValueError('Invalid automation configuration')
    if type(a['poll_seconds']) is not int or not 1 <= a['poll_seconds'] <= 86400:
        raise ValueError('poll_seconds must be 1..86400')
    labels = a['required_labels']
    if not isinstance(labels, list) or any(not isinstance(x, str) or not x.strip() or ',' in x or x.lower() in {'any', 'none'} for x in labels):
        raise ValueError('required_labels must be an array of exact labels; [] accepts all open issues')
    if a['baseline_mode'] not in {'pinned', 'target'} or type(a['fetch_source']) is not bool:
        raise ValueError('Invalid baseline/fetch policy')
    if type(a['max_publish_attempts']) is not int or not 1 <= a['max_publish_attempts'] <= 5:
        raise ValueError('max_publish_attempts must be 1..5')


def issue_iid(c, url):
    prefix = c['gitlab_url'] + '/' + c['project_path'] + '/-/issues/'
    if not url.startswith(prefix) or not re.fullmatch(r'[1-9][0-9]*', url[len(prefix):]):
        raise ValueError('Issue URL is outside the configured project or is noncanonical')
    return int(url[len(prefix):])


def check_issue(c, iid, issue):
    if issue.get('iid') != iid or issue.get('project_id') != c['project_id']:
        raise ValueError('Issue project/ID mismatch')
    if issue.get('state') != 'opened' or issue.get('author', {}).get('id') not in c['allowed_author_ids']:
        raise ValueError('Issue is closed or its author is not authorized')
    if not issue.get('title') or not issue.get('description') or not issue.get('updated_at'):
        raise ValueError('Issue title, description and revision are required')
    if 'automation' in c and not set(c['automation']['required_labels']) <= set(issue.get('labels', [])):
        raise ValueError('Issue no longer has the required automation labels')
    return {key: issue[key] for key in ('iid', 'project_id', 'title', 'description', 'updated_at', 'state', 'author')}


@contextlib.contextmanager
def locked(directory, blocking=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ValueError('This issue already has an active operation') from None
        yield directory


def task_dir(root, c, iid):
    root = Path(root).resolve()
    if root.is_relative_to(Path(c['repo_path'])):
        raise ValueError('Run storage must be outside the source repository')
    identity = digest((c['gitlab_url'] + '/' + c['project_path']).encode())[:16]
    return root / (identity + '-' + str(iid))
