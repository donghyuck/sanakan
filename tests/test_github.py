"""GitHub REST contract simulation with real Git objects and signed handoff."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit, parse_qs
import test_runner as fixtures
from sanakan.github import GitHub
from sanakan.hosting import make_provider
from sanakan.common import config, issue_iid, save, task_dir
from sanakan.publisher import publish
from sanakan import service, handoff


class GitHubServer(GitHub):
    """Emulates REST payloads, not the platform-independent publisher interface."""
    def __init__(self, repo, baseline, issue):
        super().__init__('https://github.com', 'team/project', 1, 'fixture-token')
        self.repo, self.baseline, self.current_issue = repo, baseline, issue
        self.calls = []
        self.prs = []
        self.review_posts = 0
        self.lost_ref = self.lost_pr = self.lost_review = False
        self.reject_review = False
        self.truncated = False
        self.reported_project_id = 1
        self.submitted_reviews = []

    def git(self, *args, data=None, env=None):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], input=data,
                                       env=env, stderr=subprocess.DEVNULL).decode().strip()

    def commit_data(self, sha):
        return {'sha': sha, 'message': self.git('show', '-s', '--format=%B', sha),
                'parents': [{'sha': v} for v in self.git('show', '-s', '--format=%P', sha).split()],
                'tree': {'sha': self.git('rev-parse', sha + '^{tree}')}}

    def ref(self, name):
        if name == 'main':
            return self.baseline
        try:
            return self.git('rev-parse', '--verify', 'refs/heads/' + name)
        except subprocess.CalledProcessError:
            return None

    def request(self, method, path, body=None, optional=False):
        self.calls.append((method, path, copy.deepcopy(body)))
        query = parse_qs(urlsplit(path).query)
        path = urlsplit(path).path
        if method == 'GET' and path == '':
            return {'id': self.reported_project_id, 'full_name': 'team/project'}
        if method == 'GET' and path == '/issues':
            values = [copy.deepcopy(self.current_issue)]
            # GitHub's issues endpoint also returns pull requests.
            values.append(dict(self.current_issue, number=999, pull_request={}))
            return values if query.get('page') == ['1'] else []
        if method == 'GET' and path == '/issues/1':
            return copy.deepcopy(self.current_issue)
        if method == 'GET' and path.startswith('/git/ref/heads/'):
            name = unquote(path.removeprefix('/git/ref/heads/'))
            sha = self.ref(name)
            return {'ref': 'refs/heads/' + name, 'object': {'type': 'commit', 'sha': sha}} if sha else None
        if method == 'GET' and path.startswith('/git/commits/'):
            return self.commit_data(path.split('/')[-1])
        if method == 'GET' and path.startswith('/git/trees/'):
            raw = subprocess.check_output(['git', '-C', str(self.repo), 'ls-tree', '-rz', path.split('/')[-1]])
            entries = []
            for entry in raw.split(b'\0'):
                if entry:
                    meta, name = entry.split(b'\t', 1)
                    mode, kind, sha = meta.decode().split()
                    entries.append({'path': name.decode(), 'type': kind, 'mode': mode, 'sha': sha})
            return {'tree': entries, 'truncated': self.truncated}
        if method == 'POST' and path == '/git/blobs':
            return {'sha': self.git('hash-object', '-w', '--stdin', data=base64.b64decode(body['content']))}
        if method == 'POST' and path == '/git/trees':
            with tempfile.TemporaryDirectory() as td:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / 'index'))
                self.git('read-tree', body['base_tree'], env=env)
                for entry in body['tree']:
                    if entry['sha'] is None:
                        self.git('update-index', '--force-remove', '--', entry['path'], env=env)
                    else:
                        row = (entry['mode'] + ' ' + entry['sha'] + '\t' + entry['path'] + '\0').encode()
                        self.git('update-index', '-z', '--index-info', data=row, env=env)
                return {'sha': self.git('write-tree', env=env)}
        if method == 'POST' and path == '/git/commits':
            sha = self.git('commit-tree', body['tree'], '-p', body['parents'][0], data=body['message'].encode())
            return {'sha': sha}
        if method == 'POST' and path == '/git/refs':
            self.git('update-ref', body['ref'], body['sha'], '0' * 40)
            if self.lost_ref:
                self.lost_ref = False
                raise ValueError('Lost ref creation response')
            return {'ref': body['ref'], 'object': {'sha': body['sha']}}
        if method == 'GET' and path == '/pulls':
            return copy.deepcopy(self.prs)
        if method == 'POST' and path == '/pulls':
            value = {'number': 1, 'state': 'open', 'draft': body['draft'], 'title': body['title'],
                     'body': body['body'], 'html_url': 'https://github.com/team/project/pull/1',
                     'head': {'ref': body['head'], 'sha': self.ref(body['head']), 'repo': {'id': 1}},
                     'base': {'ref': body['base'], 'repo': {'id': 1}}, 'requested_reviewers': []}
            self.prs.append(value)
            if self.lost_pr:
                self.lost_pr = False
                raise ValueError('Lost PR creation response')
            return copy.deepcopy(value)
        if method == 'GET' and path == '/pulls/1':
            value = copy.deepcopy(self.prs[0])
            value['head']['sha'] = self.ref(value['head']['ref'])
            return value
        if method == 'GET' and path == '/pulls/1/reviews':
            return copy.deepcopy(self.submitted_reviews)
        if method == 'POST' and path == '/pulls/1/requested_reviewers':
            if self.reject_review:
                raise ValueError('GitHub HTTP error 422 during review request')
            self.review_posts += 1
            self.prs[0]['requested_reviewers'].extend({'login': v} for v in body['reviewers'])
            if self.lost_review:
                self.lost_review = False
                raise ValueError('Lost review request response')
            return copy.deepcopy(self.prs[0])
        raise AssertionError((method, path, body))


class GitHubTests(unittest.TestCase):
    run_task = fixtures.RunnerTests.run_task

    def setUp(self):
        fixtures.RunnerTests.setUp(self)
        self.c.pop('gitlab_url'); self.c.pop('reviewer_ids')
        self.c.update(provider='github', github_url='https://github.com', reviewers=['reviewer'])
        save(self.path, self.c)
        self.url = 'https://github.com/team/project/issues/1'
        raw = dict(number=1, state='open', title=self.issue['title'], body=self.issue['description'],
                   updated_at=self.issue['updated_at'], user={'id': 10}, labels=[], html_url=self.url)
        self.provider = GitHubServer(self.repo, self.baseline, raw)

    def test_config_routing_url_and_namespace(self):
        c = config(self.path)
        self.assertIsInstance(make_provider(c, 'token'), GitHub)
        self.assertEqual(issue_iid(c, self.url), 1)
        for invalid in (self.url + '?x=1', self.url.replace('/issues/', '/pull/'), self.url.replace('team/', 'other/')):
            with self.assertRaises(ValueError):
                issue_iid(c, invalid)
        self.assertEqual(self.provider.issue(1)['state'], 'opened')
        self.assertEqual(len(self.provider.issues([])), 1)
        self.provider.current_issue['pull_request'] = {}
        with self.assertRaisesRegex(ValueError, 'input issues'):
            self.provider.issue(1)

    def test_draft_pr_review_and_idempotent_republish(self):
        self.assertEqual(self.run_task()['status'], 'ready')
        result = publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.assertEqual(result['pr_url'], 'https://github.com/team/project/pull/1')
        self.assertEqual(result['review_status'], 'requested')
        self.assertTrue(self.provider.prs[0]['draft'])
        self.assertIn('Validation:', self.provider.branch('codex/issue-1')['commit']['message'])
        publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.assertEqual(len(self.provider.prs), 1)
        self.assertEqual(self.provider.review_posts, 1)
        self.assertFalse(any(method == 'PATCH' for method, _, _ in self.provider.calls))

    def test_each_ambiguous_write_resumes(self):
        self.run_task()
        for name in ('lost_ref', 'lost_pr', 'lost_review'):
            setattr(self.provider, name, True)
            with self.assertRaisesRegex(ValueError, 'Lost'):
                publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.assertEqual(publish(self.publish_config, self.url, self.publish_runs, self.provider)['status'], 'published')
        self.assertEqual(len(self.provider.prs), 1)
        self.assertEqual(self.provider.review_posts, 1)

    def test_review_rejection_does_not_convert_draft_or_succeed(self):
        self.run_task(); self.provider.reject_review = True
        with self.assertRaisesRegex(ValueError, '422'):
            publish(self.publish_config, self.url, self.publish_runs, self.provider)
        state = json.loads((task_dir(self.publish_runs, self.c, 1) / 'state.json').read_text())
        self.assertEqual(state['status'], 'publishing')
        self.assertTrue(self.provider.prs[0]['draft'])
        self.assertEqual(self.provider.review_posts, 0)

    def test_completed_review_does_not_notify_again(self):
        self.run_task()
        publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.provider.prs[0]['requested_reviewers'] = []
        self.provider.submitted_reviews = [{'state': 'APPROVED', 'user': {'login': 'Reviewer'}}]
        publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.assertEqual(self.provider.review_posts, 1)

    def test_repo_identity_and_truncated_tree_rejected(self):
        self.provider.reported_project_id = 999
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.provider.issue(1)
        self.provider.reported_project_id = 1
        self.provider.truncated = True
        with self.assertRaisesRegex(ValueError, 'truncated'):
            self.provider.tree(self.baseline)

    def test_binary_create_delete_execute_mode(self):
        # Use the common API actions produced by the trusted collector/publisher.
        actions = [{'action': 'delete', 'file_path': 'value.txt'},
                   {'action': 'create', 'file_path': 'data.bin', 'content': base64.b64encode(bytes(range(256))).decode()},
                   {'action': 'create', 'file_path': 'run.sh', 'content': base64.b64encode(b'exit 0\n').decode()},
                   {'action': 'chmod', 'file_path': 'run.sh', 'execute_filemode': True}]
        self.provider.create_commit('codex/files', self.baseline, 'fixture commit', actions)
        commit = self.provider.branch('codex/files')['commit']
        result = self.provider.tree(commit['id'])
        self.assertNotIn('value.txt', result)
        self.assertEqual(result['run.sh'][0], '100755')
        data = subprocess.check_output(['git', '-C', str(self.repo), 'cat-file', 'blob', result['data.bin'][1]])
        self.assertEqual(data, bytes(range(256)))
        self.assertEqual(commit['parent_ids'], [self.baseline])

    def test_foreign_pr_rejected_before_review_request(self):
        self.run_task()
        self.provider.lost_pr = True
        with self.assertRaises(ValueError):
            publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.provider.prs[0]['base']['repo']['id'] = 999
        with self.assertRaisesRegex(ValueError, 'Cross-repository'):
            publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.assertEqual(self.provider.review_posts, 0)

    def test_deleted_pr_branch_is_not_recreated(self):
        self.run_task()
        self.provider.lost_pr = True
        with self.assertRaises(ValueError):
            publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.provider.git('update-ref', '-d', 'refs/heads/codex/issue-1')
        creates = sum(path == '/git/refs' and method == 'POST' for method, path, _ in self.provider.calls)
        with self.assertRaisesRegex(ValueError, 'do not recreate'):
            publish(self.publish_config, self.url, self.publish_runs, self.provider)
        self.assertEqual(creates, sum(path == '/git/refs' and method == 'POST' for method, path, _ in self.provider.calls))

    def test_mixed_platform_config_rejected(self):
        self.c['gitlab_url'] = 'https://gitlab.example.com'
        save(self.path, self.c)
        with self.assertRaisesRegex(ValueError, 'Unknown or missing'):
            config(self.path)

    def test_transport_headers_redirect_and_pagination(self):
        from urllib.error import HTTPError
        client = make_provider(self.c, 'private-token')
        with patch.object(client.opener, 'open', side_effect=HTTPError('url', 302, 'redirect', {}, None)) as request:
            with self.assertRaisesRegex(ValueError, '302'):
                client.request('GET', '/issues')
        sent = request.call_args.args[0]
        self.assertEqual(sent.get_header('Authorization'), 'Bearer private-token')
        self.assertNotIn('private-token', sent.full_url)
        with patch.object(client, 'request', side_effect=[[{'x': i} for i in range(100)], [{'x': 101}]]) as request:
            self.assertEqual(len(client.paged('/issues')), 101)
        self.assertIn('page=2', request.call_args_list[-1].args[1])

    def test_github_polling_handoff_and_publish(self):
        self.c.update(execution={'backend': 'docker', 'image': 'fixture@sha256:'+'a'*64, 'agent_network':'model-test'},
                      automation=dict(poll_seconds=1, required_labels=[], baseline_mode='target', fetch_source=False, max_publish_attempts=2))
        save(self.path, self.c)
        from sanakan.common import process
        with patch('sanakan.execution.container', side_effect=lambda execution, workspace, command, timeout, log, **kw:
                   process(command, workspace, timeout, log=log)):
            result = service.watch(self.path, self.runs, 'develop', self.provider, fixtures.Agents(), once=True)
        self.assertEqual(result['jobs']['1']['status'], 'handed_off')
        result = service.watch(self.path, self.root/'publisher', 'publish', self.provider, once=True)
        self.assertEqual(result['jobs']['1']['status'], 'published', result)
        self.assertEqual(result['jobs']['1']['pr_url'], 'https://github.com/team/project/pull/1')


if __name__ == '__main__':
    unittest.main()
