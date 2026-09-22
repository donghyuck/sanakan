"""Explicit local development mode and bounded Docker execution boundary."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
from .common import AUTOMATION, environment, process, safe


def validate_execution(value):
    if value == {'backend': 'local'}:
        return
    if not isinstance(value, dict) or set(value) != {'backend', 'image', 'agent_network'}:
        raise ValueError('execution requires local backend or docker/image/agent_network')
    if value['backend'] != 'docker' or not re.fullmatch(r'[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}', value['image']):
        raise ValueError('Docker execution requires a digest-pinned image')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', value['agent_network']) or value['agent_network'] in {'host', 'bridge', 'default'}:
        raise ValueError('Use a dedicated restricted agent network, not host/default/bridge')


def docker_argv(execution, workspace, command, name, readonly=False, mounts=(), model=False):
    validate_execution(execution)
    workspace = Path(workspace).resolve(strict=True)
    if ',' in str(workspace):
        raise ValueError('Comma in Docker mount path is not supported')
    mount = 'type=bind,src=' + str(workspace) + ',dst=/workspace' + (',readonly' if readonly else '')
    uid = os.getuid() or 1000
    argv = ['docker', 'run', '--rm', '--init', '--pull=never', '--name', name,
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--user', str(uid) + ':' + str(os.getgid() or 1000), '--pids-limit=256',
            '--memory=2g', '--cpus=2', '--network', execution['agent_network'] if model else 'none',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m,mode=1777',
            '--env', 'HOME=/tmp', '--env', 'GIT_CONFIG_GLOBAL=/dev/null',
            '--env', 'GIT_CONFIG_NOSYSTEM=1', '--env', 'GIT_NO_REPLACE_OBJECTS=1',
            '--workdir', '/workspace', '--mount', mount]
    for source, target, ro in mounts:
        source = str(Path(source).resolve(strict=True))
        if ',' in source:
            raise ValueError('Comma in Docker mount path is not supported')
        argv += ['--mount', 'type=bind,src=' + source + ',dst=' + target + (',readonly' if ro else '')]
    if model:
        argv += ['--interactive', '--env', 'CODEX_HOME=/output/codex']
        if os.environ.get('OPENAI_API_KEY'):
            argv += ['--env', 'OPENAI_API_KEY']  # Docker reads the value from its environment.
    return argv + ['--entrypoint', command[0], execution['image'], *command[1:]]


def container(execution, workspace, command, timeout, log, *, data=None, readonly=False, mounts=(), model=False):
    name = 'sanakan-' + uuid.uuid4().hex
    argv = docker_argv(execution, workspace, command, name, readonly, mounts, model)
    try:
        return process(argv, workspace, timeout, data, log, agent=model)
    finally:
        # Killing only the Docker client is not enough when a timeout occurs.
        process(['docker', 'rm', '-f', name], workspace, timeout=30)


def run_check(c, command, workspace, log):
    execution = c.get('execution', {'backend': 'local'})
    if execution['backend'] == 'local':
        return process(command, workspace, c['timeout_seconds'], log=log)
    return container(execution, workspace, command, c['timeout_seconds'], log)


class DockerAgents:
    def __init__(self, c):
        self.c = c

    def run(self, role, workspace, output, context):
        from .agents import prompt_for
        schema = {'main': 'triage', 'worker': 'implementation', 'reviewer': 'review'}[role]
        with tempfile.TemporaryDirectory(prefix='sanakan-agent-') as td:
            root = Path(td)
            inputs, outputs = root / 'input', root / 'output'
            inputs.mkdir(); outputs.mkdir()
            (outputs / 'codex').mkdir()
            auth = Path(os.environ.get('SANAKAN_CODEX_AUTH_FILE',
                str(Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'auth.json')))
            if auth.is_file():
                shutil.copyfile(auth, outputs / 'codex/auth.json')
            elif not os.environ.get('OPENAI_API_KEY'):
                raise ValueError('Docker agents need Codex auth.json or OPENAI_API_KEY')
            shutil.copyfile(AUTOMATION / 'schemas' / (schema + '-schema.json'), inputs / 'schema.json')
            context = dict(context)
            if 'patch' in context:
                shutil.copyfile(context['patch'], inputs / 'change.patch')
                context['patch'] = '/input/change.patch'
            feedback = dict(context.get('feedback', {}))
            # Pass bounded log text; host filesystem paths are not mounted in the container.
            if 'logs' in feedback:
                feedback['logs'] = [Path(p).read_text(errors='replace')[-16000:] for p in feedback['logs']]
            context['feedback'] = feedback
            prompt = prompt_for(role, context)
            command = ['codex', 'exec', '--ignore-user-config', '--ephemeral', '--color', 'never',
                       '--dangerously-bypass-approvals-and-sandbox',
                       '--output-schema', '/input/schema.json', '--output-last-message', '/output/result.json', '-']
            # The outer container is the sandbox: no host state/keys/sockets, read-only
            # workspace for main/review. This flag is never used by the local adapter.
            code, _ = container(self.c['execution'], workspace, command, self.c['timeout_seconds'],
                                Path(str(output) + '.log'), data=prompt.encode(), readonly=role != 'worker',
                                mounts=((inputs, '/input', True), (outputs, '/output', False)), model=True)
            if code:
                raise ValueError('Docker Codex session failed: ' + role)
            result_path = outputs / 'result.json'
            if result_path.is_symlink() or not result_path.is_file() or result_path.stat().st_size > 1024 * 1024:
                raise ValueError('Invalid agent output file')
            result = safe.read_artifact(result_path, schema)
            from .common import save
            save(output, result)
            return result


def agents_for(c):
    from .agents import CodexAgents
    return DockerAgents(c) if c.get('execution', {}).get('backend') == 'docker' else CodexAgents(c['timeout_seconds'])
