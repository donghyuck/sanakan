"""GitHub.com REST adapter with the same publication contract as GitLab.

Create Git objects then a new ref (never PATCH/force-update a ref). PR and review
requests are separate, recoverable writes. Do not treat Draft as reviewer delivery.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener
from .gitlab import NoRedirect


class GitHub:
    def __init__(self, origin, project_path, project_id, token):
        if origin != 'https://github.com' or len(project_path.split('/')) != 2:
            raise ValueError('Only github.com owner/repository projects are supported')
        self.origin = origin
        self.project_path = project_path
        self.project_id = project_id
        self.token = token
        self.base = 'https://api.github.com/repos/' + '/'.join(quote(p, safe='') for p in project_path.split('/'))
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, optional=False):
        request = Request(self.base + path, method=method,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={'Authorization': 'Bearer ' + self.token,
                                   'Accept': 'application/vnd.github+json',
                                   'X-GitHub-Api-Version': '2022-11-28',
                                   'User-Agent': 'Sanakan', 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=30) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError('GitHub response exceeds limit')
                return json.loads(data)
        except HTTPError as error:
            if optional and error.code == 404:
                return None
            # Do not echo response bodies/headers (they may contain issue data or tokens).
            raise ValueError('GitHub HTTP error ' + str(error.code) + ' during ' + method + ' ' + path.split('?')[0]) from None
        except (URLError, TimeoutError):
            raise ValueError('GitHub request failed; inspect remote state before retrying') from None

    def identity(self):
        repo = self.request('GET', '')
        if repo['id'] != self.project_id or repo['full_name'].lower() != self.project_path.lower():
            raise ValueError('GitHub repository identity mismatch')

    def paged(self, path, query=None):
        query = dict(query or {})
        result = []
        for page in range(1, 101):
            rows = self.request('GET', path + '?' + urlencode(dict(query, per_page=100, page=page)))
            if not isinstance(rows, list):
                raise ValueError('Unexpected GitHub list response')
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise ValueError('GitHub pagination limit exceeded')

    def normalize_issue(self, value):
        if 'pull_request' in value:
            raise ValueError('GitHub pull requests cannot be used as input issues')
        expected = self.origin + '/' + self.project_path + '/issues/' + str(value['number'])
        if value['html_url'].lower() != expected.lower():
            raise ValueError('GitHub issue belongs to a different repository')
        return dict(iid=value['number'], project_id=self.project_id, title=value['title'],
                    description=value['body'] or '', state='opened' if value['state'] == 'open' else 'closed',
                    updated_at=value['updated_at'], author={'id': value['user']['id']},
                    labels=[label['name'] for label in value.get('labels', [])])

    def issue(self, iid):
        self.identity()
        value = self.request('GET', '/issues/' + str(iid))
        if value['number'] != iid:
            raise ValueError('GitHub issue number mismatch')
        return self.normalize_issue(value)

    def issues(self, labels):
        self.identity()
        query = {'state': 'open', 'sort': 'created', 'direction': 'asc'}
        if labels:
            query['labels'] = ','.join(labels)
        values = self.paged('/issues', query)
        return [self.normalize_issue(v) for v in values if 'pull_request' not in v]

    def branch(self, name):
        self.identity()
        value = self.request('GET', '/git/ref/heads/' + quote(name, safe=''), optional=True)
        if value is None:
            return None
        if value['ref'] != 'refs/heads/' + name or value['object']['type'] != 'commit':
            raise ValueError('Unexpected GitHub ref')
        commit = self.request('GET', '/git/commits/' + quote(value['object']['sha'], safe=''))
        return {'commit': {'id': commit['sha'], 'message': commit['message'],
                           'parent_ids': [p['sha'] for p in commit['parents']]}}

    def tree(self, revision):
        self.identity()
        commit = self.request('GET', '/git/commits/' + quote(revision, safe=''))
        data = self.request('GET', '/git/trees/' + quote(commit['tree']['sha'], safe='') + '?recursive=1')
        if data.get('truncated') is not False:
            raise ValueError('GitHub tree is truncated or incomplete')
        return {entry['path']: (entry['mode'], entry['sha']) for entry in data['tree'] if entry['type'] != 'tree'}

    def create_commit(self, branch, baseline, message, actions):
        self.identity()
        commit = self.request('GET', '/git/commits/' + quote(baseline, safe=''))
        before = self.tree(baseline)
        pending = {}
        for action in actions:
            path = action['file_path']
            previous = pending.get(path, {'mode': before.get(path, ('100644', None))[0],
                                          'sha': before.get(path, (None, None))[1]})
            mode, oid = previous['mode'], previous['sha']
            if action['action'] == 'delete':
                oid = None
            elif action['action'] in {'create', 'update'}:
                blob = self.request('POST', '/git/blobs', {'content': action['content'], 'encoding': 'base64'})
                oid = blob['sha']
            elif action['action'] == 'chmod':
                mode = '100755' if action['execute_filemode'] else '100644'
            else:
                raise ValueError('Unsupported GitHub commit action')
            pending[path] = {'path': path, 'mode': mode, 'type': 'blob', 'sha': oid}
        new_tree = self.request('POST', '/git/trees', {'base_tree': commit['tree']['sha'], 'tree': list(pending.values())})
        created = self.request('POST', '/git/commits', {'message': message, 'tree': new_tree['sha'], 'parents': [baseline]})
        # Creating a ref fails if it exists. There is deliberately no update-ref path.
        self.identity()
        return self.request('POST', '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': created['sha']})

    def normalize_pr(self, pr):
        if pr['base']['repo']['id'] != self.project_id or not pr['head']['repo'] or pr['head']['repo']['id'] != self.project_id:
            raise ValueError('Cross-repository pull requests are not supported')
        return dict(iid=pr['number'], state='opened' if pr['state'] == 'open' else 'closed',
                    source_branch=pr['head']['ref'], target_branch=pr['base']['ref'],
                    sha=pr['head']['sha'], draft=pr['draft'], title=pr['title'],
                    description=pr['body'] or '', web_url=pr['html_url'],
                    reviewers=[{'login': p['login']} for p in pr.get('requested_reviewers', [])])

    def merge_requests(self, branch):
        self.identity()
        owner = self.project_path.split('/')[0]
        values = self.paged('/pulls', {'head': owner + ':' + branch, 'state': 'all'})
        return [self.normalize_pr(p) for p in values
                if p['head'].get('repo') and p['head']['repo']['id'] == self.project_id and p['head']['ref'] == branch]

    def create_merge_request(self, branch, target, title, body, reviewers, draft=True):
        self.identity()
        pr = self.request('POST', '/pulls', {'head': branch, 'base': target, 'title': title,
                                           'body': body, 'draft': True, 'maintainer_can_modify': False})
        return self.normalize_pr(pr)

    def merge_request(self, iid):
        self.identity()
        pr = self.normalize_pr(self.request('GET', '/pulls/' + str(iid)))
        # Already submitted reviews must not trigger another notification on a retry.
        reviews = self.paged('/pulls/' + str(iid) + '/reviews')
        pr['completed_reviewers'] = [v['user']['login'] for v in reviews
                                    if v['state'] in {'APPROVED', 'CHANGES_REQUESTED', 'COMMENTED'} and v.get('user')]
        return pr

    def ensure_reviewers(self, iid, reviewers, draft=True):
        pr = self.merge_request(iid)
        if pr['state'] != 'opened' or pr['draft'] != draft:
            raise ValueError('PR state changed before review request')
        present = {p['login'].lower() for p in pr['reviewers']} | {v.lower() for v in pr['completed_reviewers']}
        missing = [v for v in reviewers if v.lower() not in present]
        if missing:
            self.request('POST', '/pulls/' + str(iid) + '/requested_reviewers', {'reviewers': missing})
        return 'requested'

    def reviewers_satisfied(self, mr, reviewers, draft=True):
        present = {p['login'].lower() for p in mr['reviewers']} | {v.lower() for v in mr.get('completed_reviewers', [])}
        return {v.lower() for v in reviewers} <= present
