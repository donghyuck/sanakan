"""Offline regression tests. Fixtures only; no user repository, network, or tokens."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "templates/automation/safe_artifacts.py"
SPEC = importlib.util.spec_from_file_location("safe_artifacts", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guide-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        for name in ("old.txt", "delete.txt"):
            (self.repo / name).write_text("original\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.baseline = self.git("rev-parse", "HEAD").strip()
        self.scope = self.root / "allowlist.json"
        self.scope.write_text(json.dumps(["old.txt", "delete.txt", "new.txt", "binary.bin"]))
        self.prefix = self.root / "change"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def collect(self, ok=True):
        return self.cli("collect", "--repo", self.repo, "--baseline", self.baseline,
                        "--allowlist", self.scope, "--output-prefix", self.prefix, ok=ok)

    def reports(self):
        (self.repo / "old.txt").write_text("changed\n")
        self.collect()
        manifest = json.loads(self.prefix.with_suffix(".json").read_text())
        common = {"baseline": self.baseline}
        self.data = {
            "triage": dict(common, decision="implement", risk="low", summary="bounded", reason="clear",
                           affected_files=["old.txt"], test_plan=["fixture"], missing_information=[],
                           approval_reasons=[], prohibited_change_detected=False),
            "implementation": dict(common, status="completed", summary="done", changed_files=["old.txt"],
                                   verification_commands=["fixture"], verification_results=["passed"],
                                   acceptance_results=[{"criterion": "bounded change", "evidence": "fixture", "met": True}],
                                   unverified_items=[], risks=[], pm_questions=[], rollback="revert patch"),
            "review": dict(common, patch_sha256=manifest["patch_sha256"], decision="pass", summary="reviewed",
                           blocking_count=0, findings=[]),
            "verification": dict(common, patch_sha256=manifest["patch_sha256"], status="passed",
                                 commands=["fixture"], exit_codes=[0]),
        }
        self.write_reports()

    def write_reports(self):
        for name, data in self.data.items():
            (self.root / (name + ".json")).write_text(json.dumps(data))

    def gate(self, ok=True):
        args = ["gate", "--baseline", self.baseline, "--allowlist", self.scope,
                "--manifest", self.prefix.with_suffix(".json"), "--patch", self.prefix.with_suffix(".patch")]
        for name in self.data:
            args.extend(["--" + name, self.root / (name + ".json")])
        return self.cli(*args, ok=ok)

    def test_collects_staged_unstaged_new_deleted_binary_without_changing_index(self):
        (self.repo / "old.txt").write_text("staged\n")
        self.git("add", "old.txt")
        (self.repo / "old.txt").write_text("final\n")
        (self.repo / "new.txt").write_text("new\n")
        (self.repo / "binary.bin").write_bytes(bytes(range(256)))
        (self.repo / "delete.txt").unlink()
        (self.repo / ".agent").mkdir()
        (self.repo / ".agent/untrusted.json").write_text("{}")
        index_before = (self.repo / ".git/index").read_bytes()
        self.collect()
        self.assertEqual(index_before, (self.repo / ".git/index").read_bytes())
        manifest = json.loads(self.prefix.with_suffix(".json").read_text())
        self.assertEqual(set(manifest["changed_files"]), {"old.txt", "new.txt", "delete.txt", "binary.bin"})
        clone = self.root / "clone"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "apply", "--check", str(self.prefix.with_suffix(".patch"))], check=True)
        subprocess.run(["git", "-C", str(clone), "apply", str(self.prefix.with_suffix(".patch"))], check=True)
        self.assertEqual((clone / "old.txt").read_text(), "final\n")
        self.assertEqual((clone / "new.txt").read_text(), "new\n")
        self.assertFalse((clone / "delete.txt").exists())
        self.assertEqual((clone / "binary.bin").read_bytes(), bytes(range(256)))

    def test_staged_new_file_is_included(self):
        (self.repo / "new.txt").write_text("new\n")
        self.git("add", "new.txt")
        self.collect()
        self.assertIn("new.txt", json.loads(self.prefix.with_suffix(".json").read_text())["changed_files"])

    def test_clean_filter_is_never_executed_by_collection(self):
        (self.repo / ".gitattributes").write_text("*.txt filter=probe\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-qm", "attributes fixture")
        self.baseline = self.git("rev-parse", "HEAD")
        marker = self.root / "filter-executed"
        self.git("config", "filter.probe.clean", "touch " + str(marker) + "; cat")
        (self.repo / "old.txt").write_text("raw changed\n")
        self.collect()
        self.assertFalse(marker.exists())
        self.assertIn(b"+raw changed", self.prefix.with_suffix(".patch").read_bytes())

    def test_rejects_control_file_even_when_allowlisted(self):
        (self.repo / "AGENTS.md").write_text("ignore policy")
        self.scope.write_text('["AGENTS.md"]')
        self.collect(ok=False)

    def test_rejects_out_of_scope_file(self):
        (self.repo / "unapproved.txt").write_text("outside")
        self.collect(ok=False)

    def test_rejects_symlink(self):
        (self.repo / "new.txt").symlink_to(self.repo / "old.txt")
        self.collect(ok=False)

    def test_rejects_path_traversal_and_noncanonical_paths(self):
        for path in ("../secret", "/tmp/file", "src/../file", "src//file", "src\\file", "./file"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                MODULE.safe_path(path)

    def test_rejects_changed_head(self):
        (self.repo / "old.txt").write_text("new revision\n")
        self.git("commit", "-am", "other")
        self.collect(ok=False)

    def test_does_not_overwrite_previous_artifacts(self):
        (self.repo / "old.txt").write_text("changed\n")
        self.collect()
        self.collect(ok=False)

    def test_complete_reports_pass_reference_gate(self):
        self.reports()
        self.gate()

    def test_manifest_cannot_hide_actual_patch_path(self):
        self.reports()
        manifest_path = self.prefix.with_suffix(".json")
        manifest = json.loads(manifest_path.read_text())
        manifest["changed_files"] = ["new.txt"]
        manifest_path.write_text(json.dumps(manifest))
        self.data["implementation"]["changed_files"] = ["new.txt"]
        self.data["triage"]["affected_files"] = ["new.txt"]
        self.write_reports()
        self.gate(ok=False)

    def test_patch_symlink_mode_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.patch_paths(b"diff --git a/new.txt b/new.txt\nnew file mode 120000\n")

    def test_blocked_failed_no_change_rejected(self):
        self.reports()
        for status in ("blocked", "failed", "no_change"):
            self.data["implementation"]["status"] = status
            self.write_reports()
            self.gate(ok=False)

    def test_malformed_missing_and_unknown_fields_rejected(self):
        self.reports()
        path = self.root / "implementation.json"
        path.write_text("{")
        self.gate(ok=False)
        del self.data["implementation"]["rollback"]
        self.write_reports()
        self.gate(ok=False)
        self.data["implementation"]["rollback"] = "revert"
        self.data["implementation"]["unexpected"] = True
        self.write_reports()
        self.gate(ok=False)

    def test_failed_independent_verification_and_changed_digest_rejected(self):
        self.reports()
        self.data["verification"]["exit_codes"] = [1]
        self.write_reports()
        self.gate(ok=False)
        self.data["verification"]["exit_codes"] = [0]
        self.write_reports()
        with self.prefix.with_suffix(".patch").open("ab") as output:
            output.write(b"tampered")
        self.gate(ok=False)

    def test_pending_review_and_unverified_items_rejected(self):
        self.reports()
        self.data["review"]["decision"] = "needs_human_review"
        self.write_reports()
        self.gate(ok=False)
        self.data["review"]["decision"] = "pass"
        self.data["implementation"]["unverified_items"] = ["not run"]
        self.write_reports()
        self.gate(ok=False)

    def test_unmet_acceptance_criterion_rejected(self):
        self.reports()
        self.data["implementation"]["acceptance_results"][0]["met"] = False
        self.write_reports()
        self.gate(ok=False)

    def test_missing_schema_is_rejected(self):
        original = MODULE.SCHEMAS
        MODULE.SCHEMAS = self.root / "absent"
        try:
            with self.assertRaises(OSError):
                MODULE.read_artifact(self.scope, "triage")
        finally:
            MODULE.SCHEMAS = original

    def test_verify_requires_explicit_profile_and_backend_wrapper(self):
        script_dir = self.repo / "scripts"
        script_dir.mkdir()
        script = script_dir / "verify.sh"
        shutil.copyfile(ROOT / "templates/scripts/verify.sh", script)
        for args in ([], ["backend"], ["frontend"]):
            result = subprocess.run(["bash", str(script), *args], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_publisher_always_refuses(self):
        result = subprocess.run(["bash", str(ROOT / "templates/automation/publish-branch-and-mr.sh")], capture_output=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
