"""Direct `--stepN` shell runs write a private log; engine and binaries are fake (no real Docker)."""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_private_logs import Base, FakePopen, ROOT, run_pipeline  # noqa: E402

FAKE_ENGINE = """#!/bin/sh
case "$1" in
  image|ps|stop) exit 0 ;;
  run)
    echo "Error: mock"
    if [ -n "$FAKE_READY" ]; then
      : > "$FAKE_READY"; i=0
      while [ ! -e "$FAKE_GO" ] && [ "$i" -lt 300 ]; do sleep 0.1; i=$((i+1)); done
    fi
    exit "${FAKE_RC:-0}" ;;
esac
"""
BAD_TEE = "#!/bin/sh\ncat >/dev/null\nexit 1\n"


class DirectStep(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="my proj ")).resolve()  # path with spaces
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.scripts = self.tmp / "pkg dir" / "bin dir"
        self.scripts.mkdir(parents=True)
        for n in ("run.sh", "run_with_local_preparation.sh", "common.sh", "run_pipeline.py"):
            shutil.copy(ROOT / n, self.scripts / n)
        self.cwd = self.tmp / "work dir"; self.cwd.mkdir()
        self.data = self.cwd / "data"; self.data.mkdir()
        fake = self.tmp / "engine"; fake.write_text(FAKE_ENGINE)
        tools = self.tmp / "tools"; tools.mkdir()
        for n in ("terraform", "tfpolicy"):
            (tools / n).write_text("#!/bin/sh\n")
        for f in (fake, tools / "terraform", tools / "tfpolicy"):
            f.chmod(0o755)
        self.badbin = self.tmp / "badbin"; self.badbin.mkdir()
        (self.badbin / "tee").write_text(BAD_TEE); (self.badbin / "tee").chmod(0o755)
        self.write_env()
        self.fake = fake

    def write_env(self, extra=""):
        (self.cwd / ".env").write_text(
            f'DOCKER_CLI="{self.tmp / "engine"}"\nDATA_DIR=./data\n'
            f'TERRAFORM_BINARY_PATH="{self.tmp / "tools" / "terraform"}"\n'
            f'TFPOLICY_BINARY_PATH="{self.tmp / "tools" / "tfpolicy"}"\n'
            "AUTH_PROVIDER=litellm\nMODEL_BASE_URL=http://x\nMODEL_API_KEY=k\nMODEL_NAME=m\n" + extra)

    def sh(self, *args, rc=0, path_prefix="", **env):
        e = {"PATH": f"{path_prefix}/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.tmp), "FAKE_RC": str(rc)}
        e.update(env)
        return subprocess.run(["bash", str(self.scripts / "run_with_local_preparation.sh"), *args],
                              capture_output=True, text=True, cwd=self.cwd, env=e)

    def runs(self):
        root = self.data / ".logs"
        return sorted(root.glob("run-*")) if root.exists() else []

    def checker(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "skills/tfpac-run/scripts/result_check.py"), *args],
                              capture_output=True, text=True, cwd=self.cwd)

    def test_failed_step_keeps_exit_code_and_private_log(self):
        r = self.sh("--no-confirm", "step3-summary", rc=3)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("Error: mock", r.stdout)  # still shown on the terminal
        (run,) = self.runs()
        self.assertIn(f"Private log dir: {run}", r.stdout)
        self.assertEqual(stat.S_IMODE(run.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.data / ".logs").stat().st_mode), 0o700)
        text = (run / "stage3.log").read_text()
        self.assertIn("Error: mock", text)
        self.assertIn("Return code: 3", text)
        self.assertEqual(list((self.data / "output").rglob("*.log")), [])
        d = self.checker()  # default selects the fresh run from the config cwd
        self.assertEqual(d.returncode, 0, d.stdout)
        self.assertEqual(json.loads(d.stdout)["log_dir"], str(run))
        e = self.checker("--log-dir", str(run))
        self.assertEqual(json.loads(e.stdout)["log_dir"], str(run))

    def test_success_and_stage_names(self):
        for step, name in (("step0-extraction", "stage0.log"), ("step3-summary", "stage3.log")):
            r = self.sh("--no-confirm", step)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            (log,) = (self.data / ".logs").glob(f"run-*/{name}")
            self.assertIn("Return code: 0", log.read_text())
        self.assertEqual(len(self.runs()), 2)

    def test_marker_skips_capture_even_if_env_file_sets_it(self):
        self.write_env("PIPELINE_LOG_CAPTURED=0\n")
        r = self.sh("--no-confirm", "step3-summary", rc=3, PIPELINE_LOG_CAPTURED="1")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.runs(), [])
        self.assertNotIn("Private log dir", r.stdout)

    def test_dryrun_does_not_capture(self):
        r = self.sh("--dryrun", "step3-summary")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.runs(), [])

    def test_unsafe_log_root_refused_before_docker(self):
        elsewhere = self.tmp / "elsewhere"; elsewhere.mkdir()
        (self.data / ".logs").symlink_to(elsewhere)
        r = self.sh("--no-confirm", "step3-summary")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Error: mock", r.stdout)
        self.assertIn("Unsafe log root", r.stderr)

    def test_log_write_failure_is_not_reported_as_success(self):
        r = self.sh("--no-confirm", "step3-summary", path_prefix=f"{self.badbin}:")
        self.assertEqual(r.returncode, 1)
        self.assertIn("failed to write private log", r.stderr)
        r = self.sh("--no-confirm", "step3-summary", rc=3, path_prefix=f"{self.badbin}:")
        self.assertEqual(r.returncode, 3)


    def test_signal_to_parent_while_engine_fails_is_not_success(self):
        # /bin/bash (3.2 on macOS) runs the trap before PIPESTATUS is read; the signal must still win
        for sig, code in ((signal.SIGTERM, 143), (signal.SIGINT, 130)):
            with self.subTest(sig=sig.name):
                ready, go = self.tmp / f"ready-{code}", self.tmp / f"go-{code}"
                env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.tmp), "FAKE_RC": "3",
                       "FAKE_READY": str(ready), "FAKE_GO": str(go)}
                p = subprocess.Popen(["/bin/bash", str(self.scripts / "run_with_local_preparation.sh"),
                                      "--no-confirm", "step3-summary"], stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, cwd=self.cwd, env=env)
                try:
                    deadline = time.time() + 30
                    while not ready.exists() and p.poll() is None and time.time() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(ready.exists(), "script never reached the engine")
                    os.kill(p.pid, sig)  # parent only, the engine keeps running
                    go.touch()
                    out, _ = p.communicate(timeout=30)
                finally:
                    if p.poll() is None:
                        p.kill(); p.communicate()
                self.assertEqual(p.returncode, code, out)
                texts = [f.read_text() for f in (self.data / ".logs").glob("run-*/stage3.log")]
                self.assertTrue(any(f"Return code: {code}" in t for t in texts), texts)
                self.assertFalse(any("Return code: 0" in t for t in texts), texts)


class OrchestratorMarker(Base):
    def test_run_docker_command_sets_capture_marker(self):
        ex = self.make()
        seen = {}
        def popen(cmd, **kw):
            seen.update(kw["env"])
            return FakePopen()
        with mock.patch.object(run_pipeline.subprocess, "Popen", popen), mock.patch("builtins.print"):
            self.assertTrue(ex._run_docker_command("s", "p", "Stage X"))
        self.assertEqual(seen["PIPELINE_LOG_CAPTURED"], "1")


if __name__ == "__main__":
    unittest.main()
