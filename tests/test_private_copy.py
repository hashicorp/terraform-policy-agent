"""Backup/checkpoint copies never follow symlinks; timeout cleanup gates checkpointing.

Engine commands are mocked (subprocess.run); no real Docker/Podman is exercised.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_private_logs import Base, FakePopen, ROOT, run_pipeline  # noqa: E402

COMMON = ROOT / "common.sh"
SECRET = "SAFE"  # sentinel content that must never appear in a backup or snapshot


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def cp(cmd, rc=0, out=b""):
    return subprocess.CompletedProcess(cmd, rc, out, b"")


def boom(exc):
    def f(cmd):
        raise exc
    return f


class CopyBase(Base):
    def setUp(self):
        super().setUp()
        self.ex = self.make()
        (self.ex.output_dir / "ok.txt").write_text("ok")

    def assertSentinelIntact(self):
        self.assertEqual(self.sentinel.read_text(), SECRET)

    def assertNoSecretCopy(self, root):
        for p in Path(root).rglob("*"):
            self.assertFalse(p.is_file() and not p.is_symlink() and p.read_text() == SECRET, p)


class SaveCheckpoint(CopyBase):
    def test_file_and_dir_symlinks_refused(self):
        outside = self.tmp / "outdir"; outside.mkdir(); (outside / "s.txt").write_text(SECRET)
        for name, target in (("f", self.sentinel), ("d", outside)):
            link = self.ex.output_dir / name
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                self.ex._save_checkpoint(1)
            link.unlink()
        self.assertSentinelIntact()
        self.assertFalse(self.ex._checkpoint_path().exists())
        self.assertFalse(self.ex._stage_snapshot_dir(1).exists())
        self.assertNoSecretCopy(self.ex._checkpoint_dir())

    def test_failed_copy_keeps_previous_snapshot_and_json(self):
        self.ex._save_checkpoint(1)
        before_json = self.ex._checkpoint_path().read_bytes()
        before_snap = tree_bytes(self.ex._stage_snapshot_dir(1))
        (self.ex.output_dir / "ok.txt").write_text("changed")
        with mock.patch.object(run_pipeline.shutil, "copytree", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                self.ex._save_checkpoint(1)
        self.assertEqual(self.ex._checkpoint_path().read_bytes(), before_json)
        self.assertEqual(tree_bytes(self.ex._stage_snapshot_dir(1)), before_snap)
        self.assertEqual([p.name for p in self.ex._checkpoint_dir().iterdir() if p.name.startswith(".stage")], [])

    def test_fifo_refused_and_stage_not_marked(self):
        os.mkfifo(self.ex.output_dir / "pipe")
        with self.assertRaises(ValueError):
            self.ex._save_checkpoint(2)
        self.assertNotIn("stage2_done", self.ex._load_checkpoint())

    def test_terraform_dir_omitted_even_with_inner_link(self):
        tf = self.ex.output_dir / "P" / ".terraform"
        tf.mkdir(parents=True)
        (tf / "link").symlink_to(self.sentinel)
        self.ex._save_checkpoint(1)
        self.assertFalse(list(self.ex._stage_snapshot_dir(1).rglob(".terraform")))
        self.assertEqual(self.ex._load_checkpoint()["stage1_snapshot_version"], 2)

    def test_checkpoint_root_symlink_refused(self):
        (self.data / ".checkpoint").symlink_to(self.tmp)
        with self.assertRaises(RuntimeError):
            self.ex._save_checkpoint(1)
        self.assertEqual(list(self.tmp.glob("stage*")), [])


class RestoreCheckpoint(CopyBase):
    def test_roundtrip(self):
        self.ex._save_checkpoint(1)
        (self.ex.output_dir / "ok.txt").write_text("changed")
        self.ex._restore_checkpoint(1)
        self.assertEqual((self.ex.output_dir / "ok.txt").read_text(), "ok")

    def test_legacy_snapshot_rejected_output_untouched(self):
        self.ex._save_checkpoint(1)
        cp_ = self.ex._load_checkpoint(); del cp_["stage1_snapshot_version"]
        self.ex._checkpoint_path().write_text(json.dumps(cp_))
        with self.assertRaisesRegex(RuntimeError, "fresh run"):
            self.ex._restore_checkpoint(1)
        self.assertTrue((self.ex.output_dir / "ok.txt").exists())

    def test_missing_snapshot_fails_loud(self):
        self.ex._save_checkpoint(1)
        shutil.rmtree(self.ex._stage_snapshot_dir(1))
        with self.assertRaises(RuntimeError):
            self.ex._restore_checkpoint(1)
        self.assertTrue((self.ex.output_dir / "ok.txt").exists())

    def test_symlink_in_snapshot_validated_before_wipe(self):
        self.ex._save_checkpoint(1)
        (self.ex._stage_snapshot_dir(1) / "evil").symlink_to(self.sentinel)
        with self.assertRaises(ValueError):
            self.ex._restore_checkpoint(1)
        self.assertEqual((self.ex.output_dir / "ok.txt").read_text(), "ok")
        self.assertSentinelIntact()

    def test_output_root_symlink_refused_target_kept(self):
        self.ex._save_checkpoint(1)
        target = self.tmp / "target"; target.mkdir(); (target / "keep").write_text("k")
        shutil.rmtree(self.ex.output_dir)
        self.ex.output_dir.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.ex._restore_checkpoint(1)
        self.assertEqual((target / "keep").read_text(), "k")

    def test_snapshot_root_symlink_refused(self):
        self.ex._save_checkpoint(1)
        shutil.rmtree(self.ex._stage_snapshot_dir(1))
        self.ex._stage_snapshot_dir(1).symlink_to(self.tmp)
        with self.assertRaises(RuntimeError):
            self.ex._restore_checkpoint(1)
        self.assertTrue((self.ex.output_dir / "ok.txt").exists())


class InteractiveBackup(Base):
    def make_interactive(self, choice="1"):
        with mock.patch.object(sys, "argv", ["run_pipeline.py"]), \
             mock.patch("builtins.input", return_value=choice), mock.patch("builtins.print"):
            return self.make()

    def test_symlinks_refused_no_dereference(self):
        out = self.data / "output"; out.mkdir(parents=True)
        (out / "x.txt").write_text("x")
        outside = self.tmp / "d"; outside.mkdir(); (outside / "s").write_text(SECRET)
        for target in (self.sentinel, outside):
            (out / "link").symlink_to(target)
            with self.assertRaises(ValueError):
                self.make_interactive()
            (out / "link").unlink()
        self.assertEqual(self.sentinel.read_text(), SECRET)
        self.assertFalse(list((self.data / ".backup").glob("*/*")))

    def test_normal_backup(self):
        out = self.data / "output"; out.mkdir(parents=True)
        (out / "x.txt").write_text("x")
        self.make_interactive()
        self.assertEqual([p.read_text() for p in (self.data / ".backup").glob("output_*/x.txt")], ["x"])

    def test_clean_refuses_symlinked_output(self):
        self.data.mkdir()
        target = self.tmp / "t"; target.mkdir(); (target / "keep").write_text("k")
        (self.data / "output").symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.make_interactive("2")
        self.assertEqual((target / "keep").read_text(), "k")


class PrivateRootOverlap(Base):
    def env(self, **kw):
        return mock.patch.dict(os.environ, kw)

    def test_checkpoint_backup_overlaps_rejected(self):
        self.data.mkdir()
        for out in (".checkpoint", ".BACKUP", ".checkpoint/x", ".backup/a/b"):
            with self.env(OUTPUT_DIR=out), self.assertRaises(ValueError, msg=out):
                self.make()
        for name in (".checkpoint", ".backup", ".Backup"):
            for sub in ("", "/sub"):
                d = self.data / (name + sub); d.mkdir(parents=True, exist_ok=True)
                with self.env(LOCAL_SKILLS_DIR=str(d)), self.assertRaises(ValueError, msg=str(d)):
                    self.make()

    def test_overlap_checked_before_interactive_backup(self):
        out = self.data / ".backup"; out.mkdir(parents=True); (out / "x").write_text("x")
        with self.env(OUTPUT_DIR=".backup"), mock.patch.object(sys, "argv", ["run_pipeline.py"]), \
             mock.patch("builtins.input", side_effect=AssertionError("prompted")), \
             self.assertRaises(ValueError):
            self.make()

    def test_symlinked_private_roots_rejected(self):
        self.data.mkdir()
        for name in (".backup", ".checkpoint"):
            (self.data / name).symlink_to(self.tmp)
            with self.assertRaises(ValueError):
                self.make()
            (self.data / name).unlink()

    def test_shell_guard(self):
        self.data.mkdir()
        def run(p):
            return subprocess.run(["bash", "-c", f'source "{COMMON}"; assert_not_overlapping_private_logs "$1" x "$2"',
                                   "_", str(self.data), str(p)], capture_output=True).returncode
        for p in (".checkpoint", ".BACKUP", ".checkpoint/x", ".backup/a"):
            self.assertNotEqual(run(self.data / p), 0, p)
        self.assertEqual(run(self.data / "output"), 0)
        self.assertEqual(run(self.data / ".backup2"), 0)


class NonzeroPopen(FakePopen):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.returncode = 3


class TimeoutCleanup(CopyBase):
    def setUp(self):
        super().setUp()
        self.spawned = 0
        def started():
            self.spawned += 1
        FakePopen.on_start = started
        self.addCleanup(setattr, FakePopen, "on_start", None)
        self.addCleanup(self.ex.running_containers.clear)  # keep atexit cleanup quiet

    def fake(self, rm, ps=None):
        self.calls = []
        def fake_run(cmd, **kw):
            self.calls.append(cmd)
            if cmd[1] == "rm":
                return rm(cmd)
            if cmd[1] == "ps":
                self.assertIsNotNone(ps, "unexpected ps call")
                return ps(cmd)
            return cp(cmd)
        return mock.patch.object(run_pipeline.subprocess, "run", fake_run)

    def run_job(self, rm, ps=None, popen=FakePopen, timeout=600, name="Stage X"):
        with mock.patch.object(run_pipeline.subprocess, "Popen", popen), \
             self.fake(rm, ps), mock.patch("builtins.print"):
            return self.ex._run_docker_command("s", "p", name, timeout_seconds=timeout)

    def test_confirmed_removal_allows_checkpoint(self):
        self.assertFalse(self.run_job(cp, timeout=0))
        self.assertTrue(any(c[1:3] == ["rm", "-f"] for c in self.calls))
        self.assertFalse(any(c[1] == "ps" for c in self.calls))
        self.assertFalse(self.ex._unsafe_cleanup)
        self.assertEqual(self.ex.running_containers, set())
        self.ex._save_checkpoint(1)

    def test_rm_failed_but_no_live_container_permits_retry(self):
        # e.g. podman auto-rm already removed it: rm rc 1, ps succeeds and is empty
        self.assertFalse(self.run_job(lambda c: cp(c, 1), lambda c: cp(c), timeout=0))
        ps = next(c for c in self.calls if c[1] == "ps")
        self.assertEqual(ps[-1], f"name=^/?{run_pipeline.re.escape(self.ex.container_prefix)}$")
        self.assertFalse(self.ex._unsafe_cleanup)
        self.assertEqual(self.ex.running_containers, set())
        self.ex._save_checkpoint(1)
        self.assertTrue(self.run_job(cp, name="Stage Y"))  # a later job still starts

    def test_unconfirmed_removal_blocks_copying(self):
        self.ex._save_checkpoint(1)
        before = self.ex._checkpoint_path().read_bytes()
        cases = {
            "rm1 ps live": (lambda c: cp(c, 1), lambda c: cp(c, 0, b"abc\n")),
            "rm1 ps rc125": (lambda c: cp(c, 1), lambda c: cp(c, 125)),
            "rm1 ps timeout": (lambda c: cp(c, 1), boom(subprocess.TimeoutExpired("ps", 30))),
            "rm1 ps engine gone": (lambda c: cp(c, 1), boom(FileNotFoundError("engine"))),
            "rm timeout": (boom(subprocess.TimeoutExpired("rm", 30)), None),
            "rm engine gone": (boom(FileNotFoundError("engine")), None),
        }
        for label, (rm, ps) in cases.items():
            self.ex._unsafe_cleanup = False
            with self.subTest(label), self.assertLogs("run_pipeline", "ERROR") as cm:
                self.assertFalse(self.run_job(rm, ps, timeout=0))
                self.assertTrue(self.ex._unsafe_cleanup)
                self.assertTrue(self.ex.running_containers)
                self.assertTrue(any("could not confirm removal" in m for m in cm.output))
                with self.assertRaises(RuntimeError):
                    self.ex._save_checkpoint(2)
                with self.assertRaises(RuntimeError):
                    self.ex._restore_checkpoint(1)
                spawned = self.spawned
                self.assertFalse(self.run_job(cp, name="Stage Y"))
                self.assertEqual(self.spawned, spawned)  # no new container started
                self.assertTrue(any("not started" in m for m in cm.output))
        self.assertEqual(self.ex._checkpoint_path().read_bytes(), before)

    def test_unsafe_flag_is_sticky(self):
        self.ex._unsafe_cleanup = True
        self.ex.running_containers.add("x")
        with self.fake(cp):
            self.assertTrue(self.ex._force_remove_container("x"))
        self.assertTrue(self.ex._unsafe_cleanup)

    def test_ps_filter_is_anchored_and_escaped(self):
        with self.fake(lambda c: cp(c, 1), lambda c: cp(c)):
            self.ex._force_remove_container("a.b-1")
        self.assertEqual(self.calls[-1][-1], "name=^/?a\\.b\\-1$")

    def test_abnormal_error_after_start_confirms_removal(self):
        with mock.patch.object(run_pipeline.subprocess, "Popen", FakePopen), \
             self.fake(lambda c: cp(c, 1)), \
             mock.patch.object(run_pipeline.time, "time", side_effect=[0.0, RuntimeError("x")]), \
             mock.patch("builtins.print"), self.assertLogs("run_pipeline", "ERROR"):
            self.assertFalse(self.ex._run_docker_command("s", "p", "Stage X", timeout_seconds=600))
        self.assertTrue(self.ex._unsafe_cleanup)

    def test_kill_or_stdout_close_failure_still_attempts_removal(self):
        for attr in ("kill", "close"):
            with self.subTest(attr):
                self.ex._unsafe_cleanup = False
                self.ex.running_containers.add("c1")
                proc = mock.Mock()
                proc.poll.return_value = None
                if attr == "kill":
                    proc.kill.side_effect = OSError("kill")
                else:
                    proc.stdout.close.side_effect = OSError("close")
                with self.fake(lambda c: cp(c, 1), lambda c: cp(c, 0, b"live")), \
                     self.assertLogs("run_pipeline", "ERROR"), self.assertRaises(OSError):
                    self.ex._abort_run(proc, "c1")
                self.assertTrue(any(c[1] == "rm" for c in self.calls))
                self.assertTrue(self.ex._unsafe_cleanup)

    def test_abort_without_process_just_untracks(self):
        self.ex.running_containers.add("c1")
        with self.fake(boom(AssertionError("no engine call expected"))):
            self.ex._abort_run(None, "c1")
        self.assertFalse(self.ex._unsafe_cleanup)
        self.assertNotIn("c1", self.ex.running_containers)

    def test_nonzero_exit_confirms_removal(self):
        self.assertFalse(self.run_job(cp, popen=NonzeroPopen))
        self.assertTrue(any(c[1] == "rm" for c in self.calls))
        self.assertFalse(self.ex._unsafe_cleanup)
        self.assertEqual(self.ex.running_containers, set())

    def test_nonzero_exit_no_live_container_is_safe_retry(self):
        self.assertFalse(self.run_job(lambda c: cp(c, 1), lambda c: cp(c), popen=NonzeroPopen))
        self.assertFalse(self.ex._unsafe_cleanup)
        self.assertEqual(self.ex.running_containers, set())

    def test_nonzero_exit_live_or_unavailable_blocks(self):
        for ps in (lambda c: cp(c, 0, b"abc"), boom(FileNotFoundError("engine"))):
            self.ex._unsafe_cleanup = False
            with self.assertLogs("run_pipeline", "ERROR"):
                self.assertFalse(self.run_job(lambda c: cp(c, 1), ps, popen=NonzeroPopen))
            self.assertTrue(self.ex._unsafe_cleanup)
            with self.assertRaises(RuntimeError):
                self.ex._save_checkpoint(1)

    def test_normal_exit_closes_stdout_and_untracks_without_engine_call(self):
        self.assertTrue(self.run_job(boom(AssertionError("no engine call expected"))))
        self.assertEqual(self.ex.running_containers, set())


class ShellBackup(Base):
    def backup(self, src, dest):
        return subprocess.run(["bash", "-c", f'source "{COMMON}"; backup_output_dir "$1" "$2"', "_", str(src), str(dest)],
                              capture_output=True, text=True)

    def test_normal_backup(self):
        src = self.tmp / "o"; (src / "sub").mkdir(parents=True); (src / "sub" / "f").write_text("v")
        r = self.backup(src, self.tmp / ".backup" / "o1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.tmp / ".backup" / "o1" / "sub" / "f").read_text(), "v")

    def test_symlinks_refused_nothing_copied(self):
        outside = self.tmp / "d"; outside.mkdir(); (outside / "s").write_text(SECRET)
        for target in (self.sentinel, outside):
            src = self.tmp / "o"; src.mkdir(exist_ok=True)
            (src / "link").symlink_to(target)
            r = self.backup(src, self.tmp / ".backup" / "o1")
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((self.tmp / ".backup" / "o1").exists())
            (src / "link").unlink()
        self.assertEqual(self.sentinel.read_text(), SECRET)

    def test_symlinked_source_or_dest_parent_refused(self):
        real = self.tmp / "real"; real.mkdir()
        (self.tmp / "srclink").symlink_to(real)
        (self.tmp / "parentlink").symlink_to(real)
        self.assertNotEqual(self.backup(self.tmp / "srclink", self.tmp / "b").returncode, 0)
        self.assertNotEqual(self.backup(real, self.tmp / "parentlink" / "b").returncode, 0)

    def test_cp_dash_P_preserves_links_without_reading_target(self):
        src = self.tmp / "o"; src.mkdir(); (src / "link").symlink_to(self.sentinel)
        subprocess.run(["cp", "-R", "-P", str(src), str(self.tmp / "c")], check=True)
        self.assertTrue((self.tmp / "c" / "link").is_symlink())

    def test_missing_source_fails(self):
        self.assertNotEqual(self.backup(self.tmp / "nope", self.tmp / "b").returncode, 0)


if __name__ == "__main__":
    unittest.main()
