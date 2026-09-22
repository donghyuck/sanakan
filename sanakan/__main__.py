"""Run with python3 -m sanakan --help from the trusted tool checkout."""
import argparse
import json
import os
import sys
from .execution import agents_for
from .common import config, safe
from .hosting import make_provider
from .publisher import publish
from .runner import run
from . import service, handoff


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
    for command in ('watch', 'start', 'status', 'stop', 'retry'):
        p = sub.add_parser(command)
        p.add_argument('--config', required=True)
        p.add_argument('--runs', required=True)
        if command in {'watch', 'start'}:
            p.add_argument('--role', choices=service.ROLES, required=True)
        if command == 'watch':
            p.add_argument('--once', action='store_true', help='One polling cycle, then exit')
        if command == 'stop':
            p.add_argument('--role', choices=(*service.ROLES, 'all'), default='all')
        if command == 'retry':
            p.add_argument('--iid', type=int, required=True)
            p.add_argument('--mode', choices=('auto', 'publish', 'revalidate'), default='auto')
    for command in ('export', 'import'):
        p = sub.add_parser(command)
        p.add_argument('--config', required=True)
        p.add_argument('--runs', required=True)
        if command == 'export':
            p.add_argument('--issue', required=True)
        else:
            p.add_argument('--packet', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'export':
            print(handoff.export_run(args.config, args.issue, args.runs))
            return 0
        if args.command == 'import':
            path, state, generation = handoff.import_run(args.config, args.packet, args.runs)
            print(json.dumps({'config': str(path), 'status': state['status'], 'generation': generation}))
            return 0
        if args.command in {'status', 'stop', 'retry', 'start'}:
            if args.command == 'status':
                result = service.status(args.config, args.runs)
            elif args.command == 'stop':
                result = service.stop(args.config, args.runs, args.role)
            elif args.command == 'retry':
                result = service.retry(args.config, args.runs, args.iid, args.mode)
            else:
                result = service.start(args.config, args.runs, args.role)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        c = config(args.config)
        if args.command == 'watch':
            token_key = 'SANAKAN_READ_TOKEN' if args.role == 'develop' else 'SANAKAN_PUBLISH_TOKEN'
            token = os.environ.get(token_key)
            if not token:
                raise ValueError(token_key + ' is required')
            if args.role == 'develop' and os.environ.get('SANAKAN_PUBLISH_TOKEN'):
                raise ValueError('Do not inject a publish token into development')
            result = service.watch(args.config, args.runs, args.role,
                                   make_provider(c, token), once=args.once)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result['services'][args.role].get('last_error') else 0
        if args.command == 'run':
            if os.environ.get('SANAKAN_PUBLISH_TOKEN'):
                raise ValueError('Do not inject a publish token into a development run')
            fixture = safe.load_json(args.issue_fixture) if args.issue_fixture else None
            token = os.environ.get('SANAKAN_READ_TOKEN', '')
            if fixture is None and not token:
                raise ValueError('SANAKAN_READ_TOKEN required for hosted issue reads')
            result = run(args.config, args.issue, args.runs, agents_for(c),
                         make_provider(c, token), fixture)
        else:
            token = os.environ.get('SANAKAN_PUBLISH_TOKEN')
            if not token:
                raise ValueError('SANAKAN_PUBLISH_TOKEN required in the separate publisher environment')
            result = publish(args.config, args.issue, args.runs, make_provider(c, token))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] in {'ready', 'published'} else 2
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('STOPPED: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
