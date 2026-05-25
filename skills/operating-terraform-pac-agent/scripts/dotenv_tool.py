#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def parse_env_file(path: Path) -> dict:
    data = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 dotenv_tool.py <env_file>", file=sys.stderr)
        return 1

    env_path = Path(sys.argv[1])
    if not env_path.exists():
        print(json.dumps({
            "ok": False,
            "error": f"env file not found: {env_path}"
        }, indent=2))
        return 1

    parsed = parse_env_file(env_path)
    print(json.dumps({
        "ok": True,
        "path": str(env_path),
        "keys": sorted(parsed.keys()),
        "values": parsed,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Made with Bob
