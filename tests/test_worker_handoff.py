"""A worker can hand implementation to the verifier without bypassing its sandbox."""
import copy
import unittest
import test_runner as fixtures
from sanakan.runner import run


class DeferredAgents(fixtures.Agents):
    def __init__(self, final_status='completed'):
        super().__init__()
        self.final_status = final_status

    def run(self, role, workspace, output, context):
        if role == 'worker-report':
            self.calls.append(role)
            assert context['verification']['status'] == 'passed'
            assert context['verification']['exit_codes'] == [0]
            result = copy.deepcopy(context['implementation'])
            result.update(status=self.final_status, unverified_items=[], verification_results=['Host verification passed'])
            result['acceptance_results'][0]['met'] = self.final_status == 'completed'
            return result
        result = super().run(role, workspace, output, context)
        if role == 'worker':
            result.update(status='implemented', unverified_items=['Host verification pending'])
            result['acceptance_results'][0]['met'] = False
        return result


class WorkerHandoffTests(unittest.TestCase):
    setUp = fixtures.RunnerTests.setUp

    def test_host_verifies_before_readonly_report_and_review(self):
        agents = DeferredAgents()
        result = run(self.path, self.url, self.runs, agents, self.provider)
        self.assertEqual(result['status'], 'ready', result)
        self.assertEqual(agents.calls, ['main', 'worker', 'worker-report', 'reviewer'])
        self.assertEqual(len(list(self.runs.rglob('implementation-draft.json'))), 1)

    def test_unresolved_completion_report_blocks_review(self):
        agents = DeferredAgents('blocked')
        result = run(self.path, self.url, self.runs, agents, self.provider)
        self.assertEqual(result['status'], 'needs_human', result)
        self.assertNotIn('reviewer', agents.calls)

    def test_failed_verification_does_not_finalize(self):
        from sanakan.common import save
        import sys
        self.c['checks'][0]['argv'] = [sys.executable, '-c', 'raise SystemExit(1)']
        save(self.path, self.c)
        agents = DeferredAgents()
        result = run(self.path, self.url, self.runs, agents, self.provider)
        self.assertEqual(result['status'], 'needs_human')
        self.assertNotIn('worker-report', agents.calls)
        self.assertNotIn('reviewer', agents.calls)


if __name__ == '__main__':
    unittest.main()
