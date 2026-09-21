"""Deterministic project publication formats; no model-generated command templates."""
from string import Formatter

DEFAULT_POLICY = {
    'branch': 'codex/issue-{iid}',
    'commit': '[ai-assisted] fix: issue #{iid} {title}\n\nIssue: {issue_url}\nWhy: {title}\nWhat: {summary}\nValidation:\n{verification}',
    'mr_title': 'Draft: #{iid} {title}',
    'mr_body': '## Why\n\n{issue_url}\n\n## What\n\n{summary}\n\n{changed_files}\n\n## Validation\n\n{verification}\n\nBaseline: `{baseline}`\nPatch SHA-256: `{patch_sha256}`\n\nIndependent review: {review_summary}\n\n## Risk / Rollback\n\n{rollback}\n\n## AI / Subagent Usage\n\nMain, worker and reviewer ran in separate Codex sessions. Human review and merge required.\n',
}
FIELDS = {'iid', 'title', 'issue_url', 'project_path', 'baseline', 'summary',
          'verification', 'changed_files', 'patch_sha256', 'review_summary', 'rollback'}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY):
        raise ValueError('Publication policy requires branch, commit, mr_title and mr_body')
    for name, template in policy.items():
        if not isinstance(template, str) or not template.strip() or len(template) > 16000:
            raise ValueError('Invalid publication template: ' + name)
        fields = set()
        for _, field, spec, conversion in Formatter().parse(template):
            if field is None:
                continue
            if field not in FIELDS or spec or conversion:
                raise ValueError('Unsupported publication template field')
            fields.add(field)
        if name == 'branch' and (fields != {'iid'} or '\n' in template or '\r' in template):
            raise ValueError('Branch must include {iid}; no other substitutions are allowed')
        if name == 'commit' and not {'issue_url', 'verification'} <= fields:
            raise ValueError('Commit must include {issue_url} and {verification}')
        if name == 'mr_title' and (not template.startswith('Draft: ') or '\n' in template or '\r' in template):
            raise ValueError('MR title must be a single line beginning with Draft: ')
        if name == 'mr_body' and not {'issue_url', 'verification', 'baseline', 'patch_sha256'} <= fields:
            raise ValueError('MR body must include issue, verification, baseline and patch digest')
    return policy


def branch(c, iid):
    return c.get('publication', DEFAULT_POLICY)['branch'].format(iid=iid)


def publication(c, issue, issue_url, implementation, verification, review, manifest, key):
    policy = validate_policy(c.get('publication', DEFAULT_POLICY))
    values = dict(iid=issue['iid'], title=' '.join(issue['title'].split())[:160],
                  issue_url=issue_url, project_path=c['project_path'], baseline=c['baseline'],
                  summary=implementation['summary'], patch_sha256=manifest['patch_sha256'],
                  rollback=implementation['rollback'], review_summary=review['summary'],
                  changed_files='\n'.join('- ' + p for p in manifest['changed_files']),
                  verification='\n'.join('- ' + command + ': exit ' + str(code)
                      for command, code in zip(verification['commands'], verification['exit_codes'])))
    result = {name: template.format_map(values) for name, template in policy.items()}
    result['commit'] += '\n\nSanakan-Run: ' + key + '\nPatch-SHA256: ' + manifest['patch_sha256']
    if len(result['mr_title']) > 255 or len(result['mr_body']) > 500000:
        raise ValueError('Rendered MR exceeds supported size')
    return result
