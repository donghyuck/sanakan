#!/usr/bin/env python3
"""Build a manifest-only ZIP; refuses overwrites and never includes repository state."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    target = args.output.absolute()
    if target.exists() or target.is_symlink() or target.resolve().is_relative_to(ROOT):
        parser.error("Output must be a new file outside the package directory.")
    subprocess.run([sys.executable, str(ROOT / "tools" / "validate_package.py")], check=True)
    names = (ROOT / "MANIFEST.txt").read_text(encoding="utf-8").splitlines()
    # File list was checked against current files by validate_package.py.
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            part = PurePosixPath(name)
            if part.is_absolute() or ".." in part.parts or name != part.as_posix():
                raise ValueError("Invalid manifest path")
            source = ROOT / name
            archive.write(source, arcname="codex-gitlab-agent-guide/" + name)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        actual = set(archive.namelist())
        expected = {"codex-gitlab-agent-guide/" + name for name in names}
        if actual != expected or len(archive.namelist()) != len(names):
            raise ValueError("ZIP manifest mismatch")
    print(f"PASS: ZIP contains exactly {len(names)} manifest files")
    print(target)


if __name__ == "__main__":
    main()
