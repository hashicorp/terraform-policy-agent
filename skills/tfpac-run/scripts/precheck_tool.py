#!/usr/bin/env python3
import argparse
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
        value = value.split("  #")[0].split("\t#")[0].strip()
        data[key.strip()] = value
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
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Terraform PAC pre-check tool")
    parser.add_argument(
        "--workflow",
        choices=["generation", "generation_with_crawler", "conversion_local", "conversion_external"],
        help="Specify the workflow type to validate workflow-specific environment variables"
    )
    parser.add_argument(
        "--summarize-output",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Summarize pipeline output from data/output directory. Optionally specify a custom output directory path."
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    env_path = repo_root / ".env"

    # Handle --summarize-output mode
    if args.summarize_output is not None:
        env = parse_env_file(env_path) if env_path.exists() else {}
        data_dir = resolve_path(repo_root, env.get("DATA_DIR", "./data"))
        
        if args.summarize_output:
            # Custom path provided
            output_dir = data_dir / args.summarize_output
        else:
            # No path provided, use default
            output_dir = data_dir / env.get("OUTPUT_DIR", "output")
        
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

    # Base required variables for all workflows
    required = ["MODEL_NAME", "IMAGE_NAME", "IMAGE_TAG", "DATA_DIR", "INPUT_DIR", "INPUT_FILE", "OUTPUT_DIR", "TERRAFORM_BINARY_PATH", "TFPOLICY_BINARY_PATH"]

    # Add workflow-specific required variables based on --workflow argument
    if args.workflow == "generation":
        # Generate from Existing Database workflow - requires database configuration
        required.extend(["POLICY_DB"])
    elif args.workflow == "generation_with_crawler":
        # Generate with Crawler workflow - requires crawler configuration
        required.extend(["CRAWLER_IMAGE_NAME", "CRAWLER_IMAGE_TAG", "CRAWLER_TIMEOUT"])
    elif args.workflow == "conversion_external":
        # External Repository Integration workflow
        required.extend(["EXTERNAL_REPO_DIR"])
        # SENTINEL_HCL_PATH is optional
    elif args.workflow == "conversion_local":
        # Manual Data Directory Setup workflow
        # No additional required variables (uses standard data directory)
        pass
    # If args.workflow is None, check only base requirements

    # Add authentication-specific required variables
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
    input_dir_external = resolve_path(repo_root, env.get("EXTERNAL_REPO_DIR", "./data/input"))
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

    if args.workflow == "conversion_external":
        result["checks"]["input_dir_external"] = str(input_dir_external)
        result["checks"]["input_dir_external_exists"] = input_dir_external.exists()
        if not input_dir_external.exists():
            result["ok"] = False
            result["errors"].append(f"input external directory not found: {input_dir_external}")
    else:
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
