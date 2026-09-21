"""Separate trusted publishing process. It never executes generated project code."""
import base64
import json
import tempfile
import time
from pathlib import Path
from .common import checkout, check_issue, config, digest, git, issue_iid, locked, safe, save, task_dir
from .runner import gate
from .policy import publication


def tree(repo, revision):
    result = {}
    for entry in git(repo, 'ls-tree', '-r', '-z', revision).split(b'\0'):
        if entry:
            details, path = entry.split(b'\t', 1)
            mode, kind, oid = details.decode().split(' ')
            result[path.decode()] = (mode, oid)
    return result


def actions(repo, baseline, final, changed):
    before, after = tree(repo, baseline), tree(repo, final)
    result = []
    for path in changed:
        if path not in after:
            result.append({'action': 'delete', 'file_path': path})
            continue
        mode, oid = after[path]
        if path not in before or before[path][1] != oid:
            result.append({'action': 'create' if path not in before else 'update', 'file_path': path,
                           'encoding': 'base64', 'content': base64.b64encode(git(repo, 'cat-file', 'blob', oid)).decode()})
        previous_mode = before.get(path, ('100644', None))[0]
        if mode != previous_mode:
            result.append({'action': 'chmod', 'file_path': path, 'execute_filemode': mode == '100755'})
    return result


def publish(config_path, issue_url, root, provider, stop_requested=lambda: False):
    c = config(config_path)
    iid = issue_iid(c, issue_url)
    with locked(task_dir(root, c, iid)) as task:
        state_path = task / 'state.json'
        state = safe.load_json(state_path)
        if state['fixture']:
            raise ValueError('Fixture runs cannot be published')
        if state['status'] not in {'ready', 'publishing', 'published'}:
            raise ValueError('Run is not ready to publish')
        if safe.load_json(task / 'config.json') != c:
            raise ValueError('Publication config differs from run config')
        issue = check_issue(c, iid, provider.issue(iid))
        if issue != safe.load_json(task / 'issue.json'):
            raise ValueError('Issue changed after implementation; publication stopped')
        key = digest(json.dumps({'config': c, 'issue': issue}, sort_keys=True).encode())
        if key != state['key']:
            raise ValueError('Run identity mismatch')
        if type(state['attempt']) is not int or not 1 <= state['attempt'] <= c['max_attempts']:
            raise ValueError('Invalid attempt')
        folder = task / ('attempt-' + str(state['attempt']))
        gate(folder)
        manifest = safe.read_artifact(folder / 'change.json', 'manifest')
        if manifest['patch_sha256'] != state['patch_sha256']:
            raise ValueError('Ready patch changed')
        def check_current():
            if stop_requested():
                raise ValueError('Stop requested; publication stopped at a phase boundary')
            if c['expires_at'] <= time.time():
                raise ValueError('Project authorization expired')
            current = check_issue(c, iid, provider.issue(iid))
            if current != issue:
                raise ValueError('Issue changed during publication')
            target = provider.branch(c['target_branch'])
            if not target or target['commit']['id'] != c['baseline']:
                raise ValueError('Target branch advanced; rebase and revalidation required')

        check_current()
        formatted = publication(c, issue, issue_url,
            safe.load_json(folder / 'implementation.json'), safe.load_json(folder / 'verification.json'),
            safe.load_json(folder / 'review.json'), manifest, state['key'])
        branch_name = formatted['branch']
        git(Path(c['repo_path']), 'check-ref-format', '--branch', branch_name)
        if branch_name == c['target_branch']:
            raise ValueError('Work branch must differ from target')
        # Build the exact final tree from the immutable patch, never from worker checkout.
        with tempfile.TemporaryDirectory(prefix='sanakan-publish-') as scratch:
            repo = Path(scratch) / 'repo'
            checkout(c['repo_path'], c['baseline'], repo)
            git(repo, 'apply', '--index', str(folder / 'change.patch'))
            final = git(repo, 'write-tree').decode().strip()
            expected = tree(repo, final)
            state['status'] = 'publishing'
            save(state_path, state)
            branch = provider.branch(branch_name)
            if not branch:
                check_current()
                # One atomic commit creates the branch; never force or overwrite a branch.
                provider.request('POST', '/repository/commits', {
                    'branch': branch_name, 'start_sha': c['baseline'],
                    'commit_message': formatted['commit'],
                    'actions': actions(repo, c['baseline'], final, manifest['changed_files'])})
                branch = provider.branch(branch_name)
            commit = branch['commit']
            if formatted['commit'].strip() != commit['message'].strip() or commit['parent_ids'] != [c['baseline']]:
                raise ValueError('Existing branch belongs to another change')
            if provider.tree(commit['id']) != expected:
                raise ValueError('Remote tree differs from verified patch')
        check_current()
        existing = provider.merge_requests(branch_name)
        if len(existing) > 1:
            raise ValueError('Multiple merge requests for this branch')
        if existing:
            mr = existing[0]
        else:
            mr = provider.request('POST', '/merge_requests', {
                'source_branch': branch_name, 'target_branch': c['target_branch'],
                'title': formatted['mr_title'], 'description': formatted['mr_body'],
                'reviewer_ids': c['reviewer_ids'], 'remove_source_branch': False})
        # Re-read after both creation and retry, including ambiguous POST results.
        mr = provider.request('GET', '/merge_requests/' + str(mr['iid']))
        if (mr['state'] != 'opened' or mr['source_branch'] != branch_name or
                mr['target_branch'] != c['target_branch'] or mr['sha'] != commit['id'] or
                not mr['draft'] or mr['title'] != formatted['mr_title'] or
                mr['description'] != formatted['mr_body'] or
                not set(c['reviewer_ids']) <= {user['id'] for user in mr['reviewers']}):
            raise ValueError('Merge request readback mismatch; human inspection required')
        check_current()
        state.update(status='published', mr_url=mr['web_url'], commit=commit['id'])
        save(state_path, state)
        return state
