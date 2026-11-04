import json
import os
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


if __name__ == "__main__":
    unittest.main()
