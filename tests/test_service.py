"""Offline polling, management, publication format and restart scenarios."""
import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import patch
from test_runner import Agents, Provider
import test_runner as fixtures
from sanakan import service
from sanakan.common import config, save, task_dir, process
from sanakan.policy import DEFAULT_POLICY, validate_policy


class PollProvider(Provider):
    def issues(self, labels):
        return [copy.deepcopy(self.current_issue)]


class ServiceTests(unittest.TestCase):
    setUp = fixtures.RunnerTests.setUp

    def prepare(self, **overrides):
        self.c['automation'] = dict(poll_seconds=1, required_labels=[], baseline_mode='pinned',
                                    fetch_source=False, max_publish_attempts=2, **overrides)
        self.c['execution'] = {'backend': 'docker', 'image': 'fixture@sha256:' + 'a'*64, 'agent_network': 'model-test'}
        fake_container = patch('sanakan.execution.container', side_effect=lambda execution, workspace, command, timeout, log, **kw: process(command, workspace, timeout, log=log))
        fake_container.start(); self.addCleanup(fake_container.stop)
        self.pubruns = self.root / 'publisher-runs'
        self.pubbase = service.directory(self.pubruns, self.c)
        self.last_role = 'develop'
        save(self.path, self.c)
        self.provider = PollProvider(self.issue, self.repo, self.baseline)
        self.agents = Agents()
        self.base = service.directory(self.runs, self.c)

    def poll(self, role):
        self.last_role = role
        return service.watch(self.path, self.runs if role == 'develop' else self.pubruns, role, self.provider, self.agents, once=True)

    def job(self):
        return service.jobs(self.base if self.last_role == 'develop' else self.pubbase)['1']

    def test_issue_to_mr_automatically_and_no_duplicate(self):
        self.prepare()
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'handed_off')
        self.poll('publish')
        self.assertEqual(self.job()['status'], 'published')
        self.poll('develop')
        self.poll('publish')
        self.assertEqual(self.agents.workers, 1)
        self.assertEqual(self.provider.commits, 1)
        self.assertEqual(len(self.provider.mrs), 1)

    def test_new_issue_on_later_poll(self):
        self.prepare()
        self.provider.current_issue['state'] = 'closed'
        self.poll('develop')
        self.assertEqual(service.jobs(self.base), {})
        self.provider.current_issue['state'] = 'opened'
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'handed_off')

    def test_project_formats_and_local_work_branch(self):
        self.prepare()
        self.c['publication'] = dict(DEFAULT_POLICY, branch='agent/task-{iid}',
            commit='[AI] fix(project): #{iid} {title}\n\nIssue: {issue_url}\nValidation: {verification}',
            mr_title='Draft: [AUTO] #{iid} {title}')
        save(self.path, self.c)
        self.poll('develop')
        _, runs = service.layout(self.base, self.job())
        work = task_dir(runs, self.c, 1) / 'worker'
        branch = subprocess.check_output(['git', '-C', str(work), 'branch', '--show-current'], text=True).strip()
        self.assertEqual(branch, 'agent/task-1')
        self.poll('publish')
        self.assertEqual(self.job()['status'], 'published', self.job())
        self.assertTrue(self.provider.branch(branch)['commit']['message'].startswith('[AI] fix(project): #1'))
        self.assertEqual(self.provider.mrs[0]['title'], 'Draft: [AUTO] #1 Fix value')
        self.assertIn('Patch SHA-256:', self.provider.mrs[0]['description'])

    def test_unsupported_format_field_and_no_draft_rejected(self):
        for changes in ({'branch': 'agent/{title}'}, {'commit': '{iid.__class__}'},
                        {'mr_title': 'Ready: {title}'}, {'mr_body': '{summary}'},
                        {'branch': 'agent/no-issue'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_policy(dict(DEFAULT_POLICY, **changes))

    def test_label_filter_and_revocation_before_publish(self):
        self.prepare()
        self.c['automation']['required_labels'] = ['ai:ready']
        save(self.path, self.c)
        self.poll('develop')
        self.assertFalse(service.jobs(self.base))
        self.provider.current_issue['labels'] = ['ai:ready']
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'handed_off')
        self.provider.current_issue['labels'] = []
        self.poll('publish')
        self.assertEqual(self.job()['status'], 'publish_retry')
        self.assertEqual(self.provider.commits, 0)

    def test_publication_error_recovers_next_poll(self):
        self.prepare()
        self.poll('develop')
        self.provider.lost_mr_response = True
        self.poll('publish')
        self.assertEqual(self.job()['status'], 'publish_retry')
        self.poll('publish')
        self.assertEqual(self.job()['status'], 'published')
        self.assertEqual(len(self.provider.mrs), 1)
        self.assertEqual(self.provider.commits, 1)

    def test_bounded_publish_retries_and_explicit_retry(self):
        self.prepare()
        self.poll('develop')
        with patch.object(self.provider, 'issue', side_effect=ValueError('temporary outage')):
            self.poll('publish')
            self.poll('publish')
            self.poll('publish')
        self.assertEqual(self.job()['publish_attempts'], 2)
        self.assertEqual(self.job()['status'], 'publish_failed')
        service.retry(self.path, self.pubruns, 1)
        self.poll('publish')
        self.assertEqual(self.job()['status'], 'published')

    def test_development_failure_not_repeated_and_retry_keeps_history(self):
        self.prepare()
        self.agents = Agents('info')
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'needs_human')
        self.poll('develop')
        self.assertEqual(self.agents.calls, ['main'])
        old_config, old_runs = service.layout(self.base, self.job())
        service.retry(self.path, self.runs, 1)
        self.agents = Agents()
        self.poll('develop')
        self.assertEqual(self.job()['generation'], 2)
        self.assertEqual(self.job()['status'], 'handed_off')
        self.assertTrue(old_config.exists())
        self.assertTrue((task_dir(old_runs, self.c, 1) / 'state.json').exists())

    def test_restart_recovers_ready_but_not_unknown_model_work(self):
        self.prepare()
        self.poll('develop')
        service.update(self.base, 1, status='developing')
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'ready')
        settings, runs = service.layout(self.base, self.job())
        state_path = task_dir(runs, self.c, 1) / 'state.json'
        state = json.loads(state_path.read_text())
        state['status'] = 'implementing'
        save(state_path, state)
        service.update(self.base, 1, status='developing')
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'interrupted')
        self.assertEqual(self.agents.workers, 1)

    def test_cooperative_stop_before_next_phase(self):
        self.prepare()
        outer = self
        class StopAgents(Agents):
            def run(self, role, workspace, output, ctx):
                result = super().run(role, workspace, output, ctx)
                if role == 'worker':
                    service.stop(outer.path, outer.runs, 'develop')
                return result
        self.agents = StopAgents()
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'stopped')
        self.assertNotIn('reviewer', self.agents.calls)

    def test_background_watch_stops_and_status_is_live(self):
        self.prepare()
        self.provider.current_issue['state'] = 'closed'
        thread = threading.Thread(target=service.watch, args=(self.path, self.runs, 'develop', self.provider))
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not (self.base / 'develop/service.json').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(service.status(self.path, self.runs)['services']['develop']['running'])
            service.stop(self.path, self.runs, 'all')
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(service.status(self.path, self.runs)['services']['develop']['running'])
        finally:
            service.stop(self.path, self.runs, 'all')
            thread.join(5)

    def test_changed_policy_blocks_publication(self):
        self.prepare()
        self.poll('develop')
        self.c['reviewer_ids'] = [99]
        save(self.path, self.c)
        self.poll('publish')
        self.assertIn('policy changed', str(service.status(self.path, self.pubruns)['handoff_errors']))
        self.assertEqual(self.provider.commits, 0)

    def test_baseline_target_snapshot_and_fetch_origin_restriction(self):
        self.prepare()
        self.c['automation']['baseline_mode'] = 'target'
        self.c['baseline'] = '0' * 40  # snapshot resolves the target rather than this value
        effective = service.snapshot(self.c, self.provider)
        self.assertEqual(effective['baseline'], self.baseline)
        self.c['automation']['fetch_source'] = True
        self.provider.git('remote', 'add', 'origin', 'https://other.invalid/repo.git')
        with self.assertRaisesRegex(ValueError, 'configured HTTPS'):
            service.snapshot(self.c, self.provider)

    def test_expired_config_can_still_be_stopped_and_inspected(self):
        self.prepare()
        self.c['expires_at'] = 1
        save(self.path, self.c)
        service.stop(self.path, self.runs, 'all')
        self.assertTrue(service.status(self.path, self.runs)['services']['develop']['stop_requested'])

    def test_start_filters_credentials_and_confirms_child_pid(self):
        self.prepare()
        folder = self.base / 'publish'
        folder.mkdir(parents=True)
        save(folder / 'service.json', {'pid': 1234})
        import os
        with patch.dict(os.environ, {'SANAKAN_PUBLISH_TOKEN': 'publisher', 'SANAKAN_READ_TOKEN': 'reader',
                                      'OPENAI_API_KEY': 'model-key'}), \
                patch('sanakan.service.config', return_value=self.c), \
                patch('sanakan.service.busy', side_effect=[False, True]), \
                patch('sanakan.service.subprocess.Popen') as spawn:
            spawn.return_value.pid = 1234
            spawn.return_value.poll.return_value = None
            result = service.start(self.path, self.runs, 'publish')
            env = spawn.call_args.kwargs['env']
            self.assertEqual(result['status'], 'started')
            self.assertEqual(env['SANAKAN_PUBLISH_TOKEN'], 'publisher')
            self.assertNotIn('SANAKAN_READ_TOKEN', env)
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('publisher', ' '.join(spawn.call_args.args[0]))

    def test_start_development_rejects_publish_credentials(self):
        self.prepare()
        import os
        with patch.dict(os.environ, {'SANAKAN_READ_TOKEN': 'reader', 'SANAKAN_PUBLISH_TOKEN': 'publisher'}):
            with self.assertRaisesRegex(ValueError, 'publish token'):
                service.start(self.path, self.runs, 'develop')

    def test_existing_remote_branch_blocks_new_development(self):
        self.prepare()
        self.provider.git('branch', 'codex/issue-1', self.baseline)
        self.poll('develop')
        self.assertEqual(self.job()['status'], 'failed')
        self.assertEqual(self.agents.calls, [])

    def test_parallel_registry_updates_do_not_drop_jobs(self):
        self.prepare()
        self.base.mkdir(parents=True)
        save(self.base / 'jobs.json', {'1': {'iid': 1}, '2': {'iid': 2}})
        failures = []
        def update(i):
            try:
                service.update(self.base, i, status='ready')
            except Exception as error:
                failures.append(error)
        threads = [threading.Thread(target=update, args=(i,)) for i in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(failures, [])
        self.assertEqual({j['status'] for j in service.jobs(self.base).values()}, {'ready'})

    def test_issues_api_pagination_and_scope(self):
        from sanakan.gitlab import GitLab
        client = GitLab(self.c['gitlab_url'], 1, 'fake')
        with patch.object(client, 'request', side_effect=[
                [{'iid': i} for i in range(1, 101)], [{'iid': 101}]]) as request:
            self.assertEqual(len(client.issues(['ai:ready'])), 101)
        paths = [call.args[1] for call in request.call_args_list]
        self.assertIn('scope=all', paths[0])
        self.assertIn('page=2', paths[1])
        self.assertIn('labels=ai%3Aready', paths[0])


if __name__ == '__main__':
    unittest.main()
