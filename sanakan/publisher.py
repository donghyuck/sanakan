"""Separate trusted publishing process. It never executes generated project code."""
import base64
import json
import tempfile
import time
from pathlib import Path
from .common import checkout, check_issue, config, digest, git, issue_iid, locked, safe, save, task_dir, run_identity
from .runner import gate
from .policy import publication
from .errors import RevalidationRequired
from .hosting import reviewers, draft, platform


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
    raw = safe.load_json(config_path)
    if raw['expires_at'] <= time.time():
        raise RevalidationRequired('Project authorization expired')
    c = config(config_path)
    iid = issue_iid(c, issue_url)
    with locked(task_dir(root, c, iid)) as task:
        state_path = task / 'state.json'
        state = safe.load_json(state_path)
        if state['fixture']:
            raise ValueError('Fixture runs cannot be published')
        if state['status'] not in {'ready', 'publishing', 'published'}:
            raise ValueError('Run is not ready to publish')
        if not state.get('handoff_verified') or state.get('execution') != 'docker':
            raise ValueError('Publication requires an authenticated isolated handoff')
        if safe.load_json(task / 'config.json') != c:
            raise RevalidationRequired('Publication config differs from run config')
        issue = check_issue(c, iid, provider.issue(iid))
        if issue != safe.load_json(task / 'issue.json'):
            raise RevalidationRequired('Issue changed after implementation; publication stopped')
        key = run_identity(c, issue)
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
                raise RevalidationRequired('Project authorization expired')
            current = check_issue(c, iid, provider.issue(iid))
            if current != issue:
                raise RevalidationRequired('Issue changed during publication')
            target = provider.branch(c['target_branch'])
            if not target or target['commit']['id'] != c['baseline']:
                raise RevalidationRequired('Target branch advanced; rebase and revalidation required')

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
                if provider.merge_requests(branch_name):
                    raise ValueError('Existing review request has no source branch; do not recreate it automatically')
                check_current()
                # One atomic commit creates the branch; never force or overwrite a branch.
                provider.create_commit(branch_name, c['baseline'], formatted['commit'],
                                       actions(repo, c['baseline'], final, manifest['changed_files']))
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
            mr = provider.create_merge_request(branch_name, c['target_branch'], formatted['mr_title'],
                                               formatted['mr_body'], reviewers(c), draft=draft(c))
        # Re-read after both creation and retry, including ambiguous POST results.
        mr = provider.merge_request(mr['iid'])
        def check_request(value):
            if (value['state'] != 'opened' or value['source_branch'] != branch_name or
                    value['target_branch'] != c['target_branch'] or value['sha'] != commit['id'] or
                    value['draft'] != draft(c) or value['title'] != formatted['mr_title'] or
                    value['description'] != formatted['mr_body']):
                raise ValueError('Merge request readback mismatch; human inspection required')
        check_request(mr)
        # Never request reviews on a mismatched/foreign PR; resume this step after an ambiguous response.
        check_current()
        review_status = provider.ensure_reviewers(mr['iid'], reviewers(c), draft=draft(c))
        mr = provider.merge_request(mr['iid'])
        check_request(mr)
        if not provider.reviewers_satisfied(mr, reviewers(c), draft=draft(c)):
            raise ValueError('Review request readback mismatch')
        check_current()
        state.update(review_status=review_status, review_url=mr['web_url'])
        if platform(c) == 'github':
            state['pr_url'] = mr['web_url']
        state.update(status='published', mr_url=mr['web_url'], commit=commit['id'])
        save(state_path, state)
        return state
