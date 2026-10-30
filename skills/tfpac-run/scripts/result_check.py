#!/usr/bin/env python3
import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


def strip_inline_comment(value: str) -> str:
    """Drop a trailing `# ...` comment the way `set -a; . ./.env` does.

    The shell scripts read .env with `source`, so this must agree with bash on where a
    value ends: a comment starts at a `#` that is outside quotes and preceded by
    whitespace (one space is enough). `IMAGE_TAG=v1#2` and `FRAGMENT=#anchor` are kept
    as-is, and a `#` inside quotes is data.
    """
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and i > 0 and value[i - 1] in " \t":
            return value[:i]
    return value



def parse_env_file(path: Path) -> dict:
    data = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = strip_inline_comment(value).strip()
    return data


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def is_safe_dir(path: Path) -> bool:
    """Real (non-symlink) directory owned by us and not group/other-writable."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid() and not st.st_mode & 0o022


def find_log_dir(data_dir: Path, explicit: Path = None):
    """Return (private run dir or None, error or None). Default: newest valid run with stage logs;
    pass --log-dir to select an exact run."""
    if explicit is not None:
        if not is_safe_dir(explicit):
            return None, f"--log-dir is not a real directory owned by you with safe permissions: {explicit}"
        if not stage_logs(explicit, "stage*.log"):
            return None, f"--log-dir contains no regular stage*.log files: {explicit}"
        return explicit, None
    root = data_dir / ".logs"
    if not is_safe_dir(root):
        return None, f"no safe private log root at {root} (missing, symlink, wrong owner or unsafe permissions)"
    runs = [p for p in root.glob("run-*") if is_safe_dir(p) and stage_logs(p, "stage*.log")]
    if not runs:
        return None, f"no valid run-* directories with stage logs under {root}"
    return max(runs, key=lambda p: os.lstat(p).st_mtime), None


def stage_logs(log_dir: Path, pattern: str) -> list:
    """Regular, non-symlink log files only."""
    return sorted(
        str(p) for p in log_dir.glob(pattern)
        if stat.S_ISREG(os.lstat(p).st_mode)
    )


def summarize_output(output_dir: Path, log_dir: Path = None, log_error: str = None) -> dict:
    summary = {
        "output_dir_exists": output_dir.exists(),
        "summary_md_exists": (output_dir / "summary.md").exists(),
        "summary_json_exists": (output_dir / "summary.json").exists(),
        "log_dir": str(log_dir) if log_dir else None,
        "log_error": log_error,
        "stage0_log_exists": False,
        "stage3_log_exists": False,
        "goal_stage1_logs": [],
        "policy_stage2_logs": [],
        "policy_stage4_logs": [],
        "policy_dirs": sorted(
            p.name for p in output_dir.iterdir()
            if p.is_dir() and p.name != "goals"
        ) if output_dir.exists() else [],
        "error_hits": [],
    }

    candidate_logs = []
    if log_dir:
        summary["stage0_log_exists"] = bool(stage_logs(log_dir, "stage0.log"))
        summary["stage3_log_exists"] = bool(stage_logs(log_dir, "stage3*.log"))
        summary["goal_stage1_logs"] = stage_logs(log_dir, "stage1_*.log")
        summary["policy_stage2_logs"] = stage_logs(log_dir, "stage2_*.log")
        summary["policy_stage4_logs"] = stage_logs(log_dir, "stage4_*.log")
        candidate_logs = (stage_logs(log_dir, "stage0*.log") + stage_logs(log_dir, "stage3*.log")
                          + summary["goal_stage1_logs"] + summary["policy_stage2_logs"]
                          + summary["policy_stage4_logs"])

    patterns = ["ERROR", "Error", "failed", "timed out", "Traceback"]
    for log_file in candidate_logs:
        try:
            text = Path(log_file).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in patterns:
            if pattern in text:
                summary["error_hits"].append({
                    "file": str(log_file),
                    "pattern": pattern,
                })
                break

    return summary


def main() -> int:
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Terraform PAC result-check tool")

    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        metavar="PATH",
        help="Summarize pipeline output in this path."
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Exact private run directory (DATA_DIR/.logs/run-*). Default: newest valid run, "
             "which may be a later --step run."
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    env_path = repo_root / ".env"
    env = parse_env_file(env_path) if env_path.exists() else {}
    data_dir = resolve_path(repo_root, env.get("DATA_DIR", "./data"))

    if args.path:
        output_dir = data_dir / args.path
    else:
        output_dir = data_dir / env.get("OUTPUT_DIR", "output")
    
    log_dir, log_error = find_log_dir(data_dir, Path(os.path.abspath(args.log_dir)) if args.log_dir else None)
    print(json.dumps(summarize_output(output_dir, log_dir, log_error), indent=2))
    return 0 if log_dir else 1

if __name__ == "__main__":
    raise SystemExit(main())
