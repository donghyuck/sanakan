#!/usr/bin/env python3
"""Validate the guide distribution; never executes templates or contacts a network."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRS = {".git", ".omx", "__pycache__"}
GENERATED = {"MANIFEST.txt", "SHA256SUMS"}


def files():
    found = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symlink not allowed: {relative}")
        if path.is_file():
            if path.suffix == ".pyc" or path.name == ".DS_Store":
                continue
            found.append(path)
    return sorted(found, key=lambda path: path.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Regenerate manifest/checksums after reviewed release changes.")
    args = parser.parse_args()
    required = [".gitattributes", ".gitignore", ".github/workflows/validate-guide.yml",
                ".gitlab-ci.yml", "LICENSE", "README.md", "VERSION", "CHANGELOG.md", "PUBLISHING.md", "VALIDATION.md",
                "docs/STUDIO_ADOPTION.md", "templates/automation/safe_artifacts.py",
                "tests/test_automation.py"]
    for name in required:
        if not (ROOT / name).is_file():
            raise ValueError(f"Missing required file: {name}")
    payload = [path for path in files() if path.relative_to(ROOT).as_posix() not in GENERATED]
    for path in payload:
        name = path.relative_to(ROOT).as_posix()
        if path.name.startswith(".env") or path.suffix in {".log", ".zip", ".pem", ".key"}:
            raise ValueError(f"Local/credential artifact prohibited: {name}")
        text = path.read_text(encoding="utf-8")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{30,}", text):
            raise ValueError(f"Possible secret: {name}")
        if re.search(r"/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/", text):
            raise ValueError(f"Personal absolute path: {name}")
        if any(line.rstrip() != line for line in text.splitlines()):
            raise ValueError(f"Trailing whitespace: {name}")
        if path.suffix == ".json":
            json.loads(text)
        elif path.suffix == ".toml":
            tomllib.loads(text)
        elif path.suffix == ".py":
            compile(text, name, "exec")
        elif path.suffix == ".sh":
            subprocess.run(["bash", "-n", str(path)], check=True)
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if re.match(r"[a-zA-Z][\w+.-]*:", target) or target.startswith("#"):
                    continue
                target = target.split("#", 1)[0]
                if target and not (path.parent / target).exists():
                    raise ValueError(f"Broken local link: {name} -> {target}")
    names = [path.relative_to(ROOT).as_posix() for path in payload] + sorted(GENERATED)
    manifest = "\n".join(sorted(names)) + "\n"
    hashes = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(ROOT).as_posix() + "\n"
                     for path in payload)
    hashes += hashlib.sha256(manifest.encode()).hexdigest() + "  MANIFEST.txt\n"
    if args.refresh:
        (ROOT / "MANIFEST.txt").write_text(manifest, encoding="utf-8")
        (ROOT / "SHA256SUMS").write_text(hashes, encoding="utf-8")
    elif (ROOT / "MANIFEST.txt").read_text(encoding="utf-8") != manifest or (ROOT / "SHA256SUMS").read_text(encoding="utf-8") != hashes:
        raise ValueError("Manifest/checksum mismatch; review changes before --refresh.")
    print(f"PASS: {len(payload)} payload files; links, JSON/TOML/Python, shell syntax, manifest and SHA-256")
    print("NOTE: YAML platform lint, model execution and real GitLab/GitHub integration are not validated here.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
