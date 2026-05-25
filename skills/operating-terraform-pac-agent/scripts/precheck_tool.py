#!/usr/bin/env python3
import json
import os
import subprocess
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


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def docker_image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


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
    repo_root = Path.cwd()
    env_path = repo_root / ".env"

    if len(sys.argv) > 1 and sys.argv[1] == "--summarize-output":
        output_dir = repo_root / "data" / "output"
        print(json.dumps(summarize_output(output_dir), indent=2))
        return 0

    result = {
        "ok": True,
        "checks": {},
        "errors": [],
    }

    if not env_path.exists():
        result["ok"] = False
        result["errors"].append(".env not found")
        print(json.dumps(result, indent=2))
        return 1

    env = parse_env_file(env_path)
    auth_provider = env.get("AUTH_PROVIDER", "litellm")

    required = ["MODEL_NAME", "IMAGE_NAME", "IMAGE_TAG", "DATA_DIR", "INPUT_DIR", "INPUT_FILE", "OUTPUT_DIR", "TERRAFORM_BINARY_PATH", "TFPOLICY_BINARY_PATH"]
    if auth_provider == "github-copilot":
        required.extend(["GITHUB_COPILOT_ACCESS_TOKEN"])
    else:
        required.extend(["MODEL_BASE_URL", "MODEL_API_KEY"])

    missing = [key for key in required if not env.get(key)]
    result["checks"]["missing_keys"] = missing
    if missing:
        result["ok"] = False
        result["errors"].append(f"missing env keys: {', '.join(missing)}")

    terraform_path = resolve_path(repo_root, env.get("TERRAFORM_BINARY_PATH", ""))
    tfpolicy_path = resolve_path(repo_root, env.get("TFPOLICY_BINARY_PATH", ""))
    data_dir = resolve_path(repo_root, env.get("DATA_DIR", "./data"))
    input_dir = data_dir / env.get("INPUT_DIR", "input")
    input_file = input_dir / env.get("INPUT_FILE", "policy_goal.txt")
    output_dir = data_dir / env.get("OUTPUT_DIR", "output")

    binary_checks = {
        "terraform_exists": terraform_path.exists(),
        "terraform_executable": os.access(terraform_path, os.X_OK) if terraform_path.exists() else False,
        "tfpolicy_exists": tfpolicy_path.exists(),
        "tfpolicy_executable": os.access(tfpolicy_path, os.X_OK) if tfpolicy_path.exists() else False,
    }
    result["checks"]["binaries"] = binary_checks

    if not binary_checks["terraform_exists"]:
        result["ok"] = False
        result["errors"].append(f"terraform binary not found: {terraform_path}")
    elif not binary_checks["terraform_executable"]:
        result["ok"] = False
        result["errors"].append(f"terraform binary not executable: {terraform_path}")

    if not binary_checks["tfpolicy_exists"]:
        result["ok"] = False
        result["errors"].append(f"tfpolicy binary not found: {tfpolicy_path}")
    elif not binary_checks["tfpolicy_executable"]:
        result["ok"] = False
        result["errors"].append(f"tfpolicy binary not executable: {tfpolicy_path}")

    result["checks"]["input_file"] = str(input_file)
    result["checks"]["input_file_exists"] = input_file.exists()
    if not input_file.exists():
        result["ok"] = False
        result["errors"].append(f"input file not found: {input_file}")

    image = f"{env.get('IMAGE_NAME', '')}:{env.get('IMAGE_TAG', '')}"
    result["checks"]["docker_image"] = image
    result["checks"]["docker_image_exists"] = docker_image_exists(image) if env.get("IMAGE_NAME") and env.get("IMAGE_TAG") else False
    if not result["checks"]["docker_image_exists"]:
        result["ok"] = False
        result["errors"].append(f"docker image not found: {image}")

    result["checks"]["output_dir"] = str(output_dir)

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

# Made with Bob
