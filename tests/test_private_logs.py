"""Regression tests: pipeline logs/metrics must never be written under OUTPUT_DIR."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_pipeline  # noqa: E402
from run_pipeline import PipelineExecutor  # noqa: E402

ROOT = Path(run_pipeline.__file__).resolve().parent


class FakePopen:
    """Stands in for run.sh: emits a token-usage line, exits 0."""
    on_start = None  # optional hook: simulates the container acting while run.sh runs

    def __init__(self, *a, **kw):
        if FakePopen.on_start:
            FakePopen.on_start()
        self.stdout = io.StringIO("tokens: ok\n")
        self.returncode = 0
    def wait(self, timeout=None): return 0
    def poll(self): return 0
    def kill(self): pass
    def terminate(self): pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.data = self.tmp / "data"
        self.sentinel = self.tmp / "outside.txt"
        self.sentinel.write_text("SAFE")
        env = {"DATA_DIR": str(self.data), "OUTPUT_DIR": "output", "MAX_RETRIES": "1"}
        p = mock.patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(sys, "argv", ["run_pipeline.py", "no-confirm"]); p.start(); self.addCleanup(p.stop)
        p = mock.patch("run_pipeline.atexit.register"); p.start(); self.addCleanup(p.stop)
        p = mock.patch("run_pipeline.signal.signal"); p.start(); self.addCleanup(p.stop)

    def make(self):
        return PipelineExecutor(ROOT)

    def assertNoLogsInOutput(self, ex):
        self.assertEqual([p for p in ex.output_dir.rglob("*.log")], [])
        self.assertFalse((ex.output_dir / "execution_metrics.json").exists())


class TestRouting(Base):
    def test_stage2_ignores_preplanted_symlink_and_uses_private_log(self):
        ex = self.make()
        pol = ex.output_dir / "Policy"; pol.mkdir()
        (pol / "stage2_generation.log").symlink_to(self.sentinel)
        with mock.patch("run_pipeline.subprocess.Popen", FakePopen), \
             mock.patch.object(ex, "_verify_stage2_output", return_value=True):
            self.assertEqual(ex._run_single_generation("Policy", 1, 1)[1], True)
        self.assertEqual(self.sentinel.read_text(), "SAFE")
        log = ex._log_path("stage2", 1)
        self.assertTrue(log.exists())
        self.assertTrue(str(log).startswith(str(ex.data_dir / ".logs")))
        self.assertIn("Stage 2", log.read_text())

    def test_stage1_appends_and_identify_use_private_log(self):
        ex = self.make()
        goal = ex.goals_dir / "goal-001.txt"; goal.write_text("x")
        pol = ex.output_dir / "PolA"; pol.mkdir()
        (pol / "requirement.txt").write_text("r"); (pol / "report.md").write_text("r")
        old = ex.goals_dir / "goal-001_stage1.log"
        FakePopen.on_start = lambda: old.symlink_to(self.sentinel)
        self.addCleanup(setattr, FakePopen, "on_start", None)
        seen = {}
        real = ex._identify_policy_directory_for_goal
        def spy(g, log=None):
            seen["log"] = log; return real(g, log)
        with mock.patch("run_pipeline.subprocess.Popen", FakePopen), \
             mock.patch.object(ex, "_identify_policy_directory_for_goal", side_effect=spy):
            self.assertTrue(ex._run_single_requirement(goal, 1, 1)[1])
        self.assertEqual(self.sentinel.read_text(), "SAFE")
        self.assertTrue(old.is_symlink())
        self.assertEqual(seen["log"], ex._log_path("stage1", 1))
        self.assertIn("Post-execution verification", seen["log"].read_text())

    def test_stage0_stage3_stage4_and_retry_unique(self):
        ex = self.make()
        (ex.output_dir / "stage0_extraction.log").symlink_to(self.sentinel)
        (ex.output_dir / "stage3_summary.log").symlink_to(self.sentinel)
        (ex.output_dir / "Pol").mkdir()
        (ex.output_dir / "Pol" / "stage4_fixtures.log").symlink_to(self.sentinel)
        (ex.goals_dir / "goal-001.txt").write_text("g")
        (self.data / "input").mkdir(exist_ok=True)
        (self.data / "input" / "policy_goal.txt").write_text("p")
        with mock.patch("run_pipeline.subprocess.Popen", FakePopen), \
             mock.patch.object(ex, "_verify_stage0_output", return_value=True), \
             mock.patch.object(ex, "_verify_stage3_output", return_value=False), \
             mock.patch.object(ex, "_verify_stage4_output", return_value=True):
            ex.stage0_extraction(); ex.stage3_summary()
            ex._run_single_fixtures("Pol", 1, 1); ex._run_single_fixtures("Pol", 1, 1, retry=True)
        self.assertEqual(self.sentinel.read_text(), "SAFE")
        for name in ("stage0", "stage3", "stage3_retry", "stage4_0001", "stage4_0001_retry"):
            self.assertTrue((ex.log_dir / f"{name}.log").exists(), name)
        self.assertNotEqual(ex._log_path("stage1", 1), ex._log_path("stage1", 2))
        self.assertNotEqual(ex._log_path("stage1", 1), ex._log_path("stage1", 1, True))

    def test_metrics_read_private_logs_and_metrics_file_private(self):
        ex = self.make()
        ex.output_dir.joinpath("stage0_extraction.log").write_text("")
        with mock.patch.object(ex, "_extract_token_usage_from_log",
                               return_value={'total_tokens_in': 5, 'total_tokens_out': 7, 'total_cost': 0,
                                             'cache_read': 0, 'cache_write': 0}) as m:
            for s in ("stage0", "stage3"):
                ex._log_path(s).write_text("x")
            ex._log_path("stage1", 1).write_text("x"); ex._log_path("stage1", 1, True).write_text("x")
            agg = ex._collect_stage_token_metrics("stage1", ex._stage_logs("stage1"))
        self.assertEqual(agg['total_tokens_in'], 5)  # retry log excluded
        self.assertTrue(all(str(ex.log_dir) in c.args[0] for c in m.call_args_list))

    def test_two_runs_get_distinct_private_dirs(self):
        ex = self.make()
        self.assertNotEqual(ex.log_dir, ex._create_private_log_dir())


def tok(i, o, c=0.0, cr=0, cw=0):
    return {'total_tokens_in': i, 'total_tokens_out': o, 'total_cost': c, 'cache_read': cr, 'cache_write': cw}


class TestResumeMetrics(Base):
    """Token metrics: skipped stages come from the checkpoint, executed ones from private logs."""
    ZERO = tok(0, 0)

    def run_pipeline(self, ex, resume, per_log, stage_logs=("stage0", "stage1_0001", "stage2_0001", "stage3")):
        def stage_fn(name):
            def f(*a, **kw):
                ex._log_path(name.split("_")[0], *( [int(name.split("_")[1])] if "_" in name else [])).write_text("x")
                return True
            return f
        def s1(*a, **kw):
            ex._log_path("stage1", 1).write_text("x"); return True, []
        parse = lambda path: per_log.get(Path(path).name, self.ZERO)
        buf = io.StringIO()
        with mock.patch.object(ex, "stage0_extraction", side_effect=lambda: stage_fn("stage0")()), \
             mock.patch.object(ex, "stage1_requirement", side_effect=s1), \
             mock.patch.object(ex, "stage2_generation", side_effect=lambda **k: stage_fn("stage2_0001")()), \
             mock.patch.object(ex, "stage3_summary", side_effect=lambda: stage_fn("stage3")()), \
             mock.patch.object(ex, "_extract_token_usage_from_log", side_effect=parse), \
             contextlib.redirect_stdout(buf):
            self.assertTrue(ex.run_full_pipeline(resume=resume))
        return json.loads((ex.log_dir / "execution_metrics.json").read_text()), buf.getvalue()

    def test_normal_run_counts_logs_and_stores_tokens_in_checkpoint(self):
        ex = self.make()
        logs = {"stage0.log": tok(1, 2, 0.5, 3, 4), "stage1_0001.log": tok(10, 20, 1.0),
                "stage2_0001.log": tok(100, 200, 2.0, 5, 6), "stage3.log": tok(7, 8, 0.25)}
        m, _ = self.run_pipeline(ex, False, logs)
        self.assertEqual(m['stage2_tokens'], 300)
        self.assertEqual(m['total_tokens_in'], 118)
        self.assertEqual(m['total_cost'], 3.75)
        self.assertEqual(m['total_cache_read'], 8)
        cp = json.loads(ex._checkpoint_path().read_text())
        for n, key in enumerate(("stage0.log", "stage1_0001.log", "stage2_0001.log", "stage3.log")):
            self.assertEqual(cp[f"stage{n}_tokens"], logs[key])

    def test_metrics_symlink_in_output_not_followed(self):
        ex = self.make()
        (ex.output_dir / "execution_metrics.json").symlink_to(self.sentinel)
        with mock.patch.object(ex, "_save_checkpoint"):  # checkpointing refuses links; covered in test_private_copy
            m, _ = self.run_pipeline(ex, False, {})
        self.assertEqual(self.sentinel.read_text(), "SAFE")
        self.assertTrue((ex.output_dir / "execution_metrics.json").is_symlink())
        self.assertTrue((ex.log_dir / "execution_metrics.json").exists())

    def test_resume_uses_stored_tokens_for_skipped_and_logs_for_executed(self):
        ex = self.make()
        stored = {"stage0.log": tok(1, 2, 0.5, 3, 4), "stage1_0001.log": tok(10, 20, 1.0, 1, 1),
                  "stage2_0001.log": tok(100, 200, 2.0, 5, 6)}
        cp = {f"stage{n}_done": True for n in range(3)}
        for n, k in enumerate(stored):
            cp[f"stage{n}_tokens"] = stored[k]
            cp[f"stage{n}_snapshot_version"] = 2
        ex._checkpoint_dir().mkdir(parents=True); ex._checkpoint_path().write_text(json.dumps(cp))
        for n in range(3):
            ex._stage_snapshot_dir(n).mkdir()
        poison = {k: tok(9999, 9999, 99.0, 9999, 9999) for k in stored}
        poison["stage3.log"] = tok(7, 8, 0.25, 2, 3)
        with self.assertNoLogs("run_pipeline", level="WARNING"):
            m, out = self.run_pipeline(ex, True, poison)
        self.assertEqual((m['stage0_tokens_in'], m['stage1_tokens_out'], m['stage2_cache_write']), (1, 20, 6))
        self.assertEqual((m['stage3_tokens_in'], m['stage3_cache_read']), (7, 2))
        self.assertEqual(m['total_tokens_in'], 118)
        self.assertEqual(m['total_cost'], 3.75)
        self.assertEqual(m['total_cache_read'], 3 + 1 + 5 + 2)

    def test_legacy_checkpoint_without_tokens_warns_and_reports_zero(self):
        ex = self.make()
        ex._checkpoint_dir().mkdir(parents=True)
        cp = {f"stage{n}_done": True for n in range(4)}
        cp.update({f"stage{n}_snapshot_version": 2 for n in range(4)})
        ex._checkpoint_path().write_text(json.dumps(cp))
        for n in range(4):
            ex._stage_snapshot_dir(n).mkdir()
        with self.assertLogs("run_pipeline", level="WARNING") as cm:
            m, out = self.run_pipeline(ex, True, {})
        self.assertEqual(m['total_tokens'], 0)
        self.assertEqual(len(cm.records), 4)
        for rec in cm.records:
            msg = rec.getMessage()
            self.assertEqual(rec.levelname, "WARNING")
            self.assertIn("no token usage stored in checkpoint", msg)
            self.assertIn("understated", msg)
            self.assertTrue(msg.isascii())
        self.assertNotIn("no token usage stored", out)

    def test_malformed_stored_tokens_treated_as_missing(self):
        ex = self.make()
        got = ex._stored_stage_tokens({"stage0_tokens": {"total_tokens_in": "x"}}, 0)
        self.assertEqual(got, self.ZERO)


class TestRejections(Base):
    def test_output_dir_dot_rejected_before_docker(self):
        with mock.patch.dict(os.environ, {"OUTPUT_DIR": "."}), \
             mock.patch("run_pipeline.subprocess.Popen") as popen:
            with self.assertRaises(ValueError):
                self.make()
            popen.assert_not_called()
        self.assertFalse((self.data / ".logs").exists())

    def test_output_inside_logs_rejected(self):
        with mock.patch.dict(os.environ, {"OUTPUT_DIR": ".logs/x"}):
            with self.assertRaises(ValueError):
                self.make()

    def test_absolute_output_dir_rejected(self):
        for val in ("/.logs", str(self.tmp / "abs")):
            with mock.patch.dict(os.environ, {"OUTPUT_DIR": val}):
                with self.assertRaises(ValueError):
                    self.make()

    def test_local_skills_dir_overlap_rejected_both_directions(self):
        self.data.mkdir()
        (self.data / ".logs").mkdir(mode=0o700)
        for val in (str(self.data / ".logs"), str(self.data / ".logs" / "run-x"), str(self.data), str(self.tmp)):
            os.makedirs(val, exist_ok=True)
            with mock.patch.dict(os.environ, {"LOCAL_SKILLS_DIR": val}):
                with self.assertRaises(ValueError, msg=val):
                    self.make()

    def test_separate_local_skills_dir_allowed(self):
        skills = self.tmp / "skills"; skills.mkdir()
        with mock.patch.dict(os.environ, {"LOCAL_SKILLS_DIR": str(skills)}):
            self.make()

    def test_shell_guard_rejects_overlap(self):
        common = ROOT / "common.sh"
        def run(path):
            return subprocess.run(
                ["bash", "-c", f'source "{common}"; assert_not_overlapping_private_logs "$1" x "$2"', "_",
                 str(self.data), str(path)], capture_output=True, text=True)
        (self.data / ".logs").mkdir(parents=True)
        self.assertNotEqual(run(self.data).returncode, 0)
        self.assertNotEqual(run(self.data / ".logs").returncode, 0)
        self.assertEqual(run(self.data / "output").returncode, 0)

    def test_case_alias_rejected(self):
        self.assertTrue(run_pipeline.paths_overlap("/d/.LOGS", "/d/.logs"))
        self.assertTrue(run_pipeline.paths_overlap("/D/.Logs/x", "/d/.logs"))
        self.assertTrue(run_pipeline.paths_overlap("/d", "/d/.logs"))
        self.assertFalse(run_pipeline.paths_overlap("/d/.logs2", "/d/.logs"))  # boundary, not prefix
        with mock.patch.dict(os.environ, {"OUTPUT_DIR": ".LOGS"}):
            with self.assertRaises(ValueError):
                self.make()
        (self.data / ".logs").mkdir(parents=True, exist_ok=True, mode=0o700)
        alias = self.data / ".LOGS"
        alias.mkdir(exist_ok=True)
        with mock.patch.dict(os.environ, {"LOCAL_SKILLS_DIR": str(alias)}):
            with self.assertRaises(ValueError):
                self.make()
        r = subprocess.run(["bash", "-c", f'source "{ROOT / "common.sh"}"; assert_not_overlapping_private_logs "$1" x "$2"',
                            "_", str(self.data), str(self.data / ".LOGS")], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_nested_output_dir_allowed(self):
        with mock.patch.dict(os.environ, {"OUTPUT_DIR": "a/b"}):
            self.make()

    def test_logs_symlink_rejected_and_not_followed(self):
        self.data.mkdir()
        target = self.tmp / "elsewhere"; target.mkdir()
        (self.data / ".logs").symlink_to(target)
        with self.assertRaises(ValueError):
            self.make()
        self.assertEqual(list(target.iterdir()), [])

    def _assert_unsafe_root(self, setup):
        """Fresh DATA_DIR per case so only the .logs diagnostic can be raised."""
        data = Path(tempfile.mkdtemp()).resolve() / "data"
        data.mkdir()
        setup(data / ".logs")
        with mock.patch.dict(os.environ, {"DATA_DIR": str(data)}):
            with self.assertRaisesRegex(ValueError, "Unsafe log root"):
                self.make()

    def test_logs_unsafe_permissions_and_non_dir_rejected(self):
        self._assert_unsafe_root(lambda l: (l.mkdir(), l.chmod(0o777)))
        self._assert_unsafe_root(lambda l: (l.mkdir(), l.chmod(0o770)))
        self._assert_unsafe_root(lambda l: l.write_text("file"))

    def test_dangling_logs_symlink_fails_closed(self):
        self._assert_unsafe_root(lambda l: l.symlink_to(self.tmp / "missing"))
        self.assertFalse((self.tmp / "missing").exists())


class TestResultCheck(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "skills" / "tfpac-run" / "scripts"))
        import result_check
        self.rc = result_check
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.data = self.tmp / "data"
        self.logs = self.data / ".logs"
        self.logs.mkdir(parents=True, mode=0o700)
        self.out = self.data / "output"; self.out.mkdir()

    def run_dir(self, name, **files):
        d = self.logs / name; d.mkdir(mode=0o700)
        for f, t in files.items():
            (d / f.replace("__", ".")).write_text(t)
        return d

    def test_reads_private_logs_and_errors_ignores_old_output_logs(self):
        (self.out / "stage0_extraction.log").write_text("Traceback old")  # legacy location
        d = self.run_dir("run-a", stage0__log="ok", stage1_0001__log="ok", stage1_0001_retry__log="ok",
                         stage2_0001__log="Traceback boom", stage3__log="ok", stage4_0001__log="ok")
        log_dir, err = self.rc.find_log_dir(self.data)
        self.assertEqual((log_dir, err), (d, None))
        s = self.rc.summarize_output(self.out, log_dir)
        self.assertTrue(s["stage0_log_exists"] and s["stage3_log_exists"])
        self.assertEqual(len(s["goal_stage1_logs"]), 2)
        self.assertEqual(len(s["policy_stage4_logs"]), 1)
        self.assertEqual([Path(h["file"]).name for h in s["error_hits"]], ["stage2_0001.log"])

    def test_missing_logs_fail_loud(self):
        self.assertIsNotNone(self.rc.find_log_dir(self.data)[1])  # no run dirs
        s = self.rc.summarize_output(self.out, None, "x")
        self.assertFalse(s["stage0_log_exists"])

    def test_symlinked_root_run_and_file_not_followed(self):
        real = self.tmp / "real"; real.mkdir(mode=0o700)
        (self.logs / "run-link").symlink_to(real)
        self.assertIsNotNone(self.rc.find_log_dir(self.data)[1])
        d = self.run_dir("run-b")
        (d / "stage0.log").symlink_to(self.tmp / "data")  # not a regular file
        self.assertEqual(self.rc.stage_logs(d, "stage0.log"), [])
        import shutil
        shutil.rmtree(self.logs)
        self.logs.symlink_to(real)
        self.assertIsNotNone(self.rc.find_log_dir(self.data)[1])

    def test_unsafe_perms_and_explicit_log_dir(self):
        d = self.run_dir("run-c", stage0__log="ok"); d.chmod(0o777)
        self.assertIsNotNone(self.rc.find_log_dir(self.data)[1])
        self.assertIsNotNone(self.rc.find_log_dir(self.data, d)[1])
        d.chmod(0o700)
        self.assertEqual(self.rc.find_log_dir(self.data, d), (d, None))

    def _cli(self, *args):
        (self.tmp / ".env").write_text(f"DATA_DIR={self.data}\n")
        return subprocess.run([sys.executable, str(ROOT / "skills/tfpac-run/scripts/result_check.py"), *args],
                              capture_output=True, text=True, cwd=self.tmp)

    def test_default_skips_newest_empty_run(self):
        old = self.run_dir("run-old", stage0__log="ok")
        os.utime(old, (1, 1))
        self.run_dir("run-new")  # newest but empty
        self.assertEqual(self.rc.find_log_dir(self.data), (old, None))
        r = self._cli()
        self.assertEqual(r.returncode, 0)
        self.assertIn("run-old", r.stdout)

    def test_only_empty_runs_fail_default_and_explicit(self):
        d = self.run_dir("run-empty")
        (d / "stage0.log").symlink_to(self.tmp)  # symlink is not a stage log
        r = self._cli()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no valid run-*", r.stdout)
        r = self._cli("--log-dir", str(d))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no regular stage*.log", r.stdout)

    def test_explicit_symlink_log_dir_rejected(self):
        real = self.run_dir("run-real", stage0__log="ok")
        link = self.tmp / "link"; link.symlink_to(real)
        (self.tmp / ".env").write_text(f"DATA_DIR={self.data}\n")
        r = subprocess.run([sys.executable, str(ROOT / "skills/tfpac-run/scripts/result_check.py"),
                            "--log-dir", str(link)], capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--log-dir must be a run-* directory directly under", r.stdout)
        self.assertIsNotNone(self.rc.find_log_dir(self.data, Path(os.path.abspath(link)))[1])
        alias = self.logs / "run-alias"; alias.symlink_to(real)  # run-* name but a symlink
        self.assertIn("not a real directory", self.rc.find_log_dir(self.data, alias)[1])

    def test_explicit_must_be_real_run_under_configured_root(self):
        good = self.run_dir("run-good", stage0__log="ok")
        self.assertEqual(self.rc.find_log_dir(self.data, good), (good, None))
        outside = self.tmp / "outside"; outside.mkdir(mode=0o700)
        copied = outside / "run-copy"; copied.mkdir(mode=0o700); (copied / "stage0.log").write_text("ok")
        alias = self.tmp / "alias"; alias.symlink_to(self.logs)
        nested = self.run_dir("run-n"); (nested / "run-inner").mkdir(mode=0o700)
        (nested / "run-inner" / "stage0.log").write_text("ok")
        bad_name = self.logs / "other"; bad_name.mkdir(mode=0o700); (bad_name / "stage0.log").write_text("ok")
        for bad in (copied, alias / "run-good", nested / "run-inner", bad_name):
            self.assertIn("directly under", self.rc.find_log_dir(self.data, bad)[1], str(bad))
        r = self._cli("--log-dir", str(copied))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("run-copy/stage0", r.stdout)

    def test_symlinked_logs_root_to_forged_run_fails_default_and_explicit(self):
        import shutil
        shutil.rmtree(self.logs)
        forged = self.out / "forged"; forged.mkdir(mode=0o700)
        run = forged / "run-x"; run.mkdir(mode=0o700); (run / "stage0.log").write_text("ok")
        self.logs.symlink_to(forged)
        self.assertIn("no safe private log root", self.rc.find_log_dir(self.data)[1])
        self.assertIn("no safe private log root", self.rc.find_log_dir(self.data, self.logs / "run-x")[1])
        for args in ((), ("--log-dir", str(self.logs / "run-x"))):
            r = self._cli(*args)
            self.assertEqual(r.returncode, 1)
            self.assertIn("no safe private log root", r.stdout)


if __name__ == "__main__":
    unittest.main()
