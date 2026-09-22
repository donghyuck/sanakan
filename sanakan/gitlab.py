"""Bounded GitLab REST adapter; credentials are headers, redirects are refused."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitLab:
    def __init__(self, origin, project_id, token):
        self.base = origin + '/api/v4/projects/' + str(project_id)
        self.token = token
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, optional=False):
        request = Request(self.base + path, method=method,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={'PRIVATE-TOKEN': self.token, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=30) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError('GitLab response exceeds limit')
                return json.loads(data)
        except HTTPError as error:
            if optional and error.code == 404:
                return None
            raise ValueError('GitLab HTTP error ' + str(error.code)) from None
        except (URLError, TimeoutError):
            raise ValueError('GitLab request failed; inspect state before retrying') from None

    def issue(self, iid):
        return self.request('GET', '/issues/' + str(iid))

    def branch(self, name):
        return self.request('GET', '/repository/branches/' + quote(name, safe=''), optional=True)

    def tree(self, revision):
        result = {}
        for page in range(1, 101):
            rows = self.request('GET', '/repository/tree?' + urlencode(
                {'ref': revision, 'recursive': 'true', 'per_page': 100, 'page': page}))
            for row in rows:
                if row['type'] != 'tree':
                    result[row['path']] = (row['mode'], row['id'])
            if len(rows) < 100:
                return result
        raise ValueError('Repository tree exceeds pilot pagination limit')

    def merge_requests(self, branch):
        return self.request('GET', '/merge_requests?' + urlencode(
            {'source_branch': branch, 'scope': 'all', 'state': 'all', 'per_page': 100}))

    def issues(self, labels):
        # Read every page before admitting work; offset order is stable for a poll.
        result = {}
        for page in range(1, 101):
            query = {'scope': 'all', 'state': 'opened', 'order_by': 'created_at',
                     'sort': 'asc', 'per_page': 100, 'page': page}
            if labels:
                query['labels'] = ','.join(labels)
            rows = self.request('GET', '/issues?' + urlencode(query))
            for row in rows:
                result[row['iid']] = row
            if len(rows) < 100:
                return list(result.values())
        raise ValueError('Issue listing exceeds pagination limit')

    def create_commit(self, branch, baseline, message, actions):
        return self.request('POST', '/repository/commits', {
            'branch': branch, 'start_sha': baseline, 'commit_message': message, 'actions': actions})

    def create_merge_request(self, branch, target, title, body, reviewers, draft=True):
        return self.request('POST', '/merge_requests', {
            'source_branch': branch, 'target_branch': target, 'title': title,
            'description': body, 'reviewer_ids': reviewers, 'remove_source_branch': False})

    def merge_request(self, iid):
        return self.request('GET', '/merge_requests/' + str(iid))

    def ensure_reviewers(self, iid, reviewers, draft=True):
        # GitLab sets the reviewers in the create request; readback checks them.
        return 'requested'

    def reviewers_satisfied(self, mr, reviewers, draft=True):
        return set(reviewers) <= {user['id'] for user in mr['reviewers']}
