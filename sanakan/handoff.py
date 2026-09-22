"""Authenticated, bounded result transfer between private controller/publisher stores.

The shared directory holds only immutable signed packets, never writable run state.
Provision the HMAC key to the two trusted hosts; never mount it in executors.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
from .common import check_issue, config, digest, git, issue_iid, locked, safe, save, task_dir
from .errors import RevalidationRequired

MAX_PACKET = 64 * 1024 * 1024
REPORTS = ('change.patch', 'change.json', 'triage.json', 'implementation.json', 'review.json', 'verification.json')


def key_bytes():
    name = os.environ.get('SANAKAN_HANDOFF_KEY_FILE')
    if not name:
        raise ValueError('SANAKAN_HANDOFF_KEY_FILE is required')
    path = Path(name)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Handoff key file must be a private regular file (chmod 600)')
    key = path.read_bytes()
    if not 32 <= len(key) <= 4096:
        raise ValueError('Handoff key must contain 32..4096 random bytes')
    return key


def channel():
    value = os.environ.get('SANAKAN_HANDOFF_DIR')
    if not value:
        raise ValueError('SANAKAN_HANDOFF_DIR is required')
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Handoff channel must be an existing directory')
    return path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def export_run(config_path, url, runs, generation=1):
    from .runner import gate
    c = config(config_path)
    iid = issue_iid(c, url)
    with locked(task_dir(runs, c, iid)) as task:
        state = safe.load_json(task / 'state.json')
        if (state['status'] != 'ready' or state['fixture'] or state.get('execution') != 'docker' or
                c.get('execution', {}).get('backend') != 'docker'):
            raise ValueError('Only ready non-fixture Docker results can be exported')
        folder = task / ('attempt-' + str(state['attempt']))
        gate(folder)
        # Baseline transport contains only the selected commit's reachable history.
        with tempfile.TemporaryDirectory(prefix='sanakan-bundle-') as td:
            scratch = Path(td) / 'repo'
            from .common import checkout
            checkout(c['repo_path'], c['baseline'], scratch)
            bundle = Path(td) / 'baseline.bundle'
            git(scratch, 'bundle', 'create', str(bundle), 'HEAD')
            if bundle.stat().st_size > MAX_PACKET // 2:
                raise ValueError('Baseline bundle exceeds handoff limit')
            entries = {'baseline.bundle': bundle.read_bytes()}
        for name in ('config.json', 'issue.json', 'allowlist.json', 'verification-policy.json', 'state.json'):
            entries[name] = (task / name).read_bytes()
        for name in REPORTS:
            entries['attempt/' + name] = (folder / name).read_bytes()
        if sum(map(len, entries.values())) > MAX_PACKET // 2:
            raise ValueError('Result bundle exceeds handoff limit')
        payload = {'version': 1, 'generation': generation,
                   'files': {name: base64.b64encode(data).decode() for name, data in entries.items()}}
        encoded = canonical(payload)
        packet = {'payload': payload, 'signature': hmac.new(key_bytes(), encoded, hashlib.sha256).hexdigest()}
        target = channel() / (digest(encoded) + '.sanakan.json')
        if target.exists():
            if safe.load_json(target) != packet:
                raise ValueError('Existing handoff packet differs')
            return target
        # Channel should be setgid to a publisher-readable group. No recursive chmod
        # of controller run directories and no shared writable state are needed.
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.packet-', delete=False) as stream:
            temp = Path(stream.name)
            stream.write(canonical(packet)); stream.flush(); os.fsync(stream.fileno())
        try:
            temp.chmod(0o640)
            os.link(temp, target)  # Atomic, no overwrite if two exporters race.
        except FileExistsError:
            if target.read_bytes() != canonical(packet):
                raise ValueError('Concurrent handoff packet differs')
        finally:
            temp.unlink(missing_ok=True)
        return target


def decode_packet(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_PACKET:
        raise ValueError('Invalid handoff packet size/type')
    packet = safe.load_json(path)
    if set(packet) != {'payload', 'signature'}:
        raise ValueError('Invalid handoff envelope')
    expected = hmac.new(key_bytes(), canonical(packet['payload']), hashlib.sha256).hexdigest()
    if not isinstance(packet['signature'], str) or not hmac.compare_digest(expected, packet['signature']):
        raise ValueError('Handoff signature mismatch')
    payload = packet['payload']
    if set(payload) != {'version', 'generation', 'files'} or payload['version'] != 1:
        raise ValueError('Unsupported handoff payload')
    if type(payload['generation']) is not int or payload['generation'] < 1:
        raise ValueError('Invalid handoff generation')
    expected_names = {'baseline.bundle', 'config.json', 'issue.json', 'allowlist.json',
                      'verification-policy.json', 'state.json'} | {'attempt/' + n for n in REPORTS}
    if set(payload['files']) != expected_names:
        raise ValueError('Unexpected handoff files')
    files = {name: base64.b64decode(value, validate=True) for name, value in payload['files'].items()}
    return payload['generation'], files


def import_run(config_path, path, runs):
    from .runner import gate
    c = config(config_path)
    generation, files = decode_packet(path)
    original = json.loads(files['config.json'])
    state = json.loads(files['state.json'])
    issue = json.loads(files['issue.json'])
    iid = issue_iid(c, state['issue_url'])
    check_issue(dict(c, automation=dict(c.get('automation', {}), required_labels=[])), iid, issue)
    expected = dict(c, baseline=original['baseline'], repo_path=original['repo_path'])
    if original != expected or (c.get('automation', {}).get('baseline_mode', 'pinned') == 'pinned' and original['baseline'] != c['baseline']):
        raise RevalidationRequired('Handoff project policy changed; revalidate the issue')
    if state['status'] != 'ready' or state['fixture'] or state.get('execution') != 'docker':
        raise ValueError('Handoff is not an isolated ready result')
    if type(state['attempt']) is not int or not 1 <= state['attempt'] <= c['max_attempts']:
        raise ValueError('Invalid handoff attempt')
    from .common import run_identity
    if state['key'] != run_identity(original, issue):
        raise ValueError('Handoff identity mismatch')
    with locked(task_dir(runs, c, iid)) as task:
        saved_state = task / 'state.json'
        if saved_state.exists():
            old = safe.load_json(saved_state)
            if old.get('key') != state['key'] or old.get('handoff_digest') != digest(Path(path).read_bytes()):
                raise ValueError('Handoff conflicts with an existing run')
            return task / 'config.json', old, generation
        # A crash before the receipt was committed can leave a partial import.
        # Only discard this private, unpublished import's fixed artifact names.
        import shutil
        for name in ('source', 'config.json', 'issue.json', 'allowlist.json', 'verification-policy.json',
                     'attempt-' + str(state['attempt'])):
            partial = task / name
            if partial.is_symlink() or partial.is_file():
                partial.unlink()
            elif partial.is_dir():
                shutil.rmtree(partial)
        # Extract only fixed filenames. All writes stay in a private temporary dir.
        with tempfile.TemporaryDirectory(dir=task, prefix='import-') as td:
            stage = Path(td)
            bundle = stage / 'baseline.bundle'; bundle.write_bytes(files['baseline.bundle'])
            repo = stage / 'source'
            sha = safe.sha(original['baseline'])
            git(stage, 'init', '--object-format=' + ('sha256' if len(sha) == 64 else 'sha1'), str(repo))
            git(repo, 'bundle', 'verify', str(bundle))
            git(repo, 'fetch', '--no-tags', str(bundle), 'HEAD')
            git(repo, 'checkout', '--detach', original['baseline'])
            effective = dict(c, baseline=original['baseline'], repo_path=str(repo))
            save(stage / 'config.json', effective)
            for name in ('issue.json', 'allowlist.json', 'verification-policy.json'):
                (stage / name).write_bytes(files[name])
            folder = stage / ('attempt-' + str(state['attempt'])); folder.mkdir()
            for name in REPORTS:
                (folder / name).write_bytes(files['attempt/' + name])
            if safe.load_json(stage / 'allowlist.json') != c['allowed_paths']:
                raise ValueError('Handoff allowlist differs from approved project')
            import shlex
            if safe.load_json(stage / 'verification-policy.json') != {
                    'baseline': effective['baseline'], 'checks': [
                        {'id': v['id'], 'command': shlex.join(v['argv'])} for v in c['checks']]}:
                raise ValueError('Handoff verification policy mismatch')
            gate(folder)
            if safe.load_json(folder / 'change.json')['patch_sha256'] != state['patch_sha256']:
                raise ValueError('Handoff state patch digest mismatch')
            effective['repo_path'] = str(task / 'source')
            save(stage / 'config.json', effective)
            for name in ('source', 'config.json', 'issue.json', 'allowlist.json', 'verification-policy.json', folder.name):
                (stage / name).replace(task / name)
        state.update(handoff_verified=True, handoff_digest=digest(Path(path).read_bytes()))
        save(saved_state, state)
        return task / 'config.json', state, generation
