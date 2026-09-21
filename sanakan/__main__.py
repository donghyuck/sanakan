"""Run with python3 -m sanakan --help from the trusted tool checkout."""
import argparse
import json
import os
import sys
from .agents import CodexAgents
from .common import config, safe
from .gitlab import GitLab
from .publisher import publish
from .runner import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('run', 'publish'):
        p = sub.add_parser(command)
        p.add_argument('--config', required=True)
        p.add_argument('--issue', required=True)
        p.add_argument('--runs', required=True)
        if command == 'run':
            p.add_argument('--issue-fixture', help='Offline issue JSON; resulting runs cannot publish')
    args = parser.parse_args()
    try:
        c = config(args.config)
        if args.command == 'run':
            if os.environ.get('SANAKAN_PUBLISH_TOKEN'):
                raise ValueError('Do not inject a publish token into a development run')
            fixture = safe.load_json(args.issue_fixture) if args.issue_fixture else None
            token = os.environ.get('SANAKAN_READ_TOKEN', '')
            if fixture is None and not token:
                raise ValueError('SANAKAN_READ_TOKEN required for GitLab issue reads')
            result = run(args.config, args.issue, args.runs, CodexAgents(c['timeout_seconds']),
                         GitLab(c['gitlab_url'], c['project_id'], token), fixture)
        else:
            token = os.environ.get('SANAKAN_PUBLISH_TOKEN')
            if not token:
                raise ValueError('SANAKAN_PUBLISH_TOKEN required in the separate publisher environment')
            result = publish(args.config, args.issue, args.runs, GitLab(c['gitlab_url'], c['project_id'], token))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] in {'ready', 'published'} else 2
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('STOPPED: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
