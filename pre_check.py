#!/usr/bin/env python3
# Copyright IBM Corp. 2026

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
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


def check_docker_daemon() -> bool:
    """Check if Docker daemon is running"""
    try:
        result = subprocess.run(
            ["docker", "ps"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def docker_image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def check_mcp_server_health(image: str) -> dict:
    """Check if terraform-mcp-server is running and healthy using Docker container"""
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm", "--entrypoint", "",
                image,
                "curl", "-s", "--connect-timeout", "3", "--max-time", "5",
                "http://host.docker.internal:8500/health"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            try:
                data = json.loads(result.stdout)
                return {
                    "available": True,
                    "status": data.get("status"),
                    "service": data.get("service"),
                }
            except json.JSONDecodeError:
                return {
                    "available": False,
                    "error": f"Invalid JSON response: {result.stdout[:100]}",
                }
        else:
            return {
                "available": False,
                "error": f"curl failed: {result.stderr[:200] if result.stderr else 'no output'}",
            }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "error": "Connection timeout",
        }
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
        }


def find_terraform_pac_agent_image() -> dict:
    """Find terraform-pac-agent image with any tag"""
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"found": False, "images": []}
        
        # Match terraform-pac-agent images with any tag
        pattern = re.compile(r".*terraform-pac-agent.*:.*")
        images = [
            line.strip() for line in result.stdout.splitlines()
            if pattern.match(line.strip())
        ]
        
        return {
            "found": len(images) > 0,
            "images": images,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"found": False, "images": []}


def get_binary_arch(binary_path: str) -> tuple[str | None, str | None]:
    """Get architecture and OS of a binary via `file -b`.
    Returns (arch, os) where arch is 'arm64'/'amd64'/None and os is 'linux'/'macos'/None."""
    import shutil
    if not shutil.which("file"):
        return None, None
    try:
        result = subprocess.run(
            ["file", "-b", binary_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None, None
        output = result.stdout.lower()
        if "aarch64" in output or "arm64" in output:
            arch = "arm64"
        elif "x86-64" in output or "x86_64" in output:
            arch = "amd64"
        else:
            arch = None
        if "mach-o" in output:
            os_name = "macos"
        elif "elf" in output:
            os_name = "linux"
        else:
            os_name = None
        return arch, os_name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None


def get_image_arch(image: str) -> tuple[str | None, str | None]:
    """Get architecture and OS of a Docker image via `docker image inspect`.
    Returns (arch, os) where arch is e.g. 'arm64'/'amd64'/None and os is 'linux'/'macos'/None."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Architecture}}|{{.Os}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None, None
        parts = result.stdout.strip().split("|")
        arch = parts[0] if parts[0] else None
        raw_os = parts[1] if len(parts) > 1 and parts[1] else None
        if raw_os == "linux":
            os_name = "linux"
        elif raw_os in ("darwin", "macos"):
            os_name = "macos"
        else:
            os_name = raw_os or None
        return arch, os_name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None


def print_interactive_report(result: dict) -> None:
    """Print user-friendly interactive report"""
    print("\n" + "=" * 70)
    print("  Terraform PaC Agent - Pre-flight Check Report")
    print("=" * 70 + "\n")
    
    # Overall status
    if result["ok"]:
        print("✅ Status: READY")
    else:
        print("❌ Status: NOT READY")
    print()
    
    # Check items with status
    checks = result.get("checks", {})
    
    print("📋 CHECK ITEMS:")
    print()
    
    # 1. Docker daemon (subcommand: docker)
    if "docker_daemon_running" in checks:
        status = "🟢" if checks["docker_daemon_running"] else "🔴"
        status_text = "Running" if checks["docker_daemon_running"] else "Not running"
        print(f"   {status} docker    : Docker Daemon - {status_text}")
    
    # 2. Environment variables (subcommand: env)
    if "missing_keys" in checks or "auth_provider_conflict" in checks:
        has_conflict = checks.get("auth_provider_conflict", False)
        missing_keys = checks.get("missing_keys", [])
        
        if has_conflict:
            print(f"   🔴 env        : Environment Variables - Authentication provider conflict")
            print(f"                   Both LiteLLM and GitHub Copilot are configured")
            print(f"                   Please choose only ONE authentication provider")
        elif missing_keys:
            print(f"   🔴 env        : Environment Variables - Missing {len(missing_keys)} keys")
            for key in missing_keys:
                print(f"                   - {key}")
        else:
            print(f"   🟢 env        : Environment Variables - All required keys present")
    
    # 3. Binaries (subcommand: binaries)
    if "binaries" in checks:
        bins = checks["binaries"]
        tf_ok = bins.get("terraform_exists") and bins.get("terraform_executable")
        tfp_ok = bins.get("tfpolicy_exists") and bins.get("tfpolicy_executable")
        tf_arch_ok = bins.get("terraform_arch_match")   # None = skipped, True/False = checked
        tfp_arch_ok = bins.get("tfpolicy_arch_match")
        tf_os_ok = bins.get("terraform_os_match")
        tfp_os_ok = bins.get("tfpolicy_os_match")

        # Overall binaries status (arch/OS mismatch is also a hard error)
        binaries_ok = (
            tf_ok and tfp_ok
            and tf_arch_ok is not False and tfp_arch_ok is not False
            and tf_os_ok is not False and tfp_os_ok is not False
        )
        status = "🟢" if binaries_ok else "🔴"

        if binaries_ok:
            image_arch = bins.get("image_arch")
            image_os = bins.get("image_os")
            note_parts = [p for p in [image_arch, image_os] if p]
            note = f" ({', '.join(note_parts)})" if note_parts else ""
            print(f"   {status} binaries  : Terraform & TFPolicy - OK{note}")
        else:
            print(f"   {status} binaries  : Terraform & TFPolicy - Issues found")
            if not tf_ok:
                print(f"                   - Terraform: Missing or not executable")
            if not tfp_ok:
                print(f"                   - TFPolicy: Missing or not executable")
            if tf_arch_ok is False:
                print(f"                   - Terraform: arch mismatch"
                      f" (binary={bins.get('terraform_arch')}, image={bins.get('image_arch')})")
            if tf_os_ok is False:
                print(f"                   - Terraform: OS mismatch"
                      f" (binary={bins.get('terraform_os')}, image={bins.get('image_os')})")
            if tfp_arch_ok is False:
                print(f"                   - TFPolicy: arch mismatch"
                      f" (binary={bins.get('tfpolicy_arch')}, image={bins.get('image_arch')})")
            if tfp_os_ok is False:
                print(f"                   - TFPolicy: OS mismatch"
                      f" (binary={bins.get('tfpolicy_os')}, image={bins.get('image_os')})")
    
    # 4. Input file (subcommand: input)
    if "input_file_exists" in checks:
        has_external_repo = "external_repo_dir" in checks
        input_exists = checks["input_file_exists"]
        
        if has_external_repo and not input_exists:
            # External repo configured but input file missing - this is OK for 'run.sh external'
            status = "⚠️"
            status_text = "Not found (OK for 'run.sh external', required for 'run.sh local')"
        else:
            status = "🟢" if input_exists else "🔴"
            status_text = "Found" if input_exists else "Not found"
        
        print(f"   {status} input     : Input File - {status_text}")
        if "input_file" in checks:
            print(f"                   Path: {checks['input_file']}")
        if has_external_repo:
            print(f"                   External Repo: {checks['external_repo_dir']}")
    
    # 5. Docker image (subcommand: image)
    if "docker_image_exists" in checks:
        status = "🟢" if checks["docker_image_exists"] else "🔴"
        status_text = "Found" if checks["docker_image_exists"] else "Not found"
        print(f"   {status} image     : Docker Image - {status_text}")
        if "docker_image" in checks:
            print(f"                   Image: {checks['docker_image']}")
        
        # Show available alternatives
        if not checks["docker_image_exists"] and "terraform_pac_agent_images" in checks:
            pac_images = checks["terraform_pac_agent_images"]
            if pac_images.get("found"):
                print(f"                   Available alternatives: {len(pac_images.get('images', []))} image(s)")
                for img in pac_images.get("images", [])[:3]:
                    print(f"                     - {img}")
    
    # 6. MCP Server (subcommand: mcp)
    if "mcp_server" in checks:
        mcp = checks["mcp_server"]
        status = "🟢" if mcp.get("available") else "🔴"
        status_text = "Available" if mcp.get("available") else "Not available (required)"
        print(f"   {status} mcp       : MCP Server - {status_text}")
        
        if mcp.get("available"):
            if "service" in mcp:
                print(f"                   Service: {mcp['service']}")
        else:
            if "error" in mcp:
                print(f"                   Error: {mcp['error']}")
            if "mcp_check_image" in checks:
                print(f"                   Checked using: {checks['mcp_check_image']}")
            print(f"                   Help: Start MCP server with:")
            print(f"                         docker run -d --name terraform-mcp-server \\")
            print(f"                           -p 8500:8080 \\")
            print(f"                           -e TRANSPORT_MODE=streamable-http \\")
            print(f"                           -e TRANSPORT_HOST=0.0.0.0 \\")
            print(f"                           -e MCP_SESSION_MODE=stateless \\")
            print(f"                           hashicorp/terraform-mcp-server:1.1.0")
    
    # 7. Policy Database (subcommand: database)
    if "policy_db_configured" in checks:
        configured = checks.get("policy_db_configured", False)
        exists = checks.get("policy_db_exists", False)
        
        if configured and exists:
            status = "🟢"
            status_text = "Configured in .env file and exists"
        elif configured and not exists:
            status = "🔴"
            status_text = "Configured in .env file but file not found"
        else:
            status = "🔴"
            status_text = "Not configured in .env file"
        
        print(f"   {status} database  : Policy Database - {status_text}")
        if "policy_db" in checks:
            print(f"                   Path: {checks['policy_db']}")

    # 8. Output directory (subcommand: output)
    if "output_dir" in checks:
        is_empty = checks.get("output_dir_empty", False)
        if is_empty:
            status = "🟢"
            status_text = "Empty (OK)"
        else:
            status = "🔴"
            status_text = "Not empty — must clean up before full pipeline"
        print(f"   {status} output    : Output Directory - {status_text}")
        print(f"                   Path: {checks['output_dir']}")

    # 9. Local mode (subcommand: local)
    if "is_local_mode" in checks:
        is_local = checks["is_local_mode"]
        status = "🟢" if is_local else "🔴"
        status_text = "EXTERNAL_REPO_DIR is not set" if is_local else "EXTERNAL_REPO_DIR is set (not local mode)"
        print(f"   {status} local     : Local Mode - {status_text}")

    print()
    
    # Errors summary
    if result["errors"]:
        print("🚫 ERRORS (must fix):")
        for i, error in enumerate(result["errors"], 1):
            print(f"   {i}. {error}")
        print()
    
    # Warnings summary
    if result["warnings"]:
        print("⚠️  WARNINGS (recommended to fix):")
        for i, warning in enumerate(result["warnings"], 1):
            print(f"   {i}. {warning}")
        print()
    
    print("=" * 70)
    
    if result["ok"]:
        print("✅ All critical checks passed. Ready to run pipeline.")
    else:
        print("❌ Please fix the errors above before running the pipeline.")
    
    print("=" * 70 + "\n")


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

    # Parse command line arguments
    output_format = "interactive"  # default
    check_targets = []  # list of checks to run
    
    valid_subcommands = ["all", "docker", "env", "binaries", "input", "image", "mcp", "database", "output", "local"]
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--summarize-output":
            env = parse_env_file(env_path) if env_path.exists() else {}
            data_dir = resolve_path(repo_root, env.get("DATA_DIR", "./data"))
            output_dir = data_dir / env.get("OUTPUT_DIR", "output")
            print(json.dumps(summarize_output(output_dir), indent=2))
            return 0
        elif sys.argv[1] in ["--help", "-h"]:
            print("Usage: pre_check.py [SUBCOMMAND...] [--json]")
            print()
            print("Subcommands (can specify multiple):")
            print("  all                 Run all checks (default)")
            print("  docker              Check Docker daemon")
            print("  env                 Check environment variables")
            print("  binaries            Check terraform/tfpolicy binaries")
            print("  input               Check input file")
            print("  image               Check Docker image")
            print("  mcp                 Check MCP server")
            print("  database            Check policy database")
            print("  output              Check OUTPUT_DIR is empty")
            print("  local               Check EXTERNAL_REPO_DIR is not set (local mode only)")
            print()
            print("Options:")
            print("  --json              Output in JSON format (for automation)")
            print("  --summarize-output  Summarize pipeline output logs")
            print("  --help, -h          Show this help message")
            print()
            print("Examples:")
            print("  pre_check.py                           # Run all checks (interactive)")
            print("  pre_check.py --json                    # Run all checks (JSON)")
            print("  pre_check.py docker                    # Check Docker daemon only")
            print("  pre_check.py docker binaries mcp       # Check multiple items")
            print("  pre_check.py mcp --json                # Check MCP server (JSON)")
            return 0
        
        # Parse arguments
        for arg in sys.argv[1:]:
            if arg == "--json":
                output_format = "json"
            elif arg in valid_subcommands:
                check_targets.append(arg)
    
    # Default to "all" if no subcommands specified
    if not check_targets:
        check_targets = ["all"]
    
    # If "all" is in the list, just use "all"
    if "all" in check_targets:
        check_targets = ["all"]

    result = {
        "ok": True,
        "checks": {},
        "errors": [],
        "warnings": [],
    }

    # Check Docker daemon first (required for most checks)
    if "all" in check_targets or "docker" in check_targets:
        docker_daemon_running = check_docker_daemon()
        result["checks"]["docker_daemon_running"] = docker_daemon_running
        if not docker_daemon_running:
            result["ok"] = False
            result["errors"].append("Docker daemon is not running or not accessible")
            # Early exit if only checking docker
            if check_targets == ["docker"]:
                if output_format == "json":
                    print(json.dumps(result, indent=2))
                else:
                    print_interactive_report(result)
                return 1

    # Early exit for docker-only check
    if check_targets == ["docker"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Load .env for other checks
    if not env_path.exists():
        result["ok"] = False
        result["errors"].append(".env not found")
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 1

    env = parse_env_file(env_path)
    auth_provider = env.get("AUTH_PROVIDER", "litellm")

    # Environment variables check
    if "all" in check_targets or "env" in check_targets:
        required = ["MODEL_NAME", "IMAGE_NAME", "IMAGE_TAG", "DATA_DIR", "INPUT_DIR", "INPUT_FILE", "OUTPUT_DIR", "TERRAFORM_BINARY_PATH", "TFPOLICY_BINARY_PATH"]
        
        # Check for conflicting auth providers
        has_litellm = env.get("MODEL_BASE_URL") or env.get("MODEL_API_KEY")
        has_github_copilot = env.get("GITHUB_COPILOT_ACCESS_TOKEN")
        
        result["checks"]["auth_provider_conflict"] = has_litellm and has_github_copilot
        
        if has_litellm and has_github_copilot:
            result["ok"] = False
            result["errors"].append("Conflicting authentication providers: both LiteLLM and GitHub Copilot are configured. Please choose only ONE.")
        
        if auth_provider == "github-copilot":
            required.extend(["GITHUB_COPILOT_ACCESS_TOKEN"])
        else:
            required.extend(["MODEL_BASE_URL", "MODEL_API_KEY"])

        missing = [key for key in required if not env.get(key)]
        result["checks"]["missing_keys"] = missing
        if missing:
            result["ok"] = False
            result["errors"].append(f"missing env keys: {', '.join(missing)}")

    # Early exit for env-only check
    if check_targets == ["env"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Resolve paths for other checks
    terraform_path = resolve_path(repo_root, env.get("TERRAFORM_BINARY_PATH", ""))
    tfpolicy_path = resolve_path(repo_root, env.get("TFPOLICY_BINARY_PATH", ""))
    data_dir = resolve_path(repo_root, env.get("DATA_DIR", "./data"))
    input_dir = data_dir / env.get("INPUT_DIR", "input")
    input_file = input_dir / env.get("INPUT_FILE", "policy_goal.txt")
    output_dir = data_dir / env.get("OUTPUT_DIR", "output")

    # Binaries check
    if "all" in check_targets or "binaries" in check_targets:
        image = f"{env.get('IMAGE_NAME', '')}:{env.get('IMAGE_TAG', '')}"
        image_arch, image_os = get_image_arch(image) if env.get("IMAGE_NAME") and env.get("IMAGE_TAG") else (None, None)

        tf_exists = terraform_path.exists()
        tf_arch, tf_os = get_binary_arch(str(terraform_path)) if tf_exists else (None, None)
        tf_arch_match = (tf_arch == image_arch) if (tf_arch and image_arch) else None
        tf_os_match = (tf_os == image_os) if (tf_os and image_os) else None

        tfp_exists = tfpolicy_path.exists()
        tfp_arch, tfp_os = get_binary_arch(str(tfpolicy_path)) if tfp_exists else (None, None)
        tfp_arch_match = (tfp_arch == image_arch) if (tfp_arch and image_arch) else None
        tfp_os_match = (tfp_os == image_os) if (tfp_os and image_os) else None

        binary_checks = {
            "terraform_exists": tf_exists,
            "terraform_executable": os.access(terraform_path, os.X_OK) if tf_exists else False,
            "terraform_arch": tf_arch,
            "terraform_arch_match": tf_arch_match,
            "terraform_os": tf_os,
            "terraform_os_match": tf_os_match,
            "tfpolicy_exists": tfp_exists,
            "tfpolicy_executable": os.access(tfpolicy_path, os.X_OK) if tfp_exists else False,
            "tfpolicy_arch": tfp_arch,
            "tfpolicy_arch_match": tfp_arch_match,
            "tfpolicy_os": tfp_os,
            "tfpolicy_os_match": tfp_os_match,
            "image_arch": image_arch,
            "image_os": image_os,
        }
        result["checks"]["binaries"] = binary_checks

        if not binary_checks["terraform_exists"]:
            result["ok"] = False
            result["errors"].append(f"terraform binary not found: {terraform_path}")
        elif not binary_checks["terraform_executable"]:
            result["ok"] = False
            result["errors"].append(f"terraform binary not executable: {terraform_path}")
        else:
            if tf_arch_match is False:
                result["ok"] = False
                result["errors"].append(
                    f"terraform binary arch mismatch: binary={tf_arch}, image={image_arch} ({image})"
                )
            if tf_os_match is False:
                result["ok"] = False
                result["errors"].append(
                    f"terraform binary OS mismatch: binary={tf_os}, image={image_os} ({image})"
                )

        if not binary_checks["tfpolicy_exists"]:
            result["ok"] = False
            result["errors"].append(f"tfpolicy binary not found: {tfpolicy_path}")
        elif not binary_checks["tfpolicy_executable"]:
            result["ok"] = False
            result["errors"].append(f"tfpolicy binary not executable: {tfpolicy_path}")
        else:
            if tfp_arch_match is False:
                result["ok"] = False
                result["errors"].append(
                    f"tfpolicy binary arch mismatch: binary={tfp_arch}, image={image_arch} ({image})"
                )
            if tfp_os_match is False:
                result["ok"] = False
                result["errors"].append(
                    f"tfpolicy binary OS mismatch: binary={tfp_os}, image={image_os} ({image})"
                )

    # Early exit for binaries-only check
    if check_targets == ["binaries"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Input file check
    # Note: Always check input file, but provide context about EXTERNAL_REPO_DIR
    external_repo_dir = env.get("EXTERNAL_REPO_DIR")
    
    if "all" in check_targets or "input" in check_targets:
        result["checks"]["input_file"] = str(input_file)
        result["checks"]["input_file_exists"] = input_file.exists()
        
        # Store external repo info for display
        if external_repo_dir:
            result["checks"]["external_repo_dir"] = external_repo_dir
        
        if not input_file.exists():
            # Only error if not in external repo mode
            if not external_repo_dir:
                result["ok"] = False
                result["errors"].append(f"input file not found: {input_file}")
            else:
                # Warning: input file missing but external repo is configured
                result["warnings"].append(f"input file not found: {input_file} (OK if using 'run.sh external', required for 'run.sh local')")

    # Early exit for input-only check
    if check_targets == ["input"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Docker image check
    if "all" in check_targets or "image" in check_targets:
        # Check for terraform-pac-agent image (any version)
        pac_agent_images = find_terraform_pac_agent_image()
        result["checks"]["terraform_pac_agent_images"] = pac_agent_images
        
        # Also check the specific image from .env
        image = f"{env.get('IMAGE_NAME', '')}:{env.get('IMAGE_TAG', '')}"
        result["checks"]["docker_image"] = image
        result["checks"]["docker_image_exists"] = docker_image_exists(image) if env.get("IMAGE_NAME") and env.get("IMAGE_TAG") else False
        
        if not result["checks"]["docker_image_exists"]:
            if pac_agent_images["found"]:
                result["warnings"].append(f"Specified image not found: {image}, but other terraform-pac-agent images are available: {', '.join(pac_agent_images['images'][:3])}")
            else:
                result["ok"] = False
                result["errors"].append(f"docker image not found: {image}")

    # Early exit for image-only check
    if check_targets == ["image"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # MCP server check
    if "all" in check_targets or "mcp" in check_targets:
        # Use the image from .env (required)
        image_name = env.get('IMAGE_NAME')
        image_tag = env.get('IMAGE_TAG')
        if not image_name or not image_tag:
            result["ok"] = False
            result["errors"].append("IMAGE_NAME and IMAGE_TAG must be set in .env for MCP check")
        else:
            check_image = f"{image_name}:{image_tag}"
            mcp_health = check_mcp_server_health(check_image)
            result["checks"]["mcp_server"] = mcp_health
            result["checks"]["mcp_check_image"] = check_image
            if not mcp_health["available"]:
                result["ok"] = False
                result["errors"].append(f"terraform-mcp-server is not accessible via {check_image} - {mcp_health.get('error', 'unknown error')}")

    # Early exit for mcp-only check
    if check_targets == ["mcp"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Database check
    if "all" in check_targets or "database" in check_targets:
        policy_db = env.get("POLICY_DB")
        
        if not policy_db:
            result["ok"] = False
            result["errors"].append("POLICY_DB environment variable is not set")
            result["checks"]["policy_db_configured"] = False
            result["checks"]["policy_db_exists"] = False
        else:
            result["checks"]["policy_db_configured"] = True
            result["checks"]["policy_db"] = policy_db
            
            # Check if the database file exists
            policy_db_path = resolve_path(repo_root, policy_db)
            db_exists = policy_db_path.exists()
            result["checks"]["policy_db_exists"] = db_exists
            
            if not db_exists:
                result["ok"] = False
                result["errors"].append(f"Policy database file not found: {policy_db}")

    # Early exit for database-only check
    if check_targets == ["database"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Output directory check
    if "all" in check_targets or "output" in check_targets:
        result["checks"]["output_dir"] = str(output_dir)
        is_empty = not (output_dir.exists() and any(output_dir.iterdir()))
        result["checks"]["output_dir_empty"] = is_empty
        if not is_empty:
            result["ok"] = False
            result["errors"].append(
                f"OUTPUT_DIR is not empty: {output_dir}\n"
                "   Fix: delete its contents or set a new OUTPUT_DIR in .env"
            )

    # Early exit for output-only check
    if check_targets == ["output"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Local mode check
    if "all" in check_targets or "local" in check_targets:
        external_repo_dir_val = env.get("EXTERNAL_REPO_DIR")
        is_local = not bool(external_repo_dir_val)
        result["checks"]["is_local_mode"] = is_local
        if not is_local:
            result["ok"] = False
            result["errors"].append(
                f"EXTERNAL_REPO_DIR is set ({external_repo_dir_val}); "
                "remove it from .env to use local mode"
            )

    # Early exit for local-only check
    if check_targets == ["local"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Output based on format
    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print_interactive_report(result)
    
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

# Made with Bob
