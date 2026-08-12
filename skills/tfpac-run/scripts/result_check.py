#!/usr/bin/env python3
import argparse
import json
import os
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


def summarize_output(output_dir: Path) -> dict:
    summary = {
        "output_dir_exists": output_dir.exists(),
        "summary_md_exists": (output_dir / "summary.md").exists(),
        "summary_json_exists": (output_dir / "summary.json").exists(),
        "stage0_log_exists": (output_dir / "stage0_extraction.log").exists(),
        "stage3_log_exists": (output_dir / "stage3_summary.log").exists(),
        "goal_stage1_logs": sorted(str(p) for p in output_dir.glob("goals/*_stage1*.log")),
        "policy_stage2_logs": sorted(str(p) for p in output_dir.glob("*/stage2_generation*.log")),
        "policy_dirs": sorted(
            p.name for p in output_dir.iterdir()
            if p.is_dir() and p.name != "goals"
        ) if output_dir.exists() else [],
        "error_hits": [],
    }

    patterns = ["ERROR", "Error", "failed", "timed out", "Traceback"]
    candidate_logs = []
    if output_dir.exists():
        candidate_logs.extend(output_dir.glob("stage*.log"))
        candidate_logs.extend(output_dir.glob("goals/*.log"))
        candidate_logs.extend(output_dir.glob("*/stage2_generation*.log"))

    for log_file in candidate_logs:
        try:
            text = log_file.read_text(encoding="utf-8", errors="ignore")
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
    args = parser.parse_args()

    repo_root = Path.cwd()
    env_path = repo_root / ".env"
    env = parse_env_file(env_path) if env_path.exists() else {}
    data_dir = resolve_path(repo_root, env.get("DATA_DIR", "./data"))

    if args.path:
        output_dir = data_dir / args.path
    else:
        output_dir = data_dir / env.get("OUTPUT_DIR", "output")
    
    print(json.dumps(summarize_output(output_dir), indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

# Made with Bob
