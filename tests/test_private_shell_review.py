"""Shell hardening ported from PAC PR83: lexical OUTPUT_DIR guard, trusted DATA_DIR, skills/output
overlap before any mkdir, backup below-DATA_DIR checks and canonical direct-step headers.
Fake engine only (no real Docker). Run: python3 -W error::ResourceWarning -m unittest tests.test_private_shell_review
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_direct_step_logs as D  # noqa: E402

ROOT = D.ROOT
COMMON = ROOT / "common.sh"
ARGV_ENGINE = """#!/bin/sh
{ echo "--CALL"; printf '%s\\n' "$@"; } >> "$FAKE_ARGV"
exit 0
"""


def sh(code, *args):
    return subprocess.run(["bash", "-c", f'source "{COMMON}"; {code}', "_", *map(str, args)],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


class Base(unittest.TestCase):
    # reuse the direct-step fixture (private copy of scripts, fake tools) without inheriting its tests
    setUp = D.DirectStep.setUp
    write_env = D.DirectStep.write_env
    sh = D.DirectStep.sh
    runs = D.DirectStep.runs

    def setUp(self):  # noqa: F811
        D.DirectStep.setUp(self)
        self.fake.write_text(ARGV_ENGINE)
        self.argv = self.tmp / "argv"

    def step(self, *args, input_text=None, **env):
        e = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.tmp), "FAKE_ARGV": str(self.argv)}
        e.update(env)
        return subprocess.run(["bash", str(self.scripts / "run_with_local_preparation.sh"), *args],
                              capture_output=True, text=True, cwd=self.cwd, env=e, input=input_text,
                              stdin=None if input_text is not None else subprocess.DEVNULL, timeout=60)

    def run_call(self):
        calls = self.argv.read_text().split("--CALL\n") if self.argv.exists() else []
        return next((c.splitlines() for c in calls if c.startswith("run\n")), None)

    def tree(self):
        return sorted(str(p.relative_to(self.cwd)) for p in self.cwd.rglob("*"))


class Guards(Base):
    def test_normalize_output_dir(self):
        for raw, want in (("output/", "output"), ("output/.", "output"), ("./a//b/", "a/b"), (".", ".")):
            r = sh('normalize_output_dir "$1"', raw)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, want), raw)
        for bad in ("a/../b", ".."):
            self.assertNotEqual(sh('normalize_output_dir "$1"', bad).returncode, 0, bad)

    def test_absolute_and_dotdot_output_rejected_before_engine(self):
        for out in ("/abs/out", "a/../b", ".."):
            r = self.step("--no-confirm", "step3-summary", OUTPUT_DIR=out)
            self.assertEqual(r.returncode, 1, out)
            self.assertIsNone(self.run_call(), out)

    def test_symlinked_output_root_never_backed_up(self):
        host = self.tmp / "host"; host.mkdir(); (host / "SENTINEL").write_text("v")
        (self.data / "output").symlink_to(host)
        for out in ("output", "output/", "output/.", "./output//"):
            r = self.step("step0-extraction", input_text="1\n", OUTPUT_DIR=out)
            self.assertNotIn("Backed up", r.stdout, out)
            self.assertFalse((self.data / ".backup").exists(), out)
        self.assertEqual({p.name for p in host.iterdir()}, {"SENTINEL"})

    def test_backup_helper_refuses_links_and_dotdot_below_data(self):
        host = self.tmp / "host"; (host / "out").mkdir(parents=True); (host / "out" / "f").write_text("v")
        (self.data / "a").symlink_to(host)
        (self.data / "o").mkdir(); (self.data / "o" / "f").write_text("v")
        b = self.data / ".backup" / "o"
        for src in (self.data / "a" / "out", f"{self.data}/x/../o", self.tmp / "host" / "out"):
            self.assertNotEqual(sh('backup_output_dir "$1" "$2" "$3"', src, b, self.data).returncode, 0, str(src))
        self.assertFalse((self.data / ".backup").exists())
        ok = sh('backup_output_dir "$1" "$2" "$3"', self.data / "o", b, self.data)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual((b / "f").read_text(), "v")
        # compat: two-argument form (no trusted root) still works
        self.assertEqual(sh('backup_output_dir "$1" "$2"', self.data / "o", self.data / ".backup" / "two").returncode, 0)

    def test_data_dir_with_dotdot_spaces_and_root_link_backs_up(self):
        data = self.tmp / "custom data"
        (data / "output").mkdir(parents=True); (data / "output" / "f").write_text("v")
        link = self.tmp / "rootlink"; link.symlink_to(data)  # trusted root may itself be reached via a link
        for raw in (f"{self.cwd}/../custom data", str(link)):
            r = self.step("step0-extraction", input_text="1\n", DATA_DIR=raw)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(list((data / ".backup").glob("output_*/f")))

    def test_missing_or_empty_relative_data_dir_fails_without_using_cwd(self):
        before = self.tree()
        r = self.step("--no-confirm", "step3-summary", DATA_DIR="./nodata")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ERROR: DATA_DIR not found: ./nodata", r.stderr)
        self.assertEqual(self.tree(), before)
        self.assertIsNone(self.run_call())

    def overlap(self, out, skills):
        return sh('assert_skills_not_overlapping_output "$1" "$2"', out, skills).returncode

    def test_skills_output_overlap_either_direction_and_case(self):
        o = self.data / "branch" / "out"
        for skills in (o, o / "s", self.data / "branch", self.data, self.data / "BRANCH" / "Out",
                       self.data / "branch" / "x" / ".." / "out"):
            self.assertNotEqual(self.overlap(o, skills), 0, str(skills))
        self.assertEqual(self.overlap(o, self.tmp / "skills"), 0)
        self.assertEqual(self.overlap(o, self.data / "branch" / "outer"), 0)

    def test_skills_overlap_through_symlink(self):
        o = self.data / "out"; o.mkdir()
        (self.tmp / "s").symlink_to(o)
        self.assertNotEqual(self.overlap(o, self.tmp / "s"), 0)


class SkillsBeforeMkdir(Base):
    def setUp(self):
        super().setUp()
        (self.data / "input").mkdir()
        (self.data / "input" / "policy_goal.txt").write_text("seed")

    def go(self, skills, output="branch/out", via="export", args=("--no-confirm", "step3-summary"), **extra):
        if via == "env":
            original = (self.cwd / ".env").read_text()
            try:
                val = skills if skills.startswith('"') else f'"{skills}"'  # tmp path has spaces
                with open(self.cwd / ".env", "a") as f:
                    f.write(f"OUTPUT_DIR={output}\nLOCAL_SKILLS_DIR={val}\n")
                return self.step(*args, **extra)
            finally:
                (self.cwd / ".env").write_text(original)
        return self.step(*args, OUTPUT_DIR=output, LOCAL_SKILLS_DIR=skills, **extra)

    def test_missing_overlapping_skills_rejected_before_any_mkdir(self):
        d = self.data
        (d / "lnk").symlink_to(d / "branch")  # dangling, absolute target
        (d / "rlnk").symlink_to("branch")  # dangling, relative target
        before = self.tree()
        cases = (
            ("abs missing ancestor", dict(skills=str(d / "branch"))),
            ("rel missing ancestor", dict(skills="./data/branch")),
            ("rel trailing slash", dict(skills="data/branch/")),
            ("dotdot missing ancestor", dict(skills=str(d / "x" / ".." / "branch"))),
            ("case alias", dict(skills=str(d / "BRANCH"))),
            ("equals missing output", dict(skills=str(d / "branch" / "out"))),
            ("descendant of missing output", dict(skills=str(d / "branch" / "out" / "s"))),
            ("dangling abs link", dict(skills=str(d / "lnk"))),
            ("dangling rel link", dict(skills=str(d / "rlnk"))),
            (".env abs", dict(skills=str(d / "branch"), via="env")),
            (".env rel", dict(skills="./data/branch", via="env")),
            (".env literal $DATA_DIR", dict(skills='"$DATA_DIR/branch"', via="env")),
            ("dryrun", dict(skills=str(d / "branch"), args=("--dryrun", "step3-summary"))),
            ("input dir under missing ancestor", dict(skills=str(d / "branch"), INPUT_DIR="branch/in")),
        )
        for name, kw in cases:
            with self.subTest(name):
                r = self.go(**kw)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("overlaps OUTPUT_DIR", r.stderr)
                self.assertEqual(self.tree(), before)  # no branch, input, output or .logs created
                self.assertIsNone(self.run_call())

    def test_missing_disjoint_sibling_warns_without_mount(self):
        for skills in (str(self.data / "other"), "./data/other", str(self.data / "branch" / "outer")):
            with self.subTest(skills):
                self.argv.unlink(missing_ok=True)
                r = self.go(skills)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("LOCAL_SKILLS_DIR specified but not found", r.stdout)
                call = self.run_call()
                self.assertIsNotNone(call)
                self.assertFalse([a for a in call if ":/skills" in a or ".opencode/skills" in a])

    def test_existing_disjoint_skills_mounted_exactly_and_dryrun_is_cheap(self):
        sk = self.tmp / "skills"; sk.mkdir()
        r = self.go(str(sk))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = self.run_call()
        for dest in ("/workspace/.opencode/skills", "/skills"):
            self.assertEqual(call[call.index(f"{sk}:{dest}") - 1], "-v")
        self.argv.unlink()
        runs = self.runs()
        r = self.go(str(sk), args=("--dryrun", "step3-summary"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"{sk}:/skills".replace(" ", "\\ "), r.stdout)  # dry-run shell-quotes spaces
        self.assertIsNone(self.run_call())
        self.assertEqual(self.runs(), runs)  # dry-run creates no private log


class DirectHeaders(Base):
    def test_header_matches_orchestrator_stage_names(self):
        cases = (
            (("step0-extraction",), "stage0.log", "Stage 0: Policy Extraction"),
            (("step1-requirement", "--goal-file", "goals/goal-001.txt"), "stage1_0001.log", "Stage 1: Requirement (goal-001)"),
            (("step2-generation", "--policy-dir", "my-policy"), "stage2_0001.log", "Stage 2: Generation (my-policy)"),
            (("step3-summary",), "stage3.log", "Stage 3: Summary Generation"),
            (("step4-validation-fixtures", "--policy-dir", "my-policy"), "stage4_0001.log", "Stage 4: Fixtures (my-policy)"),
        )
        (self.data / "input").mkdir(); (self.data / "input" / "policy_goal.txt").write_text("x")
        for args, name, header in cases:
            before = set(self.runs())
            r = self.step("--no-confirm", *args, PIPELINE_LOG_CAPTURED="")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            (run,) = set(self.runs()) - before
            lines = (run / name).read_text().splitlines()
            self.assertEqual(lines[1], header)
            self.assertIn(f"Direct step: {args[0]}", lines[:5])
            self.assertIn("Return code: 0", lines)


if __name__ == "__main__":
    unittest.main()
