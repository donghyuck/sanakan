"""Issue -> main agent -> worker -> verification -> independent review -> ready."""
import json
from pathlib import Path
import shlex
import time
from types import SimpleNamespace
from .common import (AUTOMATION, checkout, check_issue, config, digest, git, issue_iid,
                     locked, process, safe, save, task_dir)


def collect(c, workspace, folder):
    safe.collect(SimpleNamespace(repo=str(workspace), baseline=c['baseline'],
                                allowlist=str(folder.parent / 'allowlist.json'),
                                output_prefix=str(folder / 'change')))
    if (folder / 'change.patch').stat().st_size > c['max_patch_bytes']:
        raise ValueError('Patch size exceeds project limit')
    return safe.read_artifact(folder / 'change.json', 'manifest')


def gate(folder):
    c = safe.load_json(folder.parent / 'config.json')
    safe.gate(SimpleNamespace(baseline=c['baseline'], allowlist=folder.parent / 'allowlist.json',
                             manifest=folder / 'change.json', patch=folder / 'change.patch',
                             triage=folder / 'triage.json', implementation=folder / 'implementation.json',
                             review=folder / 'review.json', verification=folder / 'verification.json',
                             verification_policy=folder.parent / 'verification-policy.json'))


def verify(c, workspace, folder, manifest):
    codes = []
    for index, check in enumerate(c['checks']):
        code, _ = process(check['argv'], workspace, c['timeout_seconds'],
                          log=folder / ('check-' + str(index) + '.log'))
        codes.append(max(code, 1) if code < 0 else code)
    result = dict(baseline=c['baseline'], patch_sha256=manifest['patch_sha256'],
                  status='passed' if all(code == 0 for code in codes) else 'failed',
                  commands=[shlex.join(check['argv']) for check in c['checks']],
                  check_ids=[check['id'] for check in c['checks']], exit_codes=codes)
    save(folder / 'verification.json', result)
    return result


def run(config_path, issue_url, root, agents, provider=None, fixture=None):
    c = config(config_path)
    iid = issue_iid(c, issue_url)
    issue = check_issue(c, iid, fixture if fixture is not None else provider.issue(iid))
    key = digest(json.dumps({'config': c, 'issue': issue}, sort_keys=True).encode())
    with locked(task_dir(root, c, iid)) as task:
        state_path = task / 'state.json'
        if state_path.exists():
            existing = safe.load_json(state_path)
            if existing['key'] != key:
                raise ValueError('Issue/config revision changed; use a new run root after inspecting previous state')
            # Never silently restart work, consume model budget again or overwrite evidence.
            return existing
        save(task / 'config.json', c)
        save(task / 'issue.json', issue)
        save(task / 'allowlist.json', c['allowed_paths'])
        save(task / 'verification-policy.json', {
            'baseline': c['baseline'], 'checks': [
                {'id': check['id'], 'command': shlex.join(check['argv'])} for check in c['checks']]})
        state = {'key': key, 'status': 'starting', 'issue_url': issue_url,
                 'fixture': fixture is not None, 'attempt': 0, 'started_at': time.time()}

        def transition(status, **fields):
            state.update(status=status, **fields)
            save(state_path, state)

        transition('starting')
        try:
            worker = task / 'worker'
            checkout(c['repo_path'], c['baseline'], worker)
            feedback = {}
            for attempt in range(1, c['max_attempts'] + 1):
                if c['expires_at'] <= time.time():
                    raise ValueError('Project authorization expired')
                folder = task / ('attempt-' + str(attempt))
                folder.mkdir()
                context = {'baseline': c['baseline'], 'issue': issue, 'allowed_paths': c['allowed_paths'],
                           'verification_policy': safe.load_json(task / 'verification-policy.json'),
                           'feedback': feedback}
                transition('planning', attempt=attempt)
                triage = agents.run('main', worker, folder / 'triage.json', context)
                # Main decides whether another implementation round is appropriate.
                safe.validate(triage, safe.load_json(AUTOMATION / 'schemas/triage-schema.json'))
                save(folder / 'triage.json', triage)
                if triage['baseline'] != c['baseline']:
                    raise ValueError('Main agent baseline mismatch')
                if triage['decision'] != 'implement' or triage['risk'] != 'low' or triage['prohibited_change_detected'] or triage['missing_information'] or triage['approval_reasons']:
                    transition('needs_human', reason=triage['reason'], questions=triage['missing_information'])
                    return state
                if not set(triage['affected_files']) <= set(c['allowed_paths']):
                    raise ValueError('Main agent plan exceeds approved paths')
                context['triage'] = triage
                transition('implementing')
                implementation = agents.run('worker', worker, folder / 'implementation.json', context)
                safe.validate(implementation, safe.load_json(AUTOMATION / 'schemas/implementation-schema.json'))
                save(folder / 'implementation.json', implementation)
                if implementation['status'] == 'failed':
                    feedback = {'implementation': implementation}
                    continue
                if implementation['status'] != 'completed':
                    transition('needs_human', reason='Worker did not complete', questions=implementation['pm_questions'])
                    return state
                transition('collecting')
                manifest = collect(c, worker, folder)
                # Verifier and reviewer each get a new checkout. Test side effects cannot
                # alter the source the reviewer sees or the final published patch.
                verify_workspace = folder / 'verify'
                checkout(c['repo_path'], c['baseline'], verify_workspace)
                git(verify_workspace, 'apply', '--index', str(folder / 'change.patch'))
                transition('verifying')
                verification = verify(c, verify_workspace, folder, manifest)
                context.update(implementation=implementation, verification=verification,
                               patch=str(folder / 'change.patch'), patch_sha256=manifest['patch_sha256'])
                if verification['status'] != 'passed':
                    feedback = {'verification': verification,
                                'logs': [str(folder / ('check-' + str(i) + '.log')) for i in range(len(c['checks']))]}
                    continue
                review_workspace = folder / 'review'
                checkout(c['repo_path'], c['baseline'], review_workspace)
                git(review_workspace, 'apply', '--index', str(folder / 'change.patch'))
                transition('reviewing')
                review = agents.run('reviewer', review_workspace, folder / 'review.json', context)
                safe.validate(review, safe.load_json(AUTOMATION / 'schemas/review-schema.json'))
                save(folder / 'review.json', review)
                if review['baseline'] != c['baseline'] or review['patch_sha256'] != manifest['patch_sha256']:
                    raise ValueError('Reviewer examined a different patch')
                if review['decision'] == 'needs_human_review':
                    transition('needs_human', reason=review['summary'])
                    return state
                if review['decision'] != 'pass' or review['blocking_count'] or any(f['severity'] in {'blocking', 'high'} for f in review['findings']):
                    feedback = {'review': review}
                    continue
                gate(folder)
                transition('ready', patch_sha256=manifest['patch_sha256'])
                return state
            transition('needs_human', reason='Repair attempt limit reached', feedback=feedback)
        except (ValueError, OSError, KeyError, TypeError) as error:
            transition('failed', reason=str(error))
        return state
