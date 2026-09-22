"""Regression evidence for source identity, SHA transport, revalidation and handoff."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_runner as fixtures
import test_service as services
from sanakan import service, handoff
from sanakan.common import checkout, save, task_dir, process
from sanakan.execution import docker_argv, container
from sanakan.runner import run
from sanakan.publisher import publish

DOCKER = {'backend': 'docker', 'image': 'fixture@sha256:' + 'a' * 64, 'agent_network': 'model-test'}


class StabilizationTests(unittest.TestCase):
    setUp = fixtures.RunnerTests.setUp

    def test_fetch_only_sha_reaches_worker(self):
        source = self.root / 'clone'
        subprocess.run(['git', 'clone', '-q', str(self.repo), str(source)], check=True)
        (self.repo / 'new.txt').write_text('new remote revision')
        self.provider.git('add', '.'); self.provider.git('commit', '-qm', 'advance')
        sha = self.provider.git('rev-parse', 'HEAD')
        subprocess.run(['git', '-C', str(source), 'fetch', '-q', 'origin'], check=True)
        self.assertNotEqual(subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(), sha)
        worker = self.root / 'worker'
        checkout(source, sha, worker)
        self.assertEqual((worker / 'new.txt').read_text(), 'new remote revision')
        self.assertEqual(subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(), self.baseline)

    def test_verification_source_mutation_rejected(self):
        self.c['checks'] = [{'id': 'rewrite', 'argv': [sys.executable, '-c',
            'from pathlib import Path; Path("value.txt").write_text("rewritten"); assert Path("value.txt").read_text()=="rewritten"']}]
        save(self.path, self.c)
        agents = fixtures.Agents()
        state = run(self.path, self.url, self.runs, agents, self.provider)
        self.assertEqual(state['status'], 'failed')
        self.assertIn('changed the source tree', state['reason'])
        self.assertNotIn('reviewer', agents.calls)

    def test_each_check_stops_before_next_command(self):
        marker = self.root / 'stop'
        later = self.root / 'later'
        self.c['checks'] = [
            {'id': 'first', 'argv': [sys.executable, '-c', 'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()']},
            {'id': 'later', 'argv': [sys.executable, '-c', 'from pathlib import Path; Path(' + repr(str(later)) + ').touch()']}]
        save(self.path, self.c)
        state = run(self.path, self.url, self.runs, fixtures.Agents(), self.provider, stop_requested=marker.exists)
        self.assertEqual(state['status'], 'stopped')
        self.assertFalse(later.exists())

    def test_local_result_cannot_publish_or_export(self):
        state = run(self.path, self.url, self.runs, fixtures.Agents(), self.provider)
        self.assertEqual(state['status'], 'ready')
        with self.assertRaisesRegex(ValueError, 'isolated handoff'):
            publish(self.path, self.url, self.runs, self.provider)
        with self.assertRaisesRegex(ValueError, 'Docker'):
            handoff.export_run(self.path, self.url, self.runs)

    def ready_packet(self):
        self.c['execution'] = DOCKER
        save(self.path, self.c)
        with patch('sanakan.execution.container', side_effect=lambda execution, workspace, command, timeout, log, **kw:
                   process(command, workspace, timeout, log=log)):
            result = run(self.path, self.url, self.runs, fixtures.Agents(), self.provider)
        self.assertEqual(result['status'], 'ready', result)
        return handoff.export_run(self.path, self.url, self.runs)

    def test_signed_handoff_separate_store_and_source(self):
        packet = self.ready_packet()
        self.assertEqual(packet.stat().st_mode & 0o777, 0o640)
        settings, state, _ = handoff.import_run(self.path, packet, self.root / 'publisher')
        self.assertTrue(state['handoff_verified'])
        self.assertNotEqual(json.loads(settings.read_text())['repo_path'], self.c['repo_path'])
        self.assertEqual(publish(settings, self.url, self.root / 'publisher', self.provider)['status'], 'published')
        # Controller state stays private and is not overwritten by the publisher.
        original = json.loads((task_dir(self.runs, self.c, 1) / 'state.json').read_text())
        self.assertEqual(original['status'], 'ready')
        self.assertEqual(task_dir(self.runs, self.c, 1).stat().st_mode & 0o777, 0o700)

    def test_handoff_tamper_and_wrong_key_rejected(self):
        packet = self.ready_packet()
        original = packet.read_bytes()
        body = json.loads(original); body['payload']['generation'] = 99
        packet.write_text(json.dumps(body))
        with self.assertRaisesRegex(ValueError, 'signature'):
            handoff.import_run(self.path, packet, self.root / 'publisher')
        packet.write_bytes(original)
        self.keyfile.write_bytes(os.urandom(32))
        with self.assertRaisesRegex(ValueError, 'signature'):
            handoff.import_run(self.path, packet, self.root / 'publisher')

    def test_container_mounts_and_no_host_credentials_for_checks(self):
        argv = docker_argv(DOCKER, self.repo, ['python3', '-m', 'unittest'], 'fixture')
        self.assertEqual(argv[argv.index('--network')+1], 'none')
        self.assertIn('--cap-drop=ALL', argv)
        self.assertIn('--read-only', argv)
        self.assertIn('--pull=never', argv)
        self.assertNotIn(str(self.keyfile), ' '.join(argv))
        self.assertNotIn(str(Path.home()), ' '.join(argv))
        self.assertNotIn('OPENAI_API_KEY', argv)
        readonly = docker_argv(DOCKER, self.repo, ['codex'], 'fixture', readonly=True, model=True)
        self.assertIn('type=bind,src=' + str(self.repo.resolve()) + ',dst=/workspace,readonly', readonly)

    def test_timeout_removes_container(self):
        with patch('sanakan.execution.process', side_effect=[ValueError('timeout'), (0, b'')]) as launch:
            with self.assertRaisesRegex(ValueError, 'timeout'):
                container(DOCKER, self.repo, ['false'], 1, self.root / 'log')
        self.assertEqual(launch.call_args_list[-1].args[0][:3], ['docker', 'rm', '-f'])

    def test_publish_mode_cannot_restart_failed_development(self):
        helper = services.ServiceTests(); helper.setUp()
        try:
            helper.prepare(); helper.agents = fixtures.Agents('info')
            helper.poll('develop')
            with self.assertRaisesRegex(ValueError, 'No reusable publication'):
                service.retry(helper.path, helper.runs, 1, mode='publish')
            self.assertEqual(helper.job()['generation'], 1)
        finally:
            helper.doCleanups()

    def test_stale_target_revalidation_creates_new_generation(self):
        # Exercise public management flow on distinct controller/publisher stores.
        helper = services.ServiceTests(); helper.setUp()
        try:
            helper.prepare(); helper.c['automation']['baseline_mode'] = 'target'; save(helper.path, helper.c)
            helper.poll('develop')
            (helper.repo / 'notes.txt').write_text('new target')
            helper.provider.git('add', '.'); helper.provider.git('commit', '-qm', 'advance')
            helper.provider.baseline = helper.provider.git('rev-parse', 'HEAD')
            helper.poll('publish')
            self.assertEqual(helper.job()['status'], 'needs_revalidation')
            service.retry(helper.path, helper.runs, 1, mode='revalidate')
            helper.poll('develop')
            self.assertEqual(helper.job()['generation'], 2)
            self.assertEqual(helper.job()['status'], 'handed_off', helper.job())
            helper.poll('publish')
            self.assertEqual(helper.job()['status'], 'published', helper.job())
        finally:
            helper.doCleanups()


if __name__ == '__main__':
    unittest.main()
