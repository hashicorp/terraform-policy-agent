#!/usr/bin/env python3
# Copyright IBM Corp. 2026

import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


def strip_inline_comment(value: str) -> str:
    """Drop a trailing `# ...` comment the way `set -a; . ./.env` does.

    The shell scripts read .env with `source`, so this module must agree with bash on
    where a value ends. Bash starts a comment at a `#` that is outside quotes and
    preceded by whitespace; a single space is enough. So:

        DATA_DIR=./data  # note   -> ./data
        DATA_DIR=./data # note    -> ./data
        IMAGE_TAG=v1#2            -> v1#2      (no whitespace before #)
        FRAGMENT=#anchor          -> #anchor   (nothing precedes the #)
        EXTRA="a # b"  # note     -> "a # b"   (# inside quotes is data)
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


def unquote(value: str) -> str:
    """Strip one layer of surrounding quotes from a raw .env value.

    parse_env_file() returns the value verbatim, whereas the shell scripts get it via
    `source` and therefore see it already unquoted. Stripping here keeps both readers
    in agreement for values that must be quoted in .env (i.e. those containing spaces).
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def resolve_docker_cli(env: dict) -> str:
    """Resolve the container CLI to use: docker or podman.

    Priority: .env > environment variable > default (docker), matching run.sh.
    """
    return unquote(env.get("DOCKER_CLI") or "") or os.environ.get("DOCKER_CLI") or "docker"


def resolve_docker_run_extra_args(env: dict) -> list:
    """Resolve extra flags appended to container run commands.

    Same priority as resolve_docker_cli. Split with shlex so that a value such as
    '--security-opt label=disable' becomes two arguments.
    """
    value = unquote(env.get("DOCKER_RUN_EXTRA_ARGS") or "") or os.environ.get("DOCKER_RUN_EXTRA_ARGS") or ""
    return shlex.split(value)


def check_docker_daemon(docker_cli: str = "docker") -> bool:
    """Check if the container engine is running"""
    try:
        result = subprocess.run(
            [docker_cli, "ps"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def docker_image_exists(image: str, docker_cli: str = "docker") -> bool:
    try:
        result = subprocess.run(
            [docker_cli, "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def check_mcp_server_health(image: str, docker_cli: str = "docker", extra_args: list = None) -> dict:
    """Check if terraform-mcp-server is running and healthy using a container"""
    try:
        result = subprocess.run(
            [
                docker_cli, "run", "--rm", "--entrypoint", "",
                *(extra_args or []),
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


def find_terraform_pac_agent_image(docker_cli: str = "docker") -> dict:
    """Find terraform-pac-agent image with any tag"""
    try:
        result = subprocess.run(
            [docker_cli, "images", "--format", "{{.Repository}}:{{.Tag}}"],
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


def get_binary_arch_os(binary_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Get architecture and OS of a binary via `file -b`.
    Returns (arch, os) where arch is 'arm64'/'amd64'/'arm'/'386'/'s390x'/None
    and os is 'linux'/'macos'/'freebsd'/'openbsd'/'netbsd'/'solaris'/'windows'/None."""
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
        # arch — order matters: check 64-bit variants before 32-bit
        if "aarch64" in output or "arm64" in output:
            arch = "arm64"
        elif "x86-64" in output or "x86_64" in output:
            arch = "amd64"
        elif "s390" in output or "ibm s/390" in output:
            arch = "s390x"
        elif "arm" in output:
            arch = "arm"
        elif "intel 80386" in output or "i386" in output:
            arch = "386"
        else:
            arch = None
        # os — check specific BSDs/Solaris/Windows before generic ELF→linux
        if "mach-o" in output:
            os_name = "macos"
        elif "for ms windows" in output or "pe32" in output:
            os_name = "windows"
        elif "freebsd" in output:
            os_name = "freebsd"
        elif "openbsd" in output:
            os_name = "openbsd"
        elif "netbsd" in output:
            os_name = "netbsd"
        elif "ld.so.1" in output or "solaris" in output:
            os_name = "solaris"
        elif "elf" in output:
            os_name = "linux"
        else:
            os_name = None
        return arch, os_name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None


def get_image_arch_os(image: str, docker_cli: str = "docker") -> Tuple[Optional[str], Optional[str]]:
    """Get architecture and OS of a container image via `<cli> image inspect`.
    Returns (arch, os) where arch is 'arm64'/'amd64'/'arm'/'386'/'s390x'/None
    and os is 'linux'/'macos'/'windows'/'freebsd'/'openbsd'/'netbsd'/'solaris'/None."""
    try:
        result = subprocess.run(
            [docker_cli, "image", "inspect", image, "--format", "{{.Architecture}}|{{.Os}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None, None
        parts = result.stdout.strip().split("|")
        raw_arch = parts[0].strip() if parts[0].strip() else None
        raw_os   = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

        # arch — Docker inspect returns GOARCH values directly
        if raw_arch in ("arm64", "aarch64"):
            arch = "arm64"
        elif raw_arch == "amd64":
            arch = "amd64"
        elif raw_arch == "arm":
            arch = "arm"
        elif raw_arch == "386":
            arch = "386"
        elif raw_arch == "s390x":
            arch = "s390x"
        else:
            arch = raw_arch or None

        # os — Docker inspect returns GOOS values; normalise darwin→macos
        if raw_os in ("darwin", "macos"):
            os_name = "macos"
        elif raw_os == "linux":
            os_name = "linux"
        elif raw_os == "windows":
            os_name = "windows"
        elif raw_os == "freebsd":
            os_name = "freebsd"
        elif raw_os == "openbsd":
            os_name = "openbsd"
        elif raw_os == "netbsd":
            os_name = "netbsd"
        elif raw_os == "solaris":
            os_name = "solaris"
        else:
            os_name = raw_os or None

        return arch, os_name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None, None


def check_api_credentials(env: dict) -> dict:
    def http_error_detail(e: Exception) -> str:
        # Include the response body: it tells e.g. an invalid model from an expired token
        if isinstance(e, urllib.error.HTTPError):
            try:
                body = e.read().decode(errors="replace").strip()
            except Exception:
                body = ""
            return f"HTTP {e.code} {e.reason}" + (f": {body[:300]}" if body else "")
        return str(e)

    provider = env.get("AUTH_PROVIDER", "litellm").lower()

    if provider == "litellm":
        base_url = (env.get("MODEL_BASE_URL") or "").rstrip("/")
        api_key = env.get("MODEL_API_KEY", "")
        model_name = env.get("MODEL_NAME", "")
        if not base_url:
            return {"provider": provider, "ok": False, "error": "MODEL_BASE_URL is not set"}
        if not api_key:
            return {"provider": provider, "ok": False, "error": "MODEL_API_KEY is not set"}
        if not model_name:
            return {"provider": provider, "ok": False, "error": "MODEL_NAME is not set"}
        url = f"{base_url}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps({"model": model_name, "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return {"provider": provider, "ok": True}
        except Exception as e:
            return {"provider": provider, "ok": False, "error": http_error_detail(e)}

    elif provider == "github-copilot":
        access_token = env.get("GITHUB_COPILOT_ACCESS_TOKEN", "")
        model_name = env.get("MODEL_NAME", "claude-sonnet-4.6")
        if not access_token:
            return {"provider": provider, "ok": False, "error": "GITHUB_COPILOT_ACCESS_TOKEN is not set"}
        if not model_name:
            return {"provider": provider, "ok": False, "error": "MODEL_NAME is not set"}
        req = urllib.request.Request(
            "https://api.githubcopilot.com/chat/completions",
            data=json.dumps({"model": model_name, "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 1}).encode(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Openai-Intent": "conversation-edits",
                "Copilot-Integration-Id": "vscode-chat",
                "Editor-Version": "vscode/1.99.0",
                "User-Agent": "pre_check/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return {"provider": provider, "ok": True}
        except Exception as e:
            return {"provider": provider, "ok": False, "error": http_error_detail(e)}

    elif provider == "amazon-bedrock":
        bearer_token = env.get("MODEL_API_KEY", "")
        model_name = env.get("MODEL_NAME", "")
        if not bearer_token:
            return {"provider": provider, "ok": False, "error": "MODEL_API_KEY (Bedrock bearer token) is not set"}
        if not model_name:
            return {"provider": provider, "ok": False, "error": "MODEL_NAME is not set"}
        # Like OpenCode, retry with the "us." cross-region prefix when Bedrock rejects
        # a bare model ID for on-demand throughput (e.g. anthropic.claude-opus-4-5-...).
        candidates = [model_name]
        if model_name.split(".", 1)[0] not in ("global", "us", "eu", "jp", "apac", "au"):
            candidates.append(f"us.{model_name}")
        error = ""
        for candidate in candidates:
            url = f"https://bedrock-runtime.us-east-1.amazonaws.com/model/{candidate}/converse"
            req = urllib.request.Request(
                url,
                data=json.dumps({"messages": [{"role": "user", "content": [{"text": "Hello"}]}]}).encode(),
                headers={"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp.read()
                return {"provider": provider, "ok": True}
            except Exception as e:
                error = http_error_detail(e)
                if "inference profile" not in error:
                    break
        return {"provider": provider, "ok": False, "error": error}

    else:
        return {"provider": provider, "ok": False, "error": f"Unknown AUTH_PROVIDER: {provider!r}"}


# Characters that break shell scripts and Docker volume mounts
_PATH_UNSAFE_CHARS = " \t()[]{},'\"!;#$&*?<>|~`"


def check_working_directory_path(cwd: Path) -> bool:
    path_str = str(cwd)
    return not any(c in path_str for c in _PATH_UNSAFE_CHARS)


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
    docker_cli = result.get("docker_cli", "docker")

    print("📋 CHECK ITEMS:")
    print()

    # 1. Container engine (subcommand: docker)
    if "docker_daemon_running" in checks:
        status = "🟢" if checks["docker_daemon_running"] else "🔴"
        status_text = "Running" if checks["docker_daemon_running"] else "Not running"
        print(f"   {status} docker    : Container Engine ({docker_cli}) - {status_text}")
    
    # 2. Environment variables (subcommand: env)
    if "missing_keys" in checks or "auth_provider_conflict" in checks:
        has_conflict = checks.get("auth_provider_conflict", False)
        missing_keys = checks.get("missing_keys", [])
        
        if has_conflict:
            print(f"   🔴 env        : Environment Variables - Authentication provider conflict")
            print(f"                   Multiple providers are configured (LiteLLM / GitHub Copilot / Amazon Bedrock)")
            print(f"                   Please choose only ONE in .env")
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
    
    # 5. Container image (subcommand: image)
    if "docker_image_exists" in checks:
        status = "🟢" if checks["docker_image_exists"] else "🔴"
        status_text = "Found" if checks["docker_image_exists"] else "Not found"
        print(f"   {status} image     : Container Image - {status_text}")
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
            print(f"                         {docker_cli} run -d --name terraform-mcp-server \\")
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
        if is_local:
            status = "🟢"
            status_text = "EXTERNAL_REPO_DIR is not set"
        elif checks.get("local_mode_required"):
            status = "🔴"
            status_text = "EXTERNAL_REPO_DIR is set (not local mode)"
        else:
            # `all` run: external mode is a valid configuration, not a failure.
            status = "🟢"
            status_text = "EXTERNAL_REPO_DIR is set (external mode)"
        print(f"   {status} local     : Local Mode - {status_text}")

    # 10. External mode (subcommand: external)
    if "external_repo_dir_set" in checks:
        ext_set = checks["external_repo_dir_set"]
        ext_exists = checks.get("external_repo_dir_exists", False)
        ext_ok = ext_set and ext_exists
        status = "🟢" if ext_ok else "🔴"
        if not ext_set:
            status_text = "EXTERNAL_REPO_DIR is not set"
        elif not ext_exists:
            status_text = f"Directory not found: {checks.get('external_repo_dir', '')}"
        else:
            status_text = f"Set and exists: {checks.get('external_repo_dir', '')}"
        print(f"   {status} external  : External Mode - {status_text}")

    # 0. Working directory (subcommand: workdir)
    if "workdir_ok" in checks:
        status = "🟢" if checks["workdir_ok"] else "🔴"
        status_text = "OK" if checks["workdir_ok"] else "Contains unsafe characters"
        print(f"   {status} workdir   : Working Directory - {status_text}")
        print(f"                   Path: {checks['workdir_path']}")

    # 11. API credentials (subcommand: api)
    if "api_credentials" in checks:
        api = checks["api_credentials"]
        status = "🟢" if api.get("ok") else "🔴"
        provider_label = api.get("provider", "unknown")
        status_text = "Valid" if api.get("ok") else "Invalid"
        print(f"   {status} api       : API Credentials ({provider_label}) - {status_text}")
        if not api.get("ok") and "error" in api:
            print(f"                   Error: {api['error']}")

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


def main() -> int:
    repo_root = Path.cwd()
    env_path = repo_root / ".env"

    # The container CLI must be resolved before any container command runs, which is
    # earlier than the full .env load further below (the engine check runs first).
    # A missing .env is not fatal here: it is reported by the regular .env check.
    early_env = parse_env_file(env_path) if env_path.exists() else {}
    docker_cli = resolve_docker_cli(early_env)
    docker_run_extra_args = resolve_docker_run_extra_args(early_env)

    # Parse command line arguments
    output_format = "interactive"  # default
    check_targets = []  # list of checks to run
    use_tmp = False  # --tmp flag: read .env.tmp instead of .env

    valid_subcommands = ["all", "docker", "env", "binaries", "input", "image", "mcp", "database", "output", "local", "external", "api", "workdir"]
    
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--help", "-h"]:
            print("Usage: pre_check.py [SUBCOMMAND...] [--json] [--tmp]")
            print()
            print("Subcommands (can specify multiple):")
            print("  all                 Run all checks (default)")
            print("  workdir             Check working directory path for spaces / unsafe characters")
            print("  docker              Check container engine (docker or podman)")
            print("  env                 Check environment variables")
            print("  binaries            Check terraform/tfpolicy binaries")
            print("  input               Check input file")
            print("  image               Check container image")
            print("  mcp                 Check MCP server")
            # print("  database            Check policy database")
            print("  output              Check OUTPUT_DIR is empty")
            print("  local               Require local mode: fail if EXTERNAL_REPO_DIR is set")
            print("                      (`all` only reports the mode, it does not require it)")
            print("  external            Check EXTERNAL_REPO_DIR is set and directory exists")
            print("  api                 Validate API credentials via lightweight ping")
            print()
            print("Options:")
            print("  --json              Output in JSON format (for automation)")
            print("  --tmp               Read .env.tmp instead of .env")
            print("  --summarize-output  Summarize pipeline output logs")
            print("  --help, -h          Show this help message")
            print()
            print("Examples:")
            print("  pre_check.py                           # Run all checks (interactive)")
            print("  pre_check.py --json                    # Run all checks (JSON)")
            print("  pre_check.py docker                    # Check container engine only")
            print("  pre_check.py docker binaries mcp       # Check multiple items")
            print("  pre_check.py mcp --json                # Check MCP server (JSON)")
            print("  pre_check.py --tmp mcp                 # Check MCP server using .env.tmp")
            print("  pre_check.py workdir                   # Check working directory path only")
            return 0
        
        # Parse arguments
        for arg in sys.argv[1:]:
            if arg == "--json":
                output_format = "json"
            elif arg == "--tmp":
                use_tmp = True
            elif arg in valid_subcommands:
                check_targets.append(arg)
    
    # Default to "all" if no subcommands specified
    if not check_targets:
        check_targets = ["all"]
    
    # If "all" is in the list, just use "all"
    if "all" in check_targets:
        check_targets = ["all"]

    # Resolve which env file to use
    if use_tmp:
        env_path = repo_root / ".env.tmp"
        # Re-resolve docker_cli from .env.tmp if it exists
        if env_path.exists():
            tmp_env = parse_env_file(env_path)
            docker_cli = resolve_docker_cli(tmp_env)
            docker_run_extra_args = resolve_docker_run_extra_args(tmp_env)

    result = {
        "ok": True,
        "docker_cli": docker_cli,
        "checks": {},
        "errors": [],
        "warnings": [],
    }

    # Working directory check (runs first, no .env needed)
    if "all" in check_targets or "workdir" in check_targets:
        wd_ok = check_working_directory_path(repo_root)
        result["checks"]["workdir_ok"] = wd_ok
        result["checks"]["workdir_path"] = str(repo_root)
        if not wd_ok:
            result["ok"] = False
            result["errors"].append(
                f"Working directory path contains unsafe characters: {repo_root}\n"
                "   Fix: move project to a path with only letters, numbers, hyphens, "
                "and underscores, e.g. ~/terraform-policy-agent"
            )

    if check_targets == ["workdir"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # Check the container engine first (required for most checks)
    if "all" in check_targets or "docker" in check_targets:
        docker_daemon_running = check_docker_daemon(docker_cli)
        result["checks"]["docker_daemon_running"] = docker_daemon_running
        if not docker_daemon_running:
            result["ok"] = False
            result["errors"].append(
                f"{docker_cli} is not running or not accessible"
            )
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

    # Load env file for other checks
    env_file_name = env_path.name  # ".env" or ".env.tmp"
    if not env_path.exists():
        result["ok"] = False
        result["errors"].append(f"{env_file_name} not found")
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 1

    env = parse_env_file(env_path)
    auth_provider = env.get("AUTH_PROVIDER", "litellm")

    # Environment variables check
    if "all" in check_targets or "env" in check_targets:
        required = ["MODEL_NAME", "IMAGE_NAME", "IMAGE_TAG", "DATA_DIR", "TERRAFORM_BINARY_PATH", "TFPOLICY_BINARY_PATH"]
        
        # Check for conflicting auth providers
        # Detect which providers have credentials present
        has_litellm = bool(env.get("MODEL_BASE_URL") or (auth_provider == "litellm" and env.get("MODEL_API_KEY")))
        has_github_copilot = bool(env.get("GITHUB_COPILOT_ACCESS_TOKEN"))
        has_bedrock = auth_provider == "amazon-bedrock"

        active_providers = [p for p, active in [
            ("LiteLLM",        has_litellm),
            ("GitHub Copilot", has_github_copilot),
            ("Amazon Bedrock", has_bedrock),
        ] if active]

        auth_conflict = len(active_providers) > 1
        result["checks"]["auth_provider_conflict"] = auth_conflict

        if auth_conflict:
            result["ok"] = False
            result["errors"].append(
                f"Conflicting authentication providers: {' and '.join(active_providers)} are configured. "
                "Please choose only ONE in .env."
            )
        
        if auth_provider == "github-copilot":
            required.extend(["GITHUB_COPILOT_ACCESS_TOKEN"])
        elif auth_provider == "amazon-bedrock":
            required.extend(["MODEL_API_KEY"])
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
        image_arch, image_os = get_image_arch_os(image, docker_cli) if env.get("IMAGE_NAME") and env.get("IMAGE_TAG") else (None, None)

        tf_exists = terraform_path.exists()
        tf_arch, tf_os = get_binary_arch_os(str(terraform_path)) if tf_exists else (None, None)
        tf_arch_match = (tf_arch == image_arch) if (tf_arch and image_arch) else None
        tf_os_match = (tf_os == image_os) if (tf_os and image_os) else None

        tfp_exists = tfpolicy_path.exists()
        tfp_arch, tfp_os = get_binary_arch_os(str(tfpolicy_path)) if tfp_exists else (None, None)
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

    # Container image check
    if "all" in check_targets or "image" in check_targets:
        # Check for terraform-pac-agent image (any version)
        pac_agent_images = find_terraform_pac_agent_image(docker_cli)
        result["checks"]["terraform_pac_agent_images"] = pac_agent_images
        
        # Also check the specific image from .env
        image = f"{env.get('IMAGE_NAME', '')}:{env.get('IMAGE_TAG', '')}"
        result["checks"]["docker_image"] = image
        result["checks"]["docker_image_exists"] = docker_image_exists(image, docker_cli) if env.get("IMAGE_NAME") and env.get("IMAGE_TAG") else False
        
        if not result["checks"]["docker_image_exists"]:
            if pac_agent_images["found"]:
                result["warnings"].append(f"Specified image not found: {image}, but other terraform-pac-agent images are available: {', '.join(pac_agent_images['images'][:3])}")
            else:
                result["ok"] = False
                result["errors"].append(f"container image not found: {image}")

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
            mcp_health = check_mcp_server_health(check_image, docker_cli, docker_run_extra_args)
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

    # # Database check
    # if "all" in check_targets or "database" in check_targets:
    #     policy_db = env.get("POLICY_DB")
    #
    #     if not policy_db:
    #         result["ok"] = False
    #         result["errors"].append("POLICY_DB environment variable is not set")
    #         result["checks"]["policy_db_configured"] = False
    #         result["checks"]["policy_db_exists"] = False
    #     else:
    #         result["checks"]["policy_db_configured"] = True
    #         result["checks"]["policy_db"] = policy_db
    #
    #         # Check if the database file exists
    #         policy_db_path = resolve_path(repo_root, policy_db)
    #         db_exists = policy_db_path.exists()
    #         result["checks"]["policy_db_exists"] = db_exists
    #
    #         if not db_exists:
    #             result["ok"] = False
    #             result["errors"].append(f"Policy database file not found: {policy_db}")

    # # Early exit for database-only check
    # if check_targets == ["database"]:
    #     if output_format == "json":
    #         print(json.dumps(result, indent=2))
    #     else:
    #         print_interactive_report(result)
    #     return 0 if result["ok"] else 1

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

    # Local mode check.
    if "all" in check_targets or "local" in check_targets:
        external_repo_dir_val = env.get("EXTERNAL_REPO_DIR")
        is_local = not bool(external_repo_dir_val)
        result["checks"]["is_local_mode"] = is_local
        if not is_local:
            result["ok"] = False
            result["errors"].append(
                f"EXTERNAL_REPO_DIR is set ({external_repo_dir_val}); "
                "remove it from .env to use local mode "
                "(using external mode? ignore this)"
            )

        # In local mode, INPUT_DIR / INPUT_FILE / OUTPUT_DIR must be set
        local_required = ["INPUT_DIR", "INPUT_FILE", "OUTPUT_DIR"]
        missing_local = [k for k in local_required if not env.get(k)]
        result["checks"]["missing_local_keys"] = missing_local
        if missing_local:
            result["ok"] = False
            result["errors"].append(
                f"missing env keys for local mode: {', '.join(missing_local)}"
            )


    # External mode check
    if "all" in check_targets or "external" in check_targets:
        external_repo_dir_val = env.get("EXTERNAL_REPO_DIR", "").strip()
        ext_set = bool(external_repo_dir_val)
        ext_exists = Path(external_repo_dir_val).exists() if ext_set else False
        result["checks"]["external_repo_dir_set"] = ext_set
        result["checks"]["external_repo_dir_exists"] = ext_exists
        if ext_set:
            result["checks"]["external_repo_dir"] = external_repo_dir_val
        if not ext_set:
            result["ok"] = False
            result["errors"].append("EXTERNAL_REPO_DIR is not set in .env (using local mode? ignore this)")
        elif not ext_exists:
            result["ok"] = False
            result["errors"].append(f"EXTERNAL_REPO_DIR directory not found: {external_repo_dir_val}")

    # Early exit for external-only check
    if check_targets == ["external"]:
        if output_format == "json":
            print(json.dumps(result, indent=2))
        else:
            print_interactive_report(result)
        return 0 if result["ok"] else 1

    # API credentials check
    if "all" in check_targets or "api" in check_targets:
        api_result = check_api_credentials(env)
        result["checks"]["api_credentials"] = api_result
        if not api_result["ok"]:
            result["ok"] = False
            result["errors"].append(f"API credential check failed ({api_result['provider']}): {api_result.get('error', 'unknown error')}")

    # Early exit for api-only check
    if check_targets == ["api"]:
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
