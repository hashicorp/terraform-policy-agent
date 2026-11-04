# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MPL-2.0
"""Path guards, wrapper process-group lifecycle and checkpoint commit-marker transactions.

Run from terraform-policy-agent/: python3 -m unittest tests.test_private_core_review
Uses a REAL fake wrapper script and REAL descendant processes; only the container
engine (subprocess.run docker rm/stop/ps) is faked. A real Docker/Podman is not exercised.
"""
import os
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_pipeline  # noqa: E402
from run_pipeline import validate_path_below_data as v  # noqa: E402

REAL_RUN = subprocess.run
CHILD = ("import os,signal,sys,time\n"
         "if os.environ.get('IGNORE_TERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
         "open(os.environ['PIDF'],'w').write(str(os.getpid()))\n"
         "time.sleep(20)\nopen(os.environ['LATE'],'w').write('x')\n")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = self.tmp / "data"

    def runner(self, output="output", **env):
        e = {"DATA_DIR": str(self.data), "OUTPUT_DIR": output}
        e.update(env)
        with mock.patch.dict(os.environ, e), mock.patch.object(sys, "argv", ["x"]), \
                mock.patch("run_pipeline.atexit.register"), mock.patch("run_pipeline.signal.signal"):
            r = run_pipeline.PipelineExecutor(Path(run_pipeline.__file__).parent)
        r.running_containers.clear()
        return r


class ValidatePath(Base):
    def test_rules(self):
        d = self.tmp / "d"; d.mkdir()
        (d / "real").mkdir(); (d / "file").write_text("x")
        (d / "lnk").symlink_to(d / "real")
        self.assertEqual(v(d / "real/new/x/", d), d / "real/new/x")
        self.assertEqual(v(d / "./real/.", d), d / "real")
        self.assertEqual(v(d, d), d)
        for bad in (d / "lnk", d / "lnk/x", d / "real/../real", d / "file/x", self.tmp / "other"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                v(bad, d)
        self.assertEqual(v(d / "file", d), d / "file")  # leaf regular file: caller decides

    def test_relative_to_cwd_and_trusted_data_ancestor_symlink(self):
        real = self.tmp / "real"; (real / "data").mkdir(parents=True)
        (self.tmp / "alias").symlink_to(real)
        d = self.tmp / "alias/data"  # symlinked ancestor OF data_dir is trusted
        self.assertEqual(v(d / "o/x", d), d / "o/x")
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        self.assertEqual(v("alias/data/o", d), d / "o")
        with self.assertRaises(ValueError):
            v("alias/data/../x", d)


class SymlinkAncestors(Base):
    def test_save_and_restore_refuse_swapped_ancestor_and_preserve_state(self):
        r = self.runner("real/out")
        (r.output_dir / "a.txt").write_text("v1")
        r._save_checkpoint(1)
        meta = r._checkpoint_path().read_bytes()
        snap = (r._stage_snapshot_dir(1) / "a.txt").read_text()
        host = self.tmp / "host"; (host / "out").mkdir(parents=True)
        (host / "out" / "h.txt").write_text("HOST")
        shutil.rmtree(self.data / "real"); (self.data / "real").symlink_to(host)
        with self.assertRaises(ValueError):
            r._save_checkpoint(1)
        with self.assertRaises(ValueError):
            r._restore_checkpoint(1)
        self.assertEqual(r._checkpoint_path().read_bytes(), meta)
        self.assertEqual((r._stage_snapshot_dir(1) / "a.txt").read_text(), snap)
        self.assertEqual((host / "out/h.txt").read_text(), "HOST")
        self.assertEqual(sorted(p.name for p in host.rglob("*") if p.is_file()), ["h.txt"])

    def test_safe_copy_tree_data_dir_refuses_ancestor_links(self):
        (self.data / "real").mkdir(parents=True); (self.data / "real/f").write_text("x")
        (self.data / "lnk").symlink_to(self.data / "real")
        with self.assertRaises(ValueError):
            run_pipeline.safe_copy_tree(self.data / "lnk", self.data / "dst", data_dir=self.data)
        with self.assertRaises(ValueError):
            run_pipeline.safe_copy_tree(self.data / "real", self.data / "lnk/dst", data_dir=self.data)
        self.assertFalse((self.data / "dst").exists())


class DotDotDataDir(Base):
    def setUp(self):
        super().setUp()
        (self.tmp / "work").mkdir()
        old = os.getcwd()
        os.chdir(self.tmp / "work")
        self.addCleanup(os.chdir, old)

    def check(self, data_env):
        r = self.runner("output", DATA_DIR=data_env)
        self.assertEqual(r.data_dir, self.data)
        self.assertNotIn("..", r.data_dir.parts)
        (r.output_dir / "a.txt").write_text("v1")
        r._save_checkpoint(1)
        (r.output_dir / "a.txt").write_text("v2")
        r._restore_checkpoint(1)
        self.assertEqual((r.output_dir / "a.txt").read_text(), "v1")
        bk = r.data_dir / ".backup" / "b"
        run_pipeline.safe_copy_tree(r.output_dir, bk, data_dir=r.data_dir)
        self.assertEqual((bk / "a.txt").read_text(), "v1")
        # ancestor swap below the trusted root is still refused, state preserved
        host = self.tmp / "host"; (host / "output").mkdir(parents=True)
        shutil.rmtree(r.data_dir / "output"); (r.data_dir / "output").symlink_to(host / "output")
        meta = r._checkpoint_path().read_bytes()
        with self.assertRaises((ValueError, RuntimeError)):
            r._save_checkpoint(1)
        with self.assertRaises((ValueError, RuntimeError)):
            r._restore_checkpoint(1)
        self.assertEqual(r._checkpoint_path().read_bytes(), meta)
        self.assertEqual((r._stage_snapshot_dir(1) / "a.txt").read_text(), "v1")
        self.assertEqual(list(host.rglob("*.txt")), [])

    def test_relative_dotdot_data_dir(self):
        self.check("../data")

    def test_absolute_dotdot_data_dir(self):
        self.check(str(self.tmp / "work" / ".." / "data"))


class MountGuards(Base):
    def test_output_dotdot_rejected(self):
        for out in ("../x", "a/../b"):
            with self.subTest(out), self.assertRaises(ValueError):
                self.runner(out)

    def test_skills_output_overlap_both_directions_and_case(self):
        sk = self.tmp / "skills"; (sk / "sub").mkdir(parents=True)
        self.data.mkdir(exist_ok=True)
        with self.assertRaises(ValueError):  # skills inside output
            self.runner("output", LOCAL_SKILLS_DIR=str(self.data / "output" / "s"))
        with self.assertRaises(ValueError):  # skills contains output
            self.runner("output", LOCAL_SKILLS_DIR=str(self.data))
        with self.assertRaises(ValueError):  # case alias
            self.runner("output", LOCAL_SKILLS_DIR=str(self.data / "OUTPUT"))
        link = self.tmp / "slink"; link.symlink_to(self.data)  # resolved overlap
        with self.assertRaises(ValueError):
            self.runner("output", LOCAL_SKILLS_DIR=str(link / "output"))
        self.runner("output", LOCAL_SKILLS_DIR=str(sk))  # disjoint is fine

    def test_rejected_mounts_create_nothing_missing_or_existing(self):
        for skills in (self.data / "output" / "missing", self.data):
            with self.subTest(skills=skills), self.assertRaises(ValueError):
                self.runner("output", LOCAL_SKILLS_DIR=str(skills))
        self.assertFalse((self.data / "input").exists())  # rejected before any mkdir
        self.assertFalse((self.data / ".logs").exists())

    def test_trusted_data_dir_ancestor_symlink_runs(self):
        real = self.tmp / "real"; real.mkdir()
        (self.tmp / "alias").symlink_to(real)
        r = self.runner("output", DATA_DIR=str(self.tmp / "alias" / "data"))
        (r.output_dir / "a.txt").write_text("v1")
        r._save_checkpoint(1)
        r._restore_checkpoint(1)
        self.assertEqual((real / "data/output/a.txt").read_text(), "v1")

    def test_clean_choice_refuses_symlinked_output_ancestor_keeps_host_data(self):
        host = self.tmp / "host"; (host / "out").mkdir(parents=True)
        (host / "out" / "h.txt").write_text("HOST")
        (self.data / "real").parent.mkdir(parents=True, exist_ok=True)
        (self.data / "real").symlink_to(host)
        with mock.patch.object(sys, "argv", ["x"]), mock.patch("builtins.input", return_value="2"), \
                mock.patch("builtins.print"), self.assertRaises(ValueError):
            self.runner("real/out")
        self.assertEqual((host / "out/h.txt").read_text(), "HOST")


class LifecycleBase(Base):
    def setUp(self):
        super().setUp()
        self.r = self.runner()
        self.r._TERM_GRACE = 0.3
        self.r._KILL_GRACE = 1.0
        self.pidf, self.late = self.tmp / "pid", self.tmp / "late"
        (self.tmp / "child.py").write_text(CHILD)
        self.events = []
        env = {"PIDF": str(self.pidf), "LATE": str(self.late), "CHILD": str(self.tmp / "child.py"),
               "PY": sys.executable}
        p = mock.patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        self.addCleanup(self._reap)

    def _reap(self):
        if self.pidf.exists():
            try:
                os.kill(int(self.pidf.read_text()), 9)
            except (ProcessLookupError, ValueError):
                pass
        self.r.running_containers.clear()

    def wrapper(self, tail):
        s = self.tmp / "run.sh"
        s.write_text('#!/bin/sh\n"$PY" "$CHILD" &\n'
                     'i=0; while [ ! -s "$PIDF" ] && [ $i -lt 200 ]; do sleep 0.05; i=$((i+1)); done\n' + tail)
        s.chmod(0o755)
        self.r.run_sh = s

    def wait_child_started(self, p, timeout=10):
        """Bounded wait for the wrapper's descendant; on expiry fail (the finally/cleanups reap)."""
        deadline = time.monotonic() + timeout
        while not (self.pidf.exists() and self.pidf.read_text()):
            if time.monotonic() >= deadline:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                p.wait(timeout=5)
                p.stdout.close()
                self.fail("descendant never started")
            time.sleep(0.02)

    def child_pid(self):
        return int(self.pidf.read_text())

    def engine(self, rm_ok=True):
        def fake(cmd, **kw):
            if cmd[0] == self.r.docker_cli:
                self.events.append((cmd[1], alive(self.child_pid())))
                if cmd[1] == "ps":
                    return subprocess.CompletedProcess(cmd, 0, b"", b"")
                return subprocess.CompletedProcess(cmd, 0 if rm_ok else 1, b"", b"")
            return REAL_RUN(cmd, **kw)
        return mock.patch.object(run_pipeline.subprocess, "run", fake)

    def go(self, timeout=30):
        with self.engine(), mock.patch("builtins.print"):
            return self.r._run_docker_command("s", "p", "Stage N", timeout_seconds=timeout)

    def assertGoneBeforeEngine(self):
        self.assertTrue(self.events, "engine cleanup never ran")
        self.assertTrue(all(not a for _, a in self.events), self.events)
        self.assertFalse(alive(self.child_pid()))
        self.assertFalse(self.late.exists())


class Lifecycle(LifecycleBase):
    def test_wrapper_exits_first_rc0_descendant_killed_and_stage_fails(self):
        self.wrapper("exit 0\n")
        self.assertFalse(self.go())
        self.assertGoneBeforeEngine()

    def test_nonzero_exit_descendant_killed_before_engine(self):
        self.wrapper("exit 3\n")
        self.assertFalse(self.go())
        self.assertGoneBeforeEngine()

    def test_timeout_kills_descendant_before_engine(self):
        self.wrapper("sleep 30\n")
        self.assertFalse(self.go(timeout=0.2))
        self.assertGoneBeforeEngine()

    def test_sigterm_ignoring_descendant_is_sigkilled(self):
        with mock.patch.dict(os.environ, {"IGNORE_TERM": "1"}):
            self.wrapper("exit 1\n")
            self.assertFalse(self.go())
        self.assertGoneBeforeEngine()

    def test_clean_exit_without_descendants_succeeds(self):
        s = self.tmp / "ok.sh"; s.write_text("#!/bin/sh\necho hi\n"); s.chmod(0o755)
        self.r.run_sh = s
        with self.engine(), mock.patch("builtins.print"):
            self.assertTrue(self.r._run_docker_command("s", "p", "Stage N"))
        self.assertEqual(self.events, [])

    def test_abort_run_kills_group_before_engine(self):
        self.wrapper("sleep 30\n")
        p = subprocess.Popen([str(self.r.run_sh)], stdout=subprocess.PIPE, start_new_session=True)
        self.r._track_group(p)
        self.wait_child_started(p)
        with self.engine():
            self.r._abort_run(p, "c1")
        self.assertGoneBeforeEngine()

    def test_failed_termination_blocks_engine_save_and_new_jobs(self):
        self.wrapper("exit 1\n")
        with mock.patch.object(self.r, "_group_alive", return_value=True):
            self.assertFalse(self.go())
        self.assertTrue(self.r._unsafe_cleanup)
        self.assertEqual(self.events, [])  # engine never claimed absence
        with self.assertRaises(RuntimeError):
            self.r._save_checkpoint(1)
        with mock.patch.object(run_pipeline.subprocess, "Popen",
                               side_effect=AssertionError("no new job")):
            self.assertFalse(self.r._run_docker_command("s", "p", "Stage 2"))

    def test_popen_failure_not_tracked_and_container_untracked(self):
        with mock.patch.object(run_pipeline.subprocess, "Popen", side_effect=OSError("x")), \
                self.engine(), mock.patch("builtins.print"):
            self.assertFalse(self.r._run_docker_command("s", "p", "Stage N", container_suffix="z"))
        self.assertFalse(self.r._groups)
        self.assertFalse(self.r.running_containers)
        self.assertFalse(self.r._unsafe_cleanup)

    def test_signal_handler_stops_tracked_groups(self):
        self.wrapper("sleep 30\n")
        p = subprocess.Popen([str(self.r.run_sh)], stdout=subprocess.PIPE, start_new_session=True)
        self.r._track_group(p)
        self.wait_child_started(p)
        with mock.patch("builtins.print"), self.assertRaises(SystemExit):
            self.r._signal_handler(15, None)
        p.wait(timeout=5); p.stdout.close()
        self.assertFalse(alive(self.child_pid()))


class SignalCleanup(LifecycleBase):
    PARENT = textwrap.dedent("""
        import os, sys
        sys.path.insert(0, os.environ["POLICY_DIR"])
        from pathlib import Path
        import run_pipeline
        r = run_pipeline.PipelineExecutor(Path(run_pipeline.__file__).parent)
        r.run_sh = Path(os.environ["WRAP"])
        r._run_docker_command("s", "p", "Stage N", timeout_seconds=60)
        """)

    def _fire(self, signame):
        self.wrapper("sleep 30\n")
        dlog = self.tmp / "dlog"
        fake = self.tmp / "fakedocker"
        fake.write_text('#!/bin/sh\necho "$1 $(kill -0 $(cat "$PIDF") 2>/dev/null && echo alive || echo dead)" >> "$DLOG"\n')
        fake.chmod(0o755)
        env = dict(os.environ, DATA_DIR=str(self.data), OUTPUT_DIR="out_" + signame, DOCKER_CLI=str(fake),
                   DLOG=str(dlog), WRAP=str(self.r.run_sh),
                   POLICY_DIR=str(Path(run_pipeline.__file__).parent))
        env.pop("LOCAL_SKILLS_DIR", None)
        parent = subprocess.Popen([sys.executable, "-c", self.PARENT], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(parent.kill)
        self.addCleanup(parent.stderr.close)
        deadline = time.monotonic() + 15
        while not (self.pidf.exists() and self.pidf.read_text()):
            err = parent.stderr.read().decode() if parent.poll() is not None else ""
            self.assertLess(time.monotonic(), deadline, "descendant never started: " + err)
            time.sleep(0.05)
        os.kill(parent.pid, getattr(signal, signame))
        self.assertEqual(parent.wait(timeout=20), 1)
        self.assertFalse(alive(self.child_pid()))
        self.assertFalse(self.late.exists())
        calls = dlog.read_text().split("\n")
        self.assertIn("rm dead", calls)
        self.assertNotIn("rm alive", calls)

    def test_hangup_quit_term_int_clean_up_descendant_before_engine(self):
        for name in ("SIGHUP", "SIGQUIT", "SIGTERM", "SIGINT"):
            with self.subTest(name):
                for f in (self.pidf, self.late):
                    f.unlink(missing_ok=True)
                self._fire(name)

    GAP_PARENT = PARENT.replace(
        "r._run_docker_command(",
        "real = r._track_group\n"
        "fired = []\n"
        "def track(p):\n"
        "    if fired: return real(p)\n"
        "    fired.append(1)\n"
        "    while not (os.path.exists(os.environ['PIDF']) and open(os.environ['PIDF']).read()):\n"
        "        time.sleep(0.02)\n"
        "    os.kill(os.getpid(), signal.SIGTERM)  # real signal in the Popen->register gap\n"
        "    return real(p)\n"
        "r._track_group = track\n"
        "r._run_docker_command(").replace("import os, sys", "import os, sys, time, signal")

    def test_real_sigterm_in_registration_gap_cleans_up_wrapper(self):
        self.wrapper("sleep 30\n")
        dlog, fake = self.tmp / "dlog", self.tmp / "fakedocker"
        fake.write_text('#!/bin/sh\necho "$1 $(kill -0 $(cat "$PIDF") 2>/dev/null && echo alive || echo dead)" >> "$DLOG"\n')
        fake.chmod(0o755)
        env = dict(os.environ, DATA_DIR=str(self.data), OUTPUT_DIR="out_gap", DOCKER_CLI=str(fake),
                   DLOG=str(dlog), WRAP=str(self.r.run_sh),
                   POLICY_DIR=str(Path(run_pipeline.__file__).parent))
        env.pop("LOCAL_SKILLS_DIR", None)
        parent = subprocess.Popen([sys.executable, "-c", self.GAP_PARENT], env=env, start_new_session=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(parent.stderr.close)
        self.addCleanup(lambda: os.killpg(parent.pid, 9) if parent.poll() is None else None)
        try:
            rc = parent.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.fail("parent did not exit after SIGTERM in the registration gap")
        self.assertEqual(rc, 1, parent.stderr.read().decode())
        self.assertFalse(alive(self.child_pid()))
        self.assertFalse(self.late.exists())
        calls = dlog.read_text().split("\n")
        self.assertIn("rm dead", calls)
        self.assertNotIn("rm alive", calls)

    POPEN_PARENT = PARENT.replace(
        "r._run_docker_command(",
        "import subprocess\n"
        "real = subprocess.Popen\n"
        "def popen(*a, **kw):\n"
        "    p = real(*a, **kw)\n"
        "    if kw.get('start_new_session') is not True: return p  # only the wrapper launch\n"
        "    subprocess.Popen = real\n"
        "    while not (os.path.exists(os.environ['PIDF']) and open(os.environ['PIDF']).read()):\n"
        "        time.sleep(0.02)\n"
        "    os.kill(os.getpid(), signal.SIGTERM)  # real signal: Popen returned, not yet assigned\n"
        "    return p\n"
        "subprocess.Popen = popen\n"
        "try:\n"
        "    r._run_docker_command(").replace(
        '"Stage N", timeout_seconds=60)',
        '"Stage N", timeout_seconds=60)\n'
        'except SystemExit as e:\n'
        '    print("FLAGS", r._launching, r._deferred_exit, r._stopping, e.code, flush=True)\n'
        '    raise').replace("import os, sys", "import os, sys, time, signal")

    def test_real_sigterm_before_popen_result_assigned_cleans_up_wrapper(self):
        self.wrapper("sleep 30\n")
        dlog, fake = self.tmp / "dlog", self.tmp / "fakedocker"
        fake.write_text('#!/bin/sh\necho "$1 $(kill -0 $(cat "$PIDF") 2>/dev/null && echo alive || echo dead)" >> "$DLOG"\n')
        fake.chmod(0o755)
        env = dict(os.environ, DATA_DIR=str(self.data), OUTPUT_DIR="out_popen", DOCKER_CLI=str(fake),
                   DLOG=str(dlog), WRAP=str(self.r.run_sh),
                   POLICY_DIR=str(Path(run_pipeline.__file__).parent))
        env.pop("LOCAL_SKILLS_DIR", None)
        parent = subprocess.Popen([sys.executable, "-c", self.POPEN_PARENT], env=env, start_new_session=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(parent.stderr.close)
        self.addCleanup(parent.stdout.close)
        self.addCleanup(lambda: os.killpg(parent.pid, 9) if parent.poll() is None else None)
        try:
            out, err = parent.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            self.fail("parent did not exit after SIGTERM before Popen result assigned")
        self.assertEqual(parent.returncode, 1, err.decode())
        self.assertIn("FLAGS False True True 1", out.decode())  # flag reset, deferred, exit code 1
        self.assertFalse(alive(self.child_pid()))
        self.assertFalse(self.late.exists())
        calls = dlog.read_text().split("\n")
        self.assertIn("rm dead", calls)
        self.assertNotIn("rm alive", calls)
        self.assertNotIn("stop alive", calls)

    def test_handler_reentry_with_lock_held_does_not_deadlock(self):
        done = threading.Event()

        def interrupted():  # handler runs on the thread that already holds the lock
            with self.r._groups_lock:
                self.r._stop_all_groups()
            done.set()
        t = threading.Thread(target=interrupted, daemon=True)
        t.start()
        # a deadlocked thread would keep the lock and hang the atexit cleanup: swap it out
        self.addCleanup(setattr, self.r, "_groups_lock", threading.RLock())
        self.assertTrue(done.wait(5), "re-entrant group cleanup deadlocked")

    # --- shutdown between Popen return and group registration --------------------------
    def _gap(self, hook):
        """Run hook() once the wrapper+descendant are live but before _track_group registers."""
        self.wrapper("sleep 30\n")
        procs, fired, real_popen, real_track = [], [], subprocess.Popen, self.r._track_group

        def popen(*a, **kw):
            procs.append(real_popen(*a, **kw))
            return procs[-1]

        def track(process):
            if fired:  # the gap happens once; later registrations (abort path) are real
                return real_track(process)
            fired.append(1)
            deadline = time.monotonic() + 10
            while not (self.pidf.exists() and self.pidf.read_text()):
                self.assertLess(time.monotonic(), deadline, "descendant never started")
                time.sleep(0.02)
            hook()
            return real_track(process)

        def reap():  # outer guard: never orphan the wrapper even if the code under test is buggy
            for q in procs:
                try:
                    os.killpg(q.pid, 9)
                except (ProcessLookupError, PermissionError):
                    pass
                q.wait(timeout=5)
                q.stdout and q.stdout.close()
        self.addCleanup(reap)
        return mock.patch.object(run_pipeline.subprocess, "Popen", popen), \
            mock.patch.object(self.r, "_track_group", track)

    def assertNoEngineClaimWhileAlive(self):
        self.assertFalse([e for e in self.events if e[0] in ("rm", "ps") and e[1]], self.events)
        self.assertTrue([e for e in self.events if e[0] == "rm"], "engine rm never confirmed")
        self.assertFalse(alive(self.child_pid()))
        self.assertFalse(self.late.exists())
        self.assertFalse(self.r._groups)
        self.assertFalse(self.r._unsafe_cleanup)

    def test_handler_exit_in_registration_gap_stops_unregistered_wrapper(self):
        def hook():  # signal handler runs on the main thread in the gap
            with mock.patch("builtins.print"):
                self.r._signal_handler(15, None)
        p, t = self._gap(hook)
        with p, t, self.engine(), mock.patch("builtins.print"), self.assertRaises(SystemExit):
            self.r._run_docker_command("s", "p", "Stage N", timeout_seconds=30)
        self.assertNoEngineClaimWhileAlive()

    def test_worker_registering_after_shutdown_stops_its_group(self):
        p, t = self._gap(lambda: setattr(self.r, "_stopping", True))
        out = []
        with p, t, self.engine(), mock.patch("builtins.print"):
            th = threading.Thread(target=lambda: out.append(
                self.r._run_docker_command("s", "p", "Stage N", timeout_seconds=30)), daemon=True)
            th.start(); th.join(10)
            alive_thread = th.is_alive()
            if alive_thread:
                self.r._stop_all_groups()  # unblock a buggy implementation, then fail below
                th.join(10)
        self.assertFalse(alive_thread, "worker kept running after shutdown")
        self.assertEqual(out, [False])
        self.assertNoEngineClaimWhileAlive()

    def test_no_new_jobs_after_signal(self):
        self.r._stopping = True
        with mock.patch.object(run_pipeline.subprocess, "Popen",
                               side_effect=AssertionError("no new job")):
            self.assertFalse(self.r._run_docker_command("s", "p", "Stage N"))


class CheckpointAtomicity(Base):
    def setUp(self):
        super().setUp()
        self.r = self.runner()
        (self.r.output_dir / "a.txt").write_text("v1")
        self.r._save_checkpoint(1)
        self.meta = self.r._checkpoint_path().read_bytes()
        (self.r.output_dir / "a.txt").write_text("v2")

    def assertOldIntact(self):
        self.assertEqual(self.r._checkpoint_path().read_bytes(), self.meta)
        self.assertEqual((self.r._stage_snapshot_dir(1) / "a.txt").read_text(), "v1")

    def test_serialization_failure_keeps_old_snapshot_and_json(self):
        with mock.patch.object(run_pipeline.json, "dump", side_effect=ValueError("boom")), \
                self.assertRaises(ValueError):
            self.r._save_checkpoint(1)
        self.assertOldIntact()

    def test_metadata_install_failure_rolls_back_snapshot(self):
        with mock.patch.object(run_pipeline.os, "replace", side_effect=OSError("boom")), \
                self.assertRaises(OSError):
            self.r._save_checkpoint(1)
        self.assertOldIntact()

    def test_first_save_install_failure_leaves_no_snapshot(self):
        r = self.runner("out2")
        (r.output_dir / "a.txt").write_text("x")
        with mock.patch.object(run_pipeline.os, "replace", side_effect=OSError("boom")), \
                self.assertRaises(OSError):
            r._save_checkpoint(2)
        self.assertFalse(r._stage_snapshot_dir(2).exists())
        self.assertNotIn("stage2_done", json.loads(r._checkpoint_path().read_text()))

    def test_failed_rollback_keeps_artifacts(self):
        real = os.rename

        def rename(a, b, *k):
            if str(a).endswith("/old"):
                raise OSError("rollback boom")
            return real(a, b, *k)
        with mock.patch.object(run_pipeline.os, "replace", side_effect=OSError("boom")), \
                mock.patch.object(run_pipeline.os, "rename", rename), \
                self.assertLogs("run_pipeline", "ERROR"), self.assertRaises(OSError):
            self.r._save_checkpoint(1)
        self.assertEqual((self.r._checkpoint_dir().glob(".stage1-*/old/a.txt").__next__()).read_text(), "v1")

    def interrupt_after(self, fn_name, nth):
        """Patch os.<fn_name> so the nth call runs for REAL, then raises SystemExit (the handler)."""
        real, n = getattr(os, fn_name), [0]

        def wrapper(*a, **k):
            res = real(*a, **k)
            n[0] += 1
            if n[0] == nth:
                raise SystemExit(1)
            return res
        return mock.patch.object(run_pipeline.os, fn_name, wrapper)

    def assertNoTemp(self, r):
        self.assertEqual([p.name for p in r._checkpoint_dir().glob(".stage*")], [])

    def test_interrupt_after_old_snapshot_move_restores_old_pair(self):
        with self.interrupt_after("rename", 1), self.assertRaises(SystemExit):
            self.r._save_checkpoint(1)  # old snapshot moved aside, nothing else done
        self.assertOldIntact()
        self.assertNoTemp(self.r)

    def test_interrupt_after_new_snapshot_install_restores_old_pair(self):
        with self.interrupt_after("rename", 2), self.assertRaises(SystemExit):
            self.r._save_checkpoint(1)  # new snapshot installed, JSON not yet
        self.assertOldIntact()
        self.assertNoTemp(self.r)

    def test_interrupt_after_metadata_commit_keeps_new_pair(self):
        with self.interrupt_after("replace", 1), self.assertRaises(SystemExit):
            self.r._save_checkpoint(1)  # JSON committed: old snapshot must not come back
        self.assertEqual((self.r._stage_snapshot_dir(1) / "a.txt").read_text(), "v2")
        self.assertNotEqual(self.r._checkpoint_path().read_bytes(), self.meta)
        self.assertTrue(json.loads(self.r._checkpoint_path().read_text())["stage1_done"])
        self.assertNoTemp(self.r)

    def test_first_save_interrupts_leave_old_or_new_state_consistently(self):
        for fn, expect_new in (("rename", False), ("replace", True)):
            with self.subTest(fn=fn):
                r = self.runner("out_" + fn)
                (r.output_dir / "a.txt").write_text("x")
                with self.interrupt_after(fn, 1), self.assertRaises(SystemExit):
                    r._save_checkpoint(2)  # no previous snapshot exists
                self.assertEqual(r._stage_snapshot_dir(2).exists(), expect_new)
                self.assertEqual(json.loads(r._checkpoint_path().read_text()).get("stage2_done", False),
                                 expect_new)
                self.assertNoTemp(r)

    def test_success_advances_snapshot_and_json(self):
        self.r._save_checkpoint(1)
        self.assertEqual((self.r._stage_snapshot_dir(1) / "a.txt").read_text(), "v2")
        self.assertNotEqual(self.r._checkpoint_path().read_bytes(), self.meta)


if __name__ == "__main__":
    unittest.main()
