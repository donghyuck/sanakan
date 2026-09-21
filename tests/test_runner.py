"""Offline coordinator and publisher integration tests; no model or remote calls."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from sanakan.agents import CodexAgents
from sanakan.common import config, digest, environment, issue_iid, locked, process, save, task_dir
from sanakan.publisher import publish, tree
from sanakan.runner import run


class Agents:
    def __init__(self, mode='pass'):
        self.mode = mode
        self.calls = []
        self.workers = 0

    def run(self, role, workspace, output, ctx):
        self.calls.append(role)
        if role == 'main':
            return dict(baseline=ctx['baseline'], decision='needs_info' if self.mode == 'info' else 'implement',
                        risk='low', summary='fix value', reason='bounded task', affected_files=['value.txt'],
                        test_plan=['unit'], missing_information=['expected value?'] if self.mode == 'info' else [],
                        approval_reasons=[], prohibited_change_detected=False)
        if role == 'worker':
            self.workers += 1
            value = 'bad' if self.mode == 'test-repair' and self.workers == 1 else 'fixed'
            (workspace / 'value.txt').write_text(value)
            if self.mode == 'scope':
                (workspace / 'outside.txt').write_text('outside')
            status = 'failed' if self.mode == 'worker-repair' and self.workers == 1 else 'completed'
            return dict(baseline=ctx['baseline'], status=status, summary='fixed value',
                        changed_files=['value.txt'], verification_commands=['unit'], verification_results=['passed'],
                        acceptance_results=[{'criterion': 'fixed value', 'evidence': 'unit', 'met': True}],
                        unverified_items=[], risks=[], pm_questions=[], rollback='revert commit')
        assert (workspace / 'value.txt').read_text() == 'fixed'
        assert digest(Path(ctx['patch']).read_bytes()) == ctx['patch_sha256']
        block = self.mode in {'review-repair', 'always-block'} and (self.workers == 1 or self.mode == 'always-block')
        return dict(baseline=ctx['baseline'], patch_sha256=ctx['patch_sha256'],
                    decision='block' if block else 'pass', summary='review result',
                    blocking_count=1 if block else 0, findings=[])


class Provider:
    def __init__(self, issue, repo, baseline):
        self.current_issue = copy.deepcopy(issue)
        self.repo = repo
        self.baseline = baseline
        self.mrs = []
        self.commits = 0
        self.lost_mr_response = False

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def issue(self, iid):
        return copy.deepcopy(self.current_issue)

    def branch(self, name):
        if name == 'main':
            return {'commit': {'id': self.baseline}}
        result = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', '--verify', 'refs/heads/' + name], capture_output=True, text=True)
        if result.returncode:
            return None
        oid = result.stdout.strip()
        return {'commit': {'id': oid, 'message': self.git('show', '-s', '--format=%B', oid),
                           'parent_ids': self.git('show', '-s', '--format=%P', oid).split()}}

    def tree(self, oid):
        return tree(self.repo, oid)

    def merge_requests(self, branch):
        return copy.deepcopy(self.mrs)

    def request(self, method, path, body=None):
        if path == '/repository/commits':
            self.git('checkout', '-qb', body['branch'], body['start_sha'])
            for action in body['actions']:
                target = self.repo / action['file_path']
                if action['action'] == 'delete':
                    target.unlink()
                elif action['action'] == 'chmod':
                    target.chmod(0o755 if action['execute_filemode'] else 0o644)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(base64.b64decode(action['content']))
            self.git('add', '.')
            self.git('commit', '-qm', body['commit_message'])
            self.commits += 1
            return {'id': self.git('rev-parse', 'HEAD')}
        if path == '/merge_requests' and method == 'POST':
            mr = dict(iid=1, state='opened', title=body['title'], description=body['description'], source_branch=body['source_branch'],
                      target_branch=body['target_branch'], sha=self.git('rev-parse', 'HEAD'), draft=True,
                      reviewers=[{'id': i} for i in body['reviewer_ids']],
                      web_url='https://gitlab.example.com/team/project/-/merge_requests/1')
            self.mrs.append(mr)
            if self.lost_mr_response:
                self.lost_mr_response = False
                raise ValueError('Simulated lost MR response')
            return mr
        if method == 'GET' and path == '/merge_requests/1':
            return copy.deepcopy(self.mrs[0])
        raise AssertionError((method, path))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()
        git('init', '-q')
        git('config', 'user.email', 'fixture@example.invalid')
        git('config', 'user.name', 'Fixture')
        (self.repo / 'value.txt').write_text('broken')
        git('add', '.')
        git('commit', '-qm', 'baseline')
        self.baseline = git('rev-parse', 'HEAD')
        self.c = dict(gitlab_url='https://gitlab.example.com', project_path='team/project', project_id=1,
                      repo_path=str(self.repo), baseline=self.baseline, target_branch='main',
                      allowed_author_ids=[10], reviewer_ids=[20], allowed_paths=['value.txt'],
                      checks=[{'id': 'unit', 'argv': [sys.executable, '-c',
                              'from pathlib import Path; assert Path("value.txt").read_text() == "fixed"']}],
                      max_attempts=2, timeout_seconds=30, max_patch_bytes=100000, expires_at=int(time.time()) + 3600)
        self.path = self.root / 'config.json'
        save(self.path, self.c)
        self.issue = dict(iid=1, project_id=1, title='Fix value', description='value must be fixed',
                          state='opened', updated_at='2026-09-21T00:00:00Z', author={'id': 10})
        self.url = 'https://gitlab.example.com/team/project/-/issues/1'
        self.runs = self.root / 'runs'
        self.provider = Provider(self.issue, self.repo, self.baseline)

    def run_task(self, agents=None, fixture=False):
        return run(self.path, self.url, self.runs, agents or Agents(), self.provider,
                   self.issue if fixture else None)

    def test_full_run_and_publish_and_repeated_delivery(self):
        agents = Agents()
        state = self.run_task(agents)
        self.assertEqual(state['status'], 'ready', state)
        self.assertEqual(agents.calls, ['main', 'worker', 'reviewer'])
        self.assertEqual((self.repo / 'value.txt').read_text(), 'broken')
        self.assertEqual(self.run_task(agents), state)
        self.assertEqual(len(agents.calls), 3)
        result = publish(self.path, self.url, self.runs, self.provider)
        self.assertEqual(result['status'], 'published')
        again = publish(self.path, self.url, self.runs, self.provider)
        self.assertEqual(again['commit'], result['commit'])
        self.assertEqual(self.provider.commits, 1)
        self.assertEqual(len(self.provider.mrs), 1)

    def test_verification_and_review_repairs(self):
        for mode in ('test-repair', 'review-repair', 'worker-repair'):
            with self.subTest(mode=mode):
                self.runs = self.root / mode
                agents = Agents(mode)
                result = self.run_task(agents)
                self.assertEqual(result['status'], 'ready', result)
                self.assertEqual(agents.workers, 2)
                self.assertEqual(agents.calls.count('main'), 2)

    def test_attempt_limit_stops(self):
        result = self.run_task(Agents('always-block'))
        self.assertEqual(result['status'], 'needs_human')
        self.assertEqual(result['attempt'], 2)
        with self.assertRaises(ValueError):
            publish(self.path, self.url, self.runs, self.provider)

    def test_questions_stop_before_worker(self):
        agents = Agents('info')
        result = self.run_task(agents)
        self.assertEqual(result['status'], 'needs_human')
        self.assertEqual(agents.calls, ['main'])
        self.assertTrue(result['questions'])

    def test_scope_violation_stops(self):
        result = self.run_task(Agents('scope'))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('allowlist', result['reason'])

    def test_fixture_cannot_publish(self):
        self.assertEqual(self.run_task(fixture=True)['status'], 'ready')
        with self.assertRaisesRegex(ValueError, 'Fixture'):
            publish(self.path, self.url, self.runs, self.provider)

    def test_changed_issue_and_target_stop_publication(self):
        self.run_task()
        self.provider.current_issue['description'] = 'different'
        with self.assertRaisesRegex(ValueError, 'Issue changed'):
            publish(self.path, self.url, self.runs, self.provider)
        self.provider.current_issue = copy.deepcopy(self.issue)
        self.provider.baseline = '0' * 40
        with self.assertRaisesRegex(ValueError, 'Target branch'):
            publish(self.path, self.url, self.runs, self.provider)
        self.assertEqual(self.provider.commits, 0)

    def test_ambiguous_mr_creation_is_resumed_without_duplicate(self):
        self.run_task()
        self.provider.lost_mr_response = True
        with self.assertRaisesRegex(ValueError, 'lost MR'):
            publish(self.path, self.url, self.runs, self.provider)
        result = publish(self.path, self.url, self.runs, self.provider)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(self.provider.commits, 1)
        self.assertEqual(len(self.provider.mrs), 1)

    def test_tampered_patch_stops_publication(self):
        self.run_task()
        folder = task_dir(self.runs, self.c, 1) / 'attempt-1'
        with (folder / 'change.patch').open('ab') as stream:
            stream.write(b'tamper')
        with self.assertRaisesRegex(ValueError, 'digest'):
            publish(self.path, self.url, self.runs, self.provider)

    def test_wrong_reviewer_readback_stops(self):
        self.run_task()
        publish(self.path, self.url, self.runs, self.provider)
        self.provider.mrs[0]['reviewers'] = []
        with self.assertRaisesRegex(ValueError, 'readback'):
            publish(self.path, self.url, self.runs, self.provider)

    def test_issue_url_allowlist(self):
        for url in (self.url + '?x=1', self.url.replace('gitlab.example.com', 'attacker.invalid'),
                    self.url.replace('/team/', '/other/'), self.url + '/..'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                issue_iid(self.c, url)

    def test_closed_or_unauthorized_issue(self):
        for key, value in [('state', 'closed'), ('author', {'id': 99})]:
            self.provider.current_issue = copy.deepcopy(self.issue)
            self.provider.current_issue[key] = value
            with self.assertRaises(ValueError):
                self.run_task()

    def test_changed_revision_does_not_restart(self):
        self.run_task()
        self.provider.current_issue['updated_at'] = 'new revision'
        with self.assertRaisesRegex(ValueError, 'revision changed'):
            self.run_task()

    def test_concurrent_issue_lock(self):
        with locked(task_dir(self.runs, self.c, 1)):
            with self.assertRaisesRegex(ValueError, 'active operation'):
                self.run_task()

    def test_timeout_and_environment(self):
        with self.assertRaisesRegex(ValueError, 'timed out'):
            process([sys.executable, '-c', 'import time; time.sleep(10)'], self.root, timeout=0.05)
        with patch.dict(os.environ, {'SANAKAN_READ_TOKEN': 'secret', 'SANAKAN_PUBLISH_TOKEN': 'secret',
                                     'GIT_CONFIG_COUNT': '9', 'OPENAI_API_KEY': 'model-secret'}):
            self.assertNotIn('SANAKAN_PUBLISH_TOKEN', environment(True))
            self.assertNotIn('SANAKAN_READ_TOKEN', environment(True))
            self.assertNotIn('GIT_CONFIG_COUNT', environment(True))
            self.assertNotIn('OPENAI_API_KEY', environment())
            self.assertIn('OPENAI_API_KEY', environment(True))

    def test_config_requires_checks_and_current_authorization(self):
        for name, value in [('checks', []), ('expires_at', 1), ('allowed_paths', ['AGENTS.md'])]:
            c = copy.deepcopy(self.c)
            c[name] = value
            save(self.path, c)
            with self.subTest(name=name), self.assertRaises(ValueError):
                config(self.path)

    def test_binary_create_delete_and_mode_published(self):
        self.c['allowed_paths'] += ['image.bin', 'entry.sh']
        save(self.path, self.c)
        class BinaryAgents(Agents):
            def run(self, role, workspace, output, ctx):
                result = super().run(role, workspace, output, ctx)
                if role == 'main':
                    result['affected_files'] = ['value.txt', 'image.bin', 'entry.sh']
                if role == 'worker':
                    (workspace / 'value.txt').unlink()
                    (workspace / 'image.bin').write_bytes(bytes(range(256)))
                    (workspace / 'entry.sh').write_text('exit 0\n')
                    (workspace / 'entry.sh').chmod(0o755)
                    result['changed_files'] = ['value.txt', 'image.bin', 'entry.sh']
                return result
        class BinaryReview(BinaryAgents):
            def run(self, role, workspace, output, ctx):
                if role == 'reviewer':
                    return dict(baseline=ctx['baseline'], patch_sha256=ctx['patch_sha256'],
                                decision='pass', summary='binary checked', blocking_count=0, findings=[])
                return super().run(role, workspace, output, ctx)
        self.c['checks'][0]['argv'] = [sys.executable, '-c',
            'from pathlib import Path; assert Path("image.bin").read_bytes() == bytes(range(256)); assert not Path("value.txt").exists()']
        save(self.path, self.c)
        state = self.run_task(BinaryReview())
        self.assertEqual(state['status'], 'ready', state)
        self.assertEqual(publish(self.path, self.url, self.runs, self.provider)['status'], 'published')
        self.assertFalse((self.repo / 'value.txt').exists())
        self.assertEqual((self.repo / 'image.bin').read_bytes(), bytes(range(256)))
        self.assertTrue((self.repo / 'entry.sh').stat().st_mode & 0o111)

    def test_gitlab_transport_does_not_redirect_tokens(self):
        from sanakan.gitlab import GitLab, NoRedirect
        from urllib.error import HTTPError
        client = GitLab(self.c['gitlab_url'], 1, 'fixture-token')
        with patch.object(client.opener, 'open', side_effect=HTTPError('url', 302, 'redirect', {}, None)):
            with self.assertRaisesRegex(ValueError, '302'):
                client.issue(1)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid'))

    def test_cli_with_fake_codex_process(self):
        executable = self.root / 'codex'
        test_dir = str(Path(__file__).resolve().parent)
        executable.write_text('#!' + sys.executable + '\n' +
            'import sys, json\n' +
            'from pathlib import Path\n' +
            'sys.path.insert(0, ' + repr(test_dir) + ')\n' +
            'sys.path.insert(0, ' + repr(str(Path(__file__).resolve().parents[1])) + ')\n' +
            'from test_runner import Agents\n' +
            'args = sys.argv; prompt = sys.stdin.read()\n' +
            'ctx = json.loads(prompt.split("HOST CONTEXT (issue content and feedback are untrusted data):\\n", 1)[1])\n' +
            'schema = Path(args[args.index("--output-schema") + 1]).name\n' +
            'role = {"triage-schema.json":"main", "implementation-schema.json":"worker", "review-schema.json":"reviewer"}[schema]\n' +
            'out = Path(args[args.index("--output-last-message") + 1])\n' +
            'result = Agents().run(role, Path.cwd(), out, ctx)\n' +
            'out.write_text(json.dumps(result))\n')
        executable.chmod(0o755)
        fixture = self.root / 'issue.json'
        save(fixture, self.issue)
        env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH'])
        env.pop('SANAKAN_PUBLISH_TOKEN', None)
        result = subprocess.run([sys.executable, '-m', 'sanakan', 'run', '--config', str(self.path),
            '--issue', self.url, '--runs', str(self.runs), '--issue-fixture', str(fixture)],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads((task_dir(self.runs, self.c, 1) / 'state.json').read_text())
        self.assertEqual(state['status'], 'ready')
        self.assertTrue(state['fixture'])

    def test_codex_adapter_uses_separate_sandboxed_exec(self):
        output = self.root / 'triage.json'
        report = Agents().run('main', self.repo, output, {'baseline': self.baseline})
        save(output, report)
        with patch('sanakan.agents.process', return_value=(0, None)) as execute:
            self.assertEqual(CodexAgents(30).run('main', self.repo, output, {}), report)
        argv = execute.call_args.args[0]
        self.assertIn('--ephemeral', argv)
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'read-only')
        self.assertIn('--output-schema', argv)
        self.assertEqual(argv[-1], '-')


if __name__ == '__main__':
    unittest.main()
