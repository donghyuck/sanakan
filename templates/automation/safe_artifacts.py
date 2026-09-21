#!/usr/bin/env python3
"""Offline reference: collect a bounded patch and reject incomplete review artifacts.

Run a protected copy and protected schemas, never the worker's modified copy.
This is not a sandbox, signature verifier, secret scanner, or publishing service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

SCHEMAS = Path(__file__).resolve().parent / "schemas"
PROTECTED_DIRS = {".git", ".github", ".gitlab", ".codex", ".agent", "automation", "scripts", ".mvn", "gradle"}
PROTECTED_NAMES = {"agents.md", "ai_development_policy.md", "contributing.md", "skill.md",
                   "codeowners", "codeowners.example",
                   ".gitlab-ci.yml", ".gitmodules", ".gitattributes", ".gitignore",
                   "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                   "pom.xml", "gradlew", "gradlew.bat", "mvnw", "mvnw.cmd",
                   "gradle.properties", "settings.gradle", "settings.gradle.kts",
                   "build.gradle", "build.gradle.kts"}
SUPPORTED_SCHEMA_KEYS = {"$schema", "type", "properties", "required", "additionalProperties",
                         "items", "enum", "minimum", "minLength", "minItems", "pattern"}


def fail(message):
    raise ValueError(message)


def load_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("Duplicate JSON key")
            result[key] = value
        return result
    with open(path, encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=unique_pairs,
                         parse_constant=lambda _: fail("Non-finite JSON value"))


def check_schema(schema):
    if not isinstance(schema, dict) or set(schema) - SUPPORTED_SCHEMA_KEYS:
        fail("Unsupported schema keywords")
    kind = schema.get("type")
    if kind not in {"object", "array", "string", "integer", "boolean"}:
        fail("Unsupported schema type")
    if kind == "object":
        if schema.get("additionalProperties") is not False:
            fail("Object schemas must reject additional properties")
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) != set(properties):
            fail("All artifact properties must be required")
        for child in properties.values():
            check_schema(child)
    if kind == "array":
        check_schema(schema["items"])


def validate(value, schema, label="artifact"):
    kind = schema["type"]
    expected = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}[kind]
    if type(value) is not expected:
        fail(label + ": invalid type")
    if "enum" in schema and value not in schema["enum"]:
        fail(label + ": invalid enum")
    if kind == "object":
        if set(value) != set(schema["required"]):
            fail(label + ": missing or unknown fields")
        for key, child in value.items():
            validate(child, schema["properties"][key], label + "." + key)
    elif kind == "array":
        if len(value) < schema.get("minItems", 0):
            fail(label + ": empty array")
        for child in value:
            validate(child, schema["items"], label)
    elif kind == "string":
        if len(value.strip()) < schema.get("minLength", 0):
            fail(label + ": empty string")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            fail(label + ": invalid pattern")
    elif kind == "integer" and value < schema.get("minimum", value):
        fail(label + ": below minimum")


def read_artifact(path, schema_name):
    schema = load_json(SCHEMAS / (schema_name + "-schema.json"))
    check_schema(schema)
    value = load_json(path)
    validate(value, schema, schema_name)
    return value


def safe_path(raw):
    if not isinstance(raw, str) or not raw or "\\" in raw or any(ord(c) < 32 for c in raw):
        fail("Invalid path")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() != raw or any(p in {".", ".."} for p in path.parts):
        fail("Noncanonical path")
    if any(p.lower() in PROTECTED_DIRS for p in path.parts):
        fail("Protected directory cannot be changed")
    if path.name.lower() in PROTECTED_NAMES or path.name.lower().startswith(".env"):
        fail("Protected file cannot be changed")
    return raw


def allowlist(path):
    values = load_json(path)
    if not isinstance(values, list) or not values:
        fail("Allowlist must be a nonempty JSON array of exact paths")
    result = {safe_path(value) for value in values}
    if len(result) != len(values):
        fail("Duplicate allowlist paths")
    return result


def git(repo, *args, data=None, env=None):
    # Inherited Git overrides must not redirect this operation to another index/repository.
    clean_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    clean_env["GIT_LITERAL_PATHSPECS"] = "1"
    if env is not None and "GIT_INDEX_FILE" in env:
        clean_env["GIT_INDEX_FILE"] = env["GIT_INDEX_FILE"]
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                             "-C", str(repo), *args], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=clean_env)
    if result.returncode:
        fail("Git operation failed: " + args[0])
    return result.stdout


def sha(value):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        fail("Expected a full immutable commit ID")
    return value


def changed_paths(repo, baseline):
    # Worktree git diff can execute configured clean filters even with --no-ext-diff.
    # Enumerate paths, compare raw blob IDs, and never ask Git to inspect worktree content.
    before = {}
    for entry in git(repo, "ls-tree", "-r", "-z", baseline).split(b"\0"):
        if entry:
            details, name = entry.split(b"\t", 1)
            mode, kind, oid = details.split(b" ")
            before[name.decode("utf-8")] = (mode, oid)
    listed = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    candidates = set(before) | {p.decode("utf-8") for p in listed.split(b"\0") if p}
    changed = []
    for relative in sorted(candidates):
        if relative == ".agent" or relative.startswith(".agent/"):
            continue
        current = repo / relative
        previous = before.get(relative)
        if previous and previous[0] == b"160000":
            fail("Submodule repositories are not supported by this collector")
        if current.is_symlink():
            data, mode = os.readlink(current).encode(), b"120000"
        elif current.is_file():
            # A replaced parent directory must never cause reads outside the checkout.
            ancestor = current.parent
            while ancestor != repo:
                if ancestor.is_symlink():
                    fail("Symlink parent directory is not accepted")
                ancestor = ancestor.parent
            data = current.read_bytes()
            mode = b"100755" if current.stat().st_mode & 0o111 else b"100644"
        elif not current.exists():
            if previous:
                changed.append(relative)
            continue
        else:
            fail("Only regular files and unchanged symlinks are accepted")
        oid = git(repo, "hash-object", "--stdin", "--no-filters", data=data).strip()
        if previous != (mode, oid):
            changed.append(relative)
    return changed


def patch_paths(patch):
    # Generated patches use --no-renames. Keep the accepted dialect small.
    for line in patch.splitlines():
        if line.startswith((b"rename from ", b"rename to ", b"copy from ", b"copy to ")):
            fail("Rename/copy patches are not accepted; use delete/add")
        match = re.fullmatch(rb"(?:new file mode|deleted file mode|old mode|new mode) ([0-9]{6})", line)
        index = re.fullmatch(rb"index [0-9a-f]+\.\.[0-9a-f]+ ([0-9]{6})", line)
        if (match or index) and (match or index).group(1) not in {b"100644", b"100755"}:
            fail("Symlink/submodule patch modes are not accepted")
    with tempfile.TemporaryDirectory(prefix="codex-patch-check-") as scratch:
        output = git(scratch, "apply", "--numstat", "-z", data=patch)
    paths = []
    for entry in output.split(b"\0"):
        if entry:
            parts = entry.split(b"\t", 2)
            if len(parts) != 3:
                fail("Unsupported patch path format")
            paths.append(safe_path(parts[2].decode("utf-8")))
    if not paths or len(paths) != len(set(paths)):
        fail("Empty or repeated patch paths")
    return set(paths)


def collect(args):
    repo = Path(args.repo).resolve(strict=True)
    baseline = sha(args.baseline)
    if git(repo, "rev-parse", "HEAD").decode().strip() != baseline:
        fail("HEAD changed since the approved baseline")
    if Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve() != repo:
        fail("--repo must name the repository root")
    approved = allowlist(args.allowlist)
    paths = changed_paths(repo, baseline)
    if not paths:
        fail("No changes to collect")
    for relative in paths:
        safe_path(relative)
        if relative not in approved:
            fail("Changed file is outside the approved allowlist")
        current = repo
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.is_symlink():
                fail("Symlinks are not accepted")
        if current.exists() and not current.is_file():
            fail("Only regular files are accepted")
        before = git(repo, "ls-tree", baseline, "--", relative)
        if before and before.split(b" ", 1)[0] not in {b"100644", b"100755"}:
            fail("Symlink or submodule baseline changes are not accepted")
    prefix = Path(args.output_prefix).absolute()
    patch_path, manifest_path = Path(str(prefix) + ".patch"), Path(str(prefix) + ".json")
    for target in (patch_path, manifest_path):
        if target.exists() or target.is_symlink():
            fail("Output already exists; choose a new artifact prefix")
        resolved = target.resolve()
        if resolved.is_relative_to(repo) and not resolved.is_relative_to(repo / ".agent"):
            fail("Artifact output must be outside source or in .agent")
    with tempfile.TemporaryDirectory(prefix="codex-index-") as scratch:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch) / "index"))
        git(repo, "read-tree", baseline, env=env)
        for relative in paths:
            current = repo / relative
            if not current.exists():
                git(repo, "update-index", "--force-remove", "--", relative, env=env)
                continue
            blob = git(repo, "hash-object", "-w", "--stdin", "--no-filters", data=current.read_bytes(), env=env).strip()
            mode = b"100755" if current.stat().st_mode & 0o111 else b"100644"
            entry = mode + b" " + blob + b"\t" + relative.encode() + b"\0"
            git(repo, "update-index", "-z", "--index-info", data=entry, env=env)
        tree = git(repo, "write-tree", env=env).decode().strip()
        patch = git(repo, "diff", "--binary", "--no-renames", "--no-ext-diff", "--no-textconv", baseline, tree, env=env)
    if not patch:
        fail("No final worktree changes")
    actual = git(repo, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", baseline, tree)
    actual_paths = [p.decode() for p in actual.split(b"\0") if p]
    manifest = {"baseline": baseline, "patch_sha256": hashlib.sha256(patch).hexdigest(), "changed_files": actual_paths}
    with patch_path.open("xb") as output:
        output.write(patch)
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print("Collected patch and manifest; original index and worktree were not changed.")


def gate(args):
    baseline = sha(args.baseline)
    manifest = read_artifact(args.manifest, "manifest")
    triage = read_artifact(args.triage, "triage")
    implementation = read_artifact(args.implementation, "implementation")
    review = read_artifact(args.review, "review")
    verification = read_artifact(args.verification, "verification")
    digest = hashlib.sha256(Path(args.patch).read_bytes()).hexdigest()
    if not Path(args.patch).stat().st_size:
        fail("Empty patch")
    if any(item["baseline"] != baseline for item in (manifest, triage, implementation, review, verification)):
        fail("Baseline mismatch")
    if any(item["patch_sha256"] != digest for item in (manifest, review, verification)):
        fail("Patch digest mismatch")
    approved = allowlist(args.allowlist)
    changed = {safe_path(path) for path in manifest["changed_files"]}
    if not changed or len(changed) != len(manifest["changed_files"]) or not changed <= approved:
        fail("Manifest scope rejected")
    if patch_paths(Path(args.patch).read_bytes()) != changed:
        fail("Actual patch paths do not match manifest")
    if set(implementation["changed_files"]) != changed or not changed <= set(triage["affected_files"]):
        fail("Reported scope does not match collected scope")
    if triage["decision"] != "implement" or triage["risk"] != "low" or triage["prohibited_change_detected"]:
        fail("Triage requires human handling")
    if triage["missing_information"] or triage["approval_reasons"]:
        fail("Triage has unresolved requirements")
    if implementation["status"] != "completed":
        fail("Implementation is not completed")
    if implementation["unverified_items"] or implementation["pm_questions"] or implementation["risks"]:
        fail("Implementation requires human review")
    if not implementation["verification_commands"] or not implementation["verification_results"]:
        fail("Implementation verification evidence missing")
    if not implementation["acceptance_results"] or not all(item["met"] for item in implementation["acceptance_results"]):
        fail("Acceptance criteria are not all met")
    if review["decision"] != "pass" or review["blocking_count"] != 0:
        fail("Review has not passed")
    if any(item["severity"] in {"blocking", "high"} for item in review["findings"]):
        fail("Review contains high-risk findings")
    if verification["status"] != "passed" or not verification["commands"] or len(verification["commands"]) != len(verification["exit_codes"]):
        fail("Independent verification incomplete")
    if any(code != 0 for code in verification["exit_codes"]):
        fail("Independent verification failed")
    print("Reference gate passed. Human approval and a separately trusted publisher are still required.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-schemas")
    collector = commands.add_parser("collect")
    for name in ("repo", "baseline", "allowlist", "output-prefix"):
        collector.add_argument("--" + name, required=True)
    validator = commands.add_parser("gate")
    for name in ("baseline", "allowlist", "manifest", "patch", "triage", "implementation", "review", "verification"):
        validator.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        if args.command == "collect":
            collect(args)
        elif args.command == "gate":
            gate(args)
        else:
            for name in ("triage", "implementation", "review", "manifest", "verification"):
                check_schema(load_json(SCHEMAS / (name + "-schema.json")))
            print("Reference schemas valid")
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as error:
        print("REJECTED: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
