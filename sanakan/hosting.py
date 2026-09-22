"""Platform routing and canonical project/issue identity."""
def platform(c):
    return c.get('provider', 'gitlab')


def origin(c):
    return c['github_url'] if platform(c) == 'github' else c['gitlab_url']


def namespace(c):
    # Preserve GitLab's existing state-directory identity.
    prefix = 'github:' if platform(c) == 'github' else ''
    return prefix + origin(c) + '/' + c['project_path']


def issue_prefix(c):
    return origin(c) + '/' + c['project_path'] + ('/issues/' if platform(c) == 'github' else '/-/issues/')


def reviewers(c):
    return c['reviewers'] if platform(c) == 'github' else c['reviewer_ids']


def draft(c):
    return True


def make_provider(c, token):
    if platform(c) == 'github':
        from .github import GitHub
        return GitHub(origin(c), c['project_path'], c['project_id'], token)
    from .gitlab import GitLab
    return GitLab(origin(c), c['project_id'], token)
