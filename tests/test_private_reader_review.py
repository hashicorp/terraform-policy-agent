import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "skills/tfpac-run/scripts/result_check.py"
READERS = [READER]  # policy-agent ships only the result checker (no precheck reader)


def run_reader(reader, repo, extra=(), **env):
    """Run a reader as a subprocess with inherited DATA_DIR/OUTPUT_DIR removed, then env applied."""
    e = {k: v for k, v in os.environ.items() if k not in ("DATA_DIR", "OUTPUT_DIR")}
    e.update(env)
    return subprocess.run([sys.executable, str(reader), *extra], cwd=repo, env=e,
                          capture_output=True, text=True)


def mkrun(data, name="run-1"):
    root = data / ".logs"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    run = root / name
    run.mkdir()
    os.chmod(run, 0o700)
    (run / "stage0.log").write_text("ok")
    return run


class QuotedEnvPaths(unittest.TestCase):
    def check(self, data_val, out_val):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t)
            data = repo / "custom path"
            run = mkrun(data)
            (data / "my out").mkdir()
            (data / "my out" / "summary.md").write_text("x")
            decoy = repo / "data"  # default dir must not win
            mkrun(decoy, "run-decoy")
            (repo / ".env").write_text(f"DATA_DIR={data_val}\nOUTPUT_DIR={out_val}\n")
            for extra in ([], ["--log-dir", str(run)]):
                r = run_reader(READER, repo, extra)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(Path(out["log_dir"]).resolve(), run.resolve())
                self.assertTrue(out["summary_md_exists"])
                self.assertTrue(out["stage0_log_exists"])

    def test_single_quotes(self):
        self.check("'./custom path'", "'my out'")

    def test_double_quotes(self):
        self.check('"./custom path"', '"my out"')


class ExportedEnvPriority(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.decoy = self.repo / "data"
        mkrun(self.decoy, "run-decoy")
        (self.repo / ".env").write_text("DATA_DIR='./data'\nOUTPUT_DIR=env out\n")
        (self.decoy / "env out").mkdir()
        self.data = Path(self.tmp.name) / "exp data"  # absolute, with a space
        self.run = mkrun(self.data)
        (self.data / "exp out").mkdir()
        (self.data / "exp out" / "summary.json").write_text("{}")
        (self.data / "exp out" / "PolicyX").mkdir()

    def test_exported_wins(self):
        for reader in READERS:
            for extra in ([], ["--log-dir", str(self.run)]):
                r = run_reader(reader, self.repo, extra, DATA_DIR=str(self.data), OUTPUT_DIR="exp out")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(Path(out["log_dir"]).resolve(), self.run.resolve())
                self.assertTrue(out["output_dir_exists"])
                self.assertTrue(out["summary_json_exists"])
                self.assertEqual(out["policy_dirs"], ["PolicyX"])

    def test_relative_export(self):
        rel = os.path.relpath(self.data, self.repo)
        for reader in READERS:
            r = run_reader(reader, self.repo, DATA_DIR=rel, OUTPUT_DIR="exp out")
            out = json.loads(r.stdout)
            self.assertEqual(Path(out["log_dir"]).resolve(), self.run.resolve())
            self.assertEqual(out["policy_dirs"], ["PolicyX"])

    def test_empty_export_falls_back_to_env_file(self):
        for reader in READERS:
            r = run_reader(reader, self.repo, DATA_DIR="", OUTPUT_DIR="")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(Path(out["log_dir"]).resolve(), (self.decoy / ".logs/run-decoy").resolve())
            self.assertTrue(out["output_dir_exists"])  # .env OUTPUT_DIR "env out"
            self.assertFalse(out["summary_json_exists"])

    def test_log_dir_outside_effective_root_rejected(self):
        for reader in READERS:
            # decoy run is not under the exported DATA_DIR/.logs
            r = run_reader(reader, self.repo, ["--log-dir", str(self.decoy / ".logs/run-decoy")],
                           DATA_DIR=str(self.data), OUTPUT_DIR="exp out")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertIsNone(out["log_dir"])
            self.assertIn("--log-dir must be a run-*", out["log_error"])


sys.path.insert(0, str(READER.parent))
import result_check  # noqa: E402
from unittest import mock  # noqa: E402


class StatRace(unittest.TestCase):
    """lstat of a log/run entry may fail after discovery (benign cleanup); skip it, keep validation."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.data = Path(self._t.name).resolve() / "data"
        self.run = mkrun(self.data)

    def hook(self, target, action, nth=1):
        """Wrap os.lstat: the nth lstat of exactly `target` runs `action` then the real call."""
        real, seen = os.lstat, []

        def lstat(p, *a, **k):
            if str(p) == str(target):
                seen.append(1)
                if len(seen) == nth:
                    action(p)
            return real(p, *a, **k)
        return mock.patch.object(result_check.os, "lstat", lstat)

    @staticmethod
    def denied(p):
        raise PermissionError(13, "injected", str(p))

    def test_stage_logs_skips_deleted_and_inaccessible_but_keeps_valid(self):
        good = self.run / "stage1_0001.log"; good.write_text("ok")
        bad = self.run / "stage1_0002.log"; bad.write_text("x")
        for action in (os.unlink, self.denied):
            bad.write_text("x")
            with self.subTest(action=getattr(action, "__name__", "unlink")), self.hook(bad, action):
                self.assertEqual(result_check.stage_logs(self.run, "stage1_*.log"), [str(good)])

    def test_append_control_still_listed(self):
        log = self.run / "stage0.log"
        with self.hook(log, lambda p: p.write_text(p.read_text() + "more\n")):
            self.assertEqual(result_check.stage_logs(self.run, "stage0.log"), [str(log)])

    def test_default_and_explicit_skip_bad_file_with_valid_remaining(self):
        (self.run / "stage1_0001.log").write_text("ok")
        for action in (os.unlink, self.denied):
            (self.run / "stage0.log").write_text("x")
            for explicit in (None, self.run):
                with self.subTest(action=getattr(action, "__name__", "unlink"), explicit=explicit), \
                        self.hook(self.run / "stage0.log", action):
                    self.assertEqual(result_check.find_log_dir(self.data, explicit), (self.run, None))
                (self.run / "stage0.log").write_text("x")

    def test_all_bad_logs_give_clear_failure_not_exception(self):
        only = mkrun(Path(self._t.name).resolve() / "data2")
        data2 = only.parent.parent
        for action in (os.unlink, self.denied):
            (only / "stage0.log").write_text("x")
            for explicit in (None, only):
                with self.subTest(action=getattr(action, "__name__", "unlink"), explicit=explicit), \
                        self.hook(only / "stage0.log", action):
                    run, err = result_check.find_log_dir(data2, explicit)
                self.assertIsNone(run)
                self.assertTrue(err and "stage" in err, err)

    def test_default_skips_run_vanishing_before_mtime_capture(self):
        newer = mkrun(self.data, "run-2")
        os.utime(self.run, (1, 1))  # run-1 would lose to run-2 anyway; make run-2 the vanishing one
        os.utime(newer, (2_000_000_000, 2_000_000_000))
        with self.hook(newer, shutil.rmtree, nth=2):  # 1st lstat is is_safe_dir, 2nd the mtime capture
            self.assertEqual(result_check.find_log_dir(self.data), (self.run, None))

    def test_default_all_runs_vanishing_returns_error(self):
        with self.hook(self.run, shutil.rmtree, nth=2):
            run, err = result_check.find_log_dir(self.data)
        self.assertIsNone(run)
        self.assertIn("no valid run-*", err)

    def test_main_nonzero_with_clear_json_when_only_log_vanishes(self):
        (self.data / "output").mkdir()
        log = self.run / "stage0.log"
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"DATA_DIR": str(self.data), "OUTPUT_DIR": "output"}), \
                mock.patch.object(sys, "argv", ["rc"]), self.hook(log, os.unlink), \
                mock.patch.object(sys, "stdout", out):
            rc = result_check.main()
        self.assertEqual(rc, 1)
        self.assertIsNotNone(json.loads(out.getvalue())["log_error"])


if __name__ == "__main__":
    unittest.main()
