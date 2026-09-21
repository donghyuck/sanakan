#!/usr/bin/env python3
"""Build a standalone skills + CLI runtime plugin ZIP; no account configuration writes."""
import argparse
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    target = args.output.absolute()
    if target.exists() or target.is_symlink() or target.resolve().is_relative_to(ROOT):
        parser.error('Output must be a new file outside the repository')
    subprocess.run([sys.executable, str(ROOT / 'tools/validate_package.py')], check=True)
    entries = {}
    for name in (ROOT / 'MANIFEST.txt').read_text().splitlines():
        if name.startswith('plugins/sanakan/'):
            entries[name.removeprefix('plugins/sanakan/')] = ROOT / name
        elif name.startswith(('sanakan/', 'templates/automation/')):
            entries['runtime/' + name] = ROOT / name
    entries['assets/automation-project.json'] = ROOT / 'examples/runner/automation-project.json'
    entries['assets/AUTOMATION.md'] = ROOT / 'docs/AUTOMATION.md'
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in sorted(entries.items()):
            if name == 'assets/AUTOMATION.md':
                content = source.read_text().replace('../examples/runner/automation-project.json', 'automation-project.json')
                archive.writestr(name, content)
            else:
                archive.write(source, name)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(entries):
            raise ValueError('Plugin ZIP integrity mismatch')
    print('Plugin ZIP ready: ' + str(target))


if __name__ == '__main__':
    main()
