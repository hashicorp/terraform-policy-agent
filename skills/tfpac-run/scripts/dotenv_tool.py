#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def should_mask_value(key: str) -> bool:
    """Determine if a value should be masked based on the key name."""
    # Explicit list of fields that should be masked
    sensitive_fields = {
        'MODEL_API_KEY',
        'GITHUB_COPILOT_ACCESS_TOKEN',
        'GITHUB_COPILOT_REFRESH_TOKEN',
    }
    return key in sensitive_fields


def mask_value(value: str) -> str:
    """Mask sensitive values, showing only first 4 and last 4 characters."""
    if not value or len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


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
    
    # Mask sensitive values for output
    masked_values = {}
    for key, value in parsed.items():
        if should_mask_value(key):
            masked_values[key] = mask_value(value)
        else:
            masked_values[key] = value
    
    print(json.dumps({
        "ok": True,
        "path": str(env_path),
        "keys": sorted(parsed.keys()),
        "values": masked_values,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
