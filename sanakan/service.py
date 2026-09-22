"""Single-host polling service with durable jobs and separate credential roles."""
import copy
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from .execution import agents_for
from .common import ROOT, check_issue, config, digest, environment, git, locked, safe, save, task_dir
from .policy import branch
from .publisher import publish
from .runner import run
from .errors import RevalidationRequired
from . import handoff

ROLES = ('develop', 'publish')


def directory(root, c):
    # Keep services outside the source; namespace all state by the project, not PID.
    task_dir(root, c, 1)
    identity = digest((c['gitlab_url'] + '/' + c['project_path']).encode())[:16]
    return Path(root).resolve() / 'services' / identity


def busy(folder):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / 'lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def jobs(base):
    path = base / 'jobs.json'
    return safe.load_json(path) if path.exists() else {}


def update(base, iid, **fields):
    with locked(base / 'registry', blocking=True):
        records = jobs(base)
        job = records[str(iid)]
        job.update(fields, updated_at=time.time())
        save(base / 'jobs.json', records)
        return copy.deepcopy(job)


def layout(base, job):
    if any(type(job[k]) is not int or job[k] < 1 for k in ('iid', 'generation')):
        raise ValueError('Invalid stored job identity')
    folder = base / 'jobs' / str(job['iid']) / str(job['generation'])
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder / 'project.json', folder / 'runs'


def issue_url(c, iid):
    return c['gitlab_url'] + '/' + c['project_path'] + '/-/issues/' + str(iid)


def snapshot(c, provider):
    result = copy.deepcopy(c)
    if c['automation']['baseline_mode'] == 'target':
        target = provider.branch(c['target_branch'])
        if not target:
            raise ValueError('Target branch not found')
        result['baseline'] = safe.sha(target['commit']['id'])
        if c['automation']['fetch_source']:
            # Fetch only from the configured project; never follow an issue-provided URL.
            remote = git(Path(c['repo_path']), 'remote', 'get-url', 'origin').decode().strip()
            expected = c['gitlab_url'] + '/' + c['project_path']
            if remote not in {expected, expected + '.git'}:
                raise ValueError('Automatic fetch requires the configured HTTPS project origin without credentials')
            git(Path(c['repo_path']), 'fetch', '--no-tags', 'origin', c['target_branch'])
    git(Path(c['repo_path']), 'cat-file', '-e', result['baseline'] + '^{commit}')
    return result


def check_job_policy(c, effective):
    # A baseline chosen at admission is fixed for this job. All other policy changes
    # require explicit new development, rather than silently weakening publication.
    expected = dict(c, baseline=effective['baseline'], repo_path=effective['repo_path'])
    if effective != expected:
        raise RevalidationRequired('Project policy changed since job admission')


def receive(config_path, root, c):
    base = directory(root, c)
    failures = {}
    for packet in sorted(handoff.channel().glob('*.sanakan.json')):
        try:
            generation, files = handoff.decode_packet(packet)
            incoming = json.loads(files['state.json'])
            iid = int(json.loads(files['issue.json'])['iid'])
            with locked(base / 'registry', blocking=True):
                records = jobs(base)
                old = records.get(str(iid))
                if old and not old.get('imported'):
                    raise ValueError('Publisher must use a separate private --runs directory')
                if old and old['generation'] >= generation:
                    continue
                if old and old['status'] == 'published':
                    raise ValueError('A published issue requires manual follow-up')
            job = dict(iid=iid, generation=generation, status='ready', imported=True, publish_attempts=0)
            settings, runs = layout(base, job)
            imported_config, state, _ = handoff.import_run(config_path, packet, runs)
            save(settings, safe.load_json(imported_config))
            job.update(status=state['status'], updated_at=time.time())
            with locked(base / 'registry', blocking=True):
                records = jobs(base)
                records[str(iid)] = job
                save(base / 'jobs.json', records)
        except (ValueError, OSError, KeyError, TypeError) as error:
            failures[packet.name] = str(error)
    base.mkdir(parents=True, exist_ok=True)
    save(base / 'handoff-errors.json', failures)


def cycle(config_path, root, c, role, provider, agents=None, stopped=lambda: False):
    base = directory(root, c)
    if c['expires_at'] <= time.time():
        raise ValueError('Project authorization expired')
    if role == 'publish':
        receive(config_path, root, c)
    if role == 'develop':
        candidates = provider.issues(c['automation']['required_labels'])
        with locked(base / 'registry', blocking=True):
            records = jobs(base)
            for raw in candidates:
                iid = raw.get('iid')
                if type(iid) is not int or iid < 1 or str(iid) in records:
                    continue
                try:
                    check_issue(c, iid, raw)
                except ValueError:
                    continue
                records[str(iid)] = dict(iid=iid, generation=1, status='queued',
                                        publish_attempts=0, updated_at=time.time())
            save(base / 'jobs.json', records)
    for job in list(jobs(base).values()):
        if stopped():
            break
        iid = job['iid']
        settings, runs = layout(base, job)
        url = issue_url(c, iid)
        if role == 'develop' and job['status'] in {'ready', 'transfer_failed'}:
            try:
                packet = handoff.export_run(settings, url, runs, job['generation'])
                update(base, iid, status='handed_off', packet=packet.name, reason='')
            except (ValueError, OSError, KeyError, TypeError) as error:
                update(base, iid, status='transfer_failed', reason=str(error))
            continue
        if role == 'develop' and job['status'] == 'developing':
            # Recovery never repeats an unknown model operation automatically.
            path = task_dir(runs, c, iid) / 'state.json'
            recorded = safe.load_json(path) if path.exists() else {}
            terminal = {'ready', 'failed', 'needs_human', 'stopped'}
            recovered = recorded.get('status')
            update(base, iid, status=recovered if recovered in terminal else 'interrupted',
                   reason=recorded.get('reason', 'Previous development process ended; inspect and retry explicitly'))
            continue
        if role == 'develop' and job['status'] == 'queued':
            try:
                check_issue(c, iid, provider.issue(iid))
                name = branch(c, iid)
                if provider.branch(name) or provider.merge_requests(name):
                    raise ValueError('Existing work branch or MR requires inspection before new development')
                effective = snapshot(c, provider)
                save(settings, effective)
                update(base, iid, status='developing', baseline=effective['baseline'], branch=name, reason='')
                result = run(settings, url, runs, agents or agents_for(c),
                             provider=provider, stop_requested=stopped)
                update(base, iid, status=result['status'], reason=result.get('reason', ''),
                       questions=result.get('questions', []))
                if result['status'] == 'ready':
                    try:
                        packet = handoff.export_run(settings, url, runs, job['generation'])
                        update(base, iid, status='handed_off', packet=packet.name)
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        update(base, iid, status='transfer_failed', reason=str(error))
            except (ValueError, OSError, KeyError, TypeError) as error:
                update(base, iid, status='failed', reason=str(error))
        elif role == 'publish' and job['status'] in {'ready', 'publishing', 'publish_retry'}:
            try:
                effective = config(settings, allow_expired=True)
                check_job_policy(c, effective)
                # Revalidate labels, author and open state immediately before the publisher.
                check_issue(c, iid, provider.issue(iid))
                update(base, iid, status='publishing')
                result = publish(settings, url, runs, provider, stop_requested=stopped)
                update(base, iid, status='published', mr_url=result['mr_url'], reason='')
            except RevalidationRequired as error:
                update(base, iid, status='needs_revalidation', reason=str(error))
            except (ValueError, OSError, KeyError, TypeError) as error:
                count = job['publish_attempts'] + (0 if stopped() else 1)
                update(base, iid, publish_attempts=count, reason=str(error),
                       status='publish_failed' if count >= c['automation']['max_publish_attempts'] else 'publish_retry')
    return jobs(base)


def status(config_path, root):
    c = safe.load_json(config_path)  # Status/stop must still work after policy expiration.
    base = directory(root, c)
    services = {}
    for role in ROLES:
        path = base / role / 'service.json'
        value = safe.load_json(path) if path.exists() else {}
        services[role] = dict(value, running=busy(base / role),
                              stop_requested=(base / role / 'stop.json').exists())
    return {'services': services, 'jobs': jobs(base), 'handoff_errors':
            safe.load_json(base / 'handoff-errors.json') if (base / 'handoff-errors.json').exists() else {}}


def stop(config_path, root, role):
    c = safe.load_json(config_path)
    base = directory(root, c)
    roles = ROLES if role == 'all' else (role,)
    for selected in roles:
        folder = base / selected
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        save(folder / 'stop.json', {'requested_at': time.time()})
    return {'stop_requested': list(roles), 'behavior': 'Stops admission and exits at the next phase boundary'}


def retry(config_path, root, iid, mode="auto"):
    c = config(config_path)
    base = directory(root, c)
    # Management never races a whole development/publication operation.
    with locked(base / 'registry', blocking=True):
        records = jobs(base)
        job = records.get(str(iid))
        if not job:
            raise ValueError('Unknown issue job')
        if job['status'] in {'developing', 'publishing'} and busy(base / ('develop' if job['status'] == 'developing' else 'publish')):
            raise ValueError('An operation is active; stop it and wait before retrying')
        if mode == 'revalidate' and job.get('imported'):
            raise ValueError('Revalidate on the development host; publisher only retries signed results')
        if mode == 'revalidate' and busy(base / 'develop'):
            raise ValueError('Stop the development watcher before starting fresh revalidation')
        if mode == 'publish' and job['status'] not in {'publish_failed', 'publish_retry', 'publishing'}:
            raise ValueError('No reusable publication result; request revalidation instead')
        if mode not in {'auto', 'publish', 'revalidate'}:
            raise ValueError('Unknown retry mode')
        if job['status'] == 'published':
            raise ValueError('Published jobs cannot be retried')
        if job.get('imported') and job['status'] == 'needs_revalidation':
            raise ValueError('Revalidate on the development host and transfer a new signed result')
        if mode == 'revalidate' or (mode == 'auto' and job['status'] == 'needs_revalidation'):
            job.update(status='queued', generation=job['generation'] + 1,
                       publish_attempts=0, reason='', questions=[])
        elif job['status'] == 'needs_revalidation':
            raise ValueError('Fresh development and verification are required')
        elif job['status'] in {'publish_failed', 'publish_retry', 'publishing'}:
            job.update(status='publish_retry', publish_attempts=0, reason='')
        elif job['status'] in {'failed', 'needs_human', 'stopped', 'interrupted', 'developing'}:
            job.update(status='queued', generation=job['generation'] + 1,
                       publish_attempts=0, reason='', questions=[])
        else:
            raise ValueError('Job is already queued, ready or published; retry is not applicable')
        save(base / 'jobs.json', records)
        return job


def watch(config_path, root, role, provider, agents=None, once=False):
    c = config(config_path)
    if 'automation' not in c:
        raise ValueError('automation settings are required for watch/start')
    if c.get('execution', {}).get('backend') != 'docker':
        raise ValueError('Automatic services require Docker isolation; use run for local development')
    handoff.channel(); handoff.key_bytes()
    base = directory(root, c)
    folder = base / role
    with locked(folder):
        (folder / 'stop.json').unlink(missing_ok=True)
        quitting = threading.Event()
        old_handlers = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                old_handlers[sig] = signal.signal(sig, lambda *_: quitting.set())
        stopped = lambda: quitting.is_set() or (folder / 'stop.json').exists()
        state = dict(pid=os.getpid(), status='running', role=role, started_at=time.time())
        try:
            while not stopped():
                state.update(heartbeat=time.time(), last_error='')
                save(folder / 'service.json', state)
                try:
                    cycle(config_path, root, c, role, provider, agents, stopped)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    state['last_error'] = str(error)
                    if c['expires_at'] <= time.time():
                        quitting.set()
                state['heartbeat'] = time.time()
                save(folder / 'service.json', state)
                if once:
                    break
                deadline = time.monotonic() + c['automation']['poll_seconds']
                while not stopped() and time.monotonic() < deadline:
                    quitting.wait(min(0.5, max(0, deadline - time.monotonic())))
        finally:
            state.update(status='stopped', heartbeat=time.time())
            save(folder / 'service.json', state)
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    return status(config_path, root)


def start(config_path, root, role):
    c = config(config_path)
    if 'automation' not in c:
        raise ValueError('automation settings are required for watch/start')
    if c.get('execution', {}).get('backend') != 'docker':
        raise ValueError('Automatic services require Docker isolation')
    handoff.channel(); handoff.key_bytes()
    folder = directory(root, c) / role
    if busy(folder):
        raise ValueError('This service role is already running')
    # No shell, no token in argv, and no automatic start of the other credential role.
    env = environment(agent=(role == 'develop'))
    token_key = 'SANAKAN_READ_TOKEN' if role == 'develop' else 'SANAKAN_PUBLISH_TOKEN'
    token = os.environ.get(token_key)
    if not token:
        raise ValueError(token_key + ' is required')
    if role == 'develop' and os.environ.get('SANAKAN_PUBLISH_TOKEN'):
        raise ValueError('Do not inject a publish token into development')
    env[token_key] = token
    for key in ('SANAKAN_HANDOFF_DIR', 'SANAKAN_HANDOFF_KEY_FILE'):
        env[key] = os.environ[key]
    if role == 'develop' and os.environ.get('SANAKAN_CODEX_AUTH_FILE'):
        env['SANAKAN_CODEX_AUTH_FILE'] = os.environ['SANAKAN_CODEX_AUTH_FILE']
    with (folder / 'service.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, '-m', 'sanakan', 'watch', '--role', role,
                                  '--config', str(Path(config_path).resolve()), '--runs', str(Path(root).resolve())],
                                 cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, start_new_session=True)
    for _ in range(50):
        if child.poll() is not None:
            raise ValueError('Service exited during startup; inspect service.log')
        state_file = folder / 'service.json'
        if busy(folder) and state_file.exists() and safe.load_json(state_file).get('pid') == child.pid:
            return {'status': 'started', 'role': role, 'pid': child.pid}
        time.sleep(0.05)
    raise ValueError('Service startup not confirmed; inspect status before retrying')
