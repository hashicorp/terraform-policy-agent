#!/usr/bin/env python3
"""
set_env_for_external_mode.py

After `preprocess` phase, resolve DATA_DIR, INPUT_DIR, OUTPUT_DIR from the latest
timestamped directories and write them back into the .env file.

Usage:
    python3 skills/tfpac-run/scripts/set_env_for_external_mode.py .env

Output (stdout):
    JSON with resolved values and output_dir path for log redirection.

Side effect:
    Updates DATA_DIR, INPUT_DIR, OUTPUT_DIR, INPUT_FILE in the .env file.
"""

import json
import re
import sys
from pathlib import Path


def parse_env_file(path: Path) -> dict:
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("  #")[0].split("\t#")[0].strip()
        data[key.strip()] = value
    return data


def update_env_file(path: Path, updates: dict) -> None:
    """Write updated keys back into .env, adding them if not present."""
    lines = path.read_text(encoding="utf-8").splitlines()
    updated_keys = set()

    # Update existing lines
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append keys that were not already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def find_latest(data_dir: Path, prefix: str) -> str | None:
    """Return the basename of the most recently modified directory matching prefix-*."""
    candidates = sorted(
        [d for d in data_dir.iterdir() if d.is_dir() and d.name.startswith(prefix + "-")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return candidates[0].name if candidates else None


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 set_env_for_external_mode.py <env_file>", file=sys.stderr)
        return 1

    env_path = Path(sys.argv[1])
    if not env_path.exists():
        print(json.dumps({"ok": False, "error": f".env not found: {env_path}"}))
        return 1

    env = parse_env_file(env_path)
    data_dir_str = env.get("DATA_DIR", "./data")
    data_dir = Path(data_dir_str).resolve()

    if not data_dir.exists():
        print(json.dumps({"ok": False, "error": f"DATA_DIR not found: {data_dir}"}))
        return 1

    input_dir = find_latest(data_dir, "input")
    output_dir = find_latest(data_dir, "output")

    if not input_dir or not output_dir:
        print(json.dumps({
            "ok": False,
            "error": "No input-* or output-* directories found. Run preprocess first.",
            "data_dir": str(data_dir),
        }))
        return 1

    updates = {
        "DATA_DIR": str(data_dir),
        "INPUT_DIR": input_dir,
        "OUTPUT_DIR": output_dir,
        "INPUT_FILE": "policy_goal.txt",
    }
    update_env_file(env_path, updates)

    output_dir_abs = data_dir / output_dir
    (data_dir / "log").mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "ok": True,
        "DATA_DIR": str(data_dir),
        "INPUT_DIR": input_dir,
        "OUTPUT_DIR": output_dir,
        "INPUT_FILE": "policy_goal.txt",
        "output_dir_abs": str(output_dir_abs),
        "log_dir": str(data_dir / "log"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Made with Bob
