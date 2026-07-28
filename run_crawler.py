#!/usr/bin/env python3
"""
Crawler Docker Runner for OpenCode
Runs the crawler in an OpenCode Docker container with proper logging and output control.
"""
import argparse
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
import select


def run(goal_file: str, log_file: Path, env_vars: dict, workspace_dir: Path, verbose: bool = False, timeout: int = 600, mode = "add"):
    """
    Run the crawler OpenCode Docker container.
    
    Args:
        goal_file: Path to the goal file
        log_file: Path to save the log file
        env_vars: Dictionary of environment variables
        workspace_dir: Workspace directory path
        verbose: If True, print all output to console; if False, only print up to "Starting OpenCode..."
        timeout: Maximum execution time in seconds (default: 600 = 10 minutes)
        mode: Crawler mode (crawler, add, delete, update, apply)
    """
    
    # Read goal file content
    with open(goal_file, 'r', encoding='utf-8') as f:
        goal_content = f.read()
    
    # Construct the full prompt based on mode
    if mode == "add":
        main_full_prompt = f"""run /crawler_add to complete the full workflow.

Source to process:
{goal_content}

Save delta to: `report/delta/{{timestamp}}.jsonl`
Save summary to: `report/summary/{{timestamp}}.md`"""

    elif mode == "delete":
        main_full_prompt = f"""run /crawler_delete to complete the full workflow.

Source to process:
{goal_content}

Save delta to: `report/delta/{{timestamp}}.jsonl`
Save summary to: `report/summary/{{timestamp}}.md`"""

    elif mode == "update":
        main_full_prompt = f"""run /crawler_update to complete the full workflow.

Source to process:
{goal_content}

Save delta to: `report/delta/{{timestamp}}.jsonl`
Save summary to: `report/summary/{{timestamp}}.md`"""

    elif mode == "inspect":
        main_full_prompt = f"""run /crawler_inspect to complete the full workflow.

Source to process:
{goal_content}

Save summary to: `report/summary/{{timestamp}}.md`"""

    elif mode == "apply":
        main_full_prompt = f"""run /crawler_apply to complete the full workflow.

Delta file to apply:
{goal_content}

Apply changes to: `database/policy_spec_db.jsonl`
Update tracking files: `database/version_history.jsonl` and `database/POLICY_SUMMARY.md`"""

    
    # Get host workspace path from environment variable (for Docker-in-Docker scenarios)
    host_workspace_path = env_vars.get('HOST_WORKSPACE_PATH')
    if host_workspace_path:
        mount_path = host_workspace_path
    else:
        mount_path = workspace_dir.as_posix()
    
    # Image configuration (matching run.sh)
    IMAGE_NAME = env_vars.get('IMAGE_NAME', 'terraform-pac-agent-skills')
    IMAGE_TAG = env_vars.get('IMAGE_TAG', 'latest')
    CONTAINER_PREFIX= env_vars.get('CRAWLER_CONTAINER_PREFIX', 'crawler-agent')
    CONTAINER_NAME=env_vars.get('CRAWLER_CONTAINER_NAME', CONTAINER_PREFIX)
    
    # Build Docker command
    base_cmd = [
        "docker", "run", "--rm",
        "--name", CONTAINER_NAME,
        "-e", f"MODEL_NAME={env_vars['MODEL_NAME']}",
        "-e", f"MODEL_API_KEY={env_vars['MODEL_API_KEY']}",
    ]
    
    # Pass AUTH_PROVIDER and GitHub Copilot credentials if set
    auth_provider = env_vars.get('AUTH_PROVIDER', 'litellm')
    base_cmd.extend(["-e", f"AUTH_PROVIDER={auth_provider}"])

    if auth_provider == "litellm":
        base_cmd.extend([
            "-e", f"MODEL_BASE_URL={env_vars.get('MODEL_BASE_URL', '')}",
            "-e", f"OPENCODE_MODEL=litellm/{env_vars['MODEL_NAME']}",
        ])       
    
    elif auth_provider == 'github-copilot':
        github_access = env_vars.get('GITHUB_COPILOT_ACCESS_TOKEN', '')
        github_refresh = env_vars.get('GITHUB_COPILOT_REFRESH_TOKEN', github_access)
        github_expires = env_vars.get('GITHUB_COPILOT_EXPIRES', '0')
        
        base_cmd.extend([
            "-e", f"GITHUB_COPILOT_ACCESS_TOKEN={github_access}",
            "-e", f"GITHUB_COPILOT_REFRESH_TOKEN={github_refresh}",
            "-e", f"GITHUB_COPILOT_EXPIRES={github_expires}",
            "-e", f"OPENCODE_MODEL=github-copilot1/{env_vars['MODEL_NAME']}",
        ])
    # Amazon Bedrock
    else:
        base_cmd.extend([
            "-e", f"OPENCODE_MODEL=amazon-bedrock/{env_vars['MODEL_NAME']}",
        ])

    
    # Mount directories
    main_cmd = base_cmd.copy()
    main_cmd.extend([
        "-v", f"{env_vars.get('TERRAFORM_BINARY_PATH', str((workspace_dir / 'docker/bin/terraform-linux-arm64').resolve()))}:/tmp/host-binaries/terraform:ro",
        "-v", f"{env_vars.get('TFPOLICY_BINARY_PATH', str((workspace_dir / 'docker/bin/tfpolicy-linux-amd64').resolve()))}:/tmp/host-binaries/tfpolicy:ro",
        "-v", f"{mount_path}/crawler/data:/workspace/data:ro",
        "-v", f"{mount_path}/crawler/report:/workspace/report",
        "-v", f"{mount_path}/database:/workspace/database",
        "-v", f"{mount_path}/crawler/cache:/workspace/cache",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        f"{IMAGE_NAME}:{IMAGE_TAG}", "opencode", "run", main_full_prompt
    ])
    
    print(f"\n{'='*40}\n")
    print(f"Running Crawler OpenCode container")
    print(f"Log file: {log_file}")
    print(f"\n{'='*40}\n")
    
    # Open log file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, 'w', encoding='utf-8') as log:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f"=== Crawler OpenCode Container Log ===\n")
        log.write(f"Container: {CONTAINER_NAME}\n")
        log.write(f"Timestamp: {timestamp}\n")
        log.write(f"{'='*40}\n\n")
        log.flush()
        
        # Run process with pipes for real-time output
        process = subprocess.Popen(
            main_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        import time
        start_time = time.time()
        suppress_console = False
        
        # Stream output in real-time
        while True:
            # Check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    # Timeout exceeded - kill the process
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    
                    log.write(f"\n{'='*40}\n")
                    log.write(f"TIMEOUT: Process exceeded {timeout} seconds limit\n")
                    log.write(f"Elapsed time: {elapsed:.1f} seconds\n")
                    
                    print(f"\n{'='*40}")
                    print(f"⚠️  TIMEOUT: Crawler exceeded {timeout} seconds limit")
                    print(f"Elapsed time: {elapsed:.1f} seconds")
                    print(f"{'='*40}\n")
                    
                    break
            
            # Check if process has finished
            if process.poll() is not None:
                remaining = process.stdout.read()
                if remaining:
                    log.write(remaining)
                    log.flush()
                    if verbose or not suppress_console:
                        print(remaining, end='')
                break
            
            # Use select to check if data is available
            ready, _, _ = select.select([process.stdout], [], [], 1.0)
            
            if ready:
                line = process.stdout.readline()
                if line:
                    log.write(line)
                    log.flush()
                    
                    # Check if we should start suppressing console output
                    if "Starting OpenCode" in line or "Initializing" in line:
                        suppress_console = True
                        if not verbose:
                            print("\n🔄 Crawler is now executing... (detailed logs saved to file)\n")
                    
                    # Write to console based on verbose flag and suppress state
                    if verbose or not suppress_console:
                        print(line, end='')
        
        # Get the return code
        return_code = process.returncode
        
        log.write(f"\n{'='*40}\n")
        log.write(f"Process completed with return code: {return_code}\n")
        log.write(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    

    # Clean up container if it still exists
    try:
        subprocess.run(
            ["docker", "rm", "-f", CONTAINER_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10
        )
    except Exception:
        pass  # Container may already be removed by --rm flag

    print(f"\n{'='*40}\n")
    print(f"Running Guide Generation...")
    print(f"\n{'='*40}\n")
        
    # Construct guide prompt
    guide_full_prompt = f"""run /crawler_guide to complete the full workflow.

Executed mode:
{mode} mode

User's original input (crawler_goal.txt content): {goal_content}

Log file to analyze (generated from execution results):
log/{log_file.name}

Save guide to: `guide/guide_{log_file.stem[len("crawler_"):]}.md`"""
        
    # Build guide command with independent copy of base_cmd
    guide_cmd = base_cmd.copy()
    guide_cmd.extend([
        "-v", f"{env_vars.get('TERRAFORM_BINARY_PATH', str((workspace_dir / 'docker/bin/terraform-linux-arm64').resolve()))}:/tmp/host-binaries/terraform:ro",
        "-v", f"{env_vars.get('TFPOLICY_BINARY_PATH', str((workspace_dir / 'docker/bin/tfpolicy-linux-amd64').resolve()))}:/tmp/host-binaries/tfpolicy:ro",
        "-v", f"{mount_path}/crawler/log:/workspace/log:ro",
        "-v", f"{mount_path}/crawler/guide:/workspace/guide",
        "-v", f"{mount_path}/crawler/report:/workspace/report",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        f"{IMAGE_NAME}:{IMAGE_TAG}", "opencode", "run", guide_full_prompt
    ])
    
    # Generate guide log file
    guide_log_file = log_file.parent / f"guide_{log_file.name[len("crawler_"):]}"
    
    # Run guide generation
    with open(guide_log_file, 'w', encoding='utf-8') as guide_log:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        guide_log.write(f"=== Guide Generation Log ===\n")
        guide_log.write(f"Timestamp: {timestamp}\n")
        guide_log.write(f"{'='*40}\n\n")
        guide_log.flush()
        
        guide_process = subprocess.Popen(
            guide_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        import time
        guide_start_time = time.time()
        guide_suppress_console = False
        
        # Stream output in real-time
        while True:
            # Check if process has finished
            if guide_process.poll() is not None:
                remaining = guide_process.stdout.read()
                if remaining:
                    guide_log.write(remaining)
                    guide_log.flush()
                    if verbose or not guide_suppress_console:
                        print(remaining, end='')
                break
            
            # Use select to check if data is available
            ready, _, _ = select.select([guide_process.stdout], [], [], 1.0)
            
            if ready:
                line = guide_process.stdout.readline()
                if line:
                    guide_log.write(line)
                    guide_log.flush()
                    
                    # Check if we should start suppressing console output
                    if "Starting OpenCode" in line or "Initializing" in line:
                        guide_suppress_console = True
                        if not verbose:
                            print("\n🔄 Guide generation is now executing... (detailed logs saved to file)\n")
                    
                    # Write to console based on verbose flag and suppress state
                    if verbose or not guide_suppress_console:
                        print(line, end='')
        
        guide_return_code = guide_process.returncode
        
        guide_log.write(f"\n{'='*40}\n")
        guide_log.write(f"Guide generation completed with return code: {guide_return_code}\n")
        guide_log.write(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    
    return return_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["delete", "update", "add", "inspect", "apply"])
    args = parser.parse_args()

    mode = args.mode
    print(f"Mode: {mode}")

    # Get workspace directory
    workspace_dir = Path.cwd()
    
    # Load environment variables from .env file
    env_file = workspace_dir / ".env"
    if not env_file.exists():
        print("Error: .env file not found.")
        print("Please create a .env file with the required variables.")
        sys.exit(1)
    
    env_vars = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                line = line.split('#')[0].strip()
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    
    # Check required variables based on AUTH_PROVIDER
    auth_provider = env_vars.get('AUTH_PROVIDER', 'litellm')
    
    if auth_provider == 'github-copilot':
        if 'GITHUB_COPILOT_ACCESS_TOKEN' not in env_vars:
            print("Error: GITHUB_COPILOT_ACCESS_TOKEN not set in .env file")
            sys.exit(1)
        # Set dummy values for compatibility
        env_vars['MODEL_API_KEY'] = env_vars['GITHUB_COPILOT_ACCESS_TOKEN']
        env_vars.setdefault('MODEL_BASE_URL', 'https://api.githubcopilot.com')
    else:
        if 'MODEL_API_KEY' not in env_vars:
            print("Error: MODEL_API_KEY not set in .env file")
            sys.exit(1)
    
    if 'MODEL_NAME' not in env_vars:
        print("Error: MODEL_NAME not set in .env file")
        sys.exit(1)
    
    # Set defaults
    env_vars.setdefault('AUTH_PROVIDER', 'litellm')
    
    if env_vars['AUTH_PROVIDER'] == 'litellm':
        env_vars.setdefault('MODEL_BASE_URL', 'https://ete-litellm.ai-models.vpc-int.res.ibm.com')
        env_vars.setdefault('MODEL_NAME', 'aws/claude-sonnet-4-5')
    
    # Get binary paths from environment
    env_vars.setdefault('TERRAFORM_BINARY_PATH', env_vars.get('TERRAFORM_BINARY_PATH', ''))
    env_vars.setdefault('TFPOLICY_BINARY_PATH', env_vars.get('TFPOLICY_BINARY_PATH', ''))
    
    # Check if goal file exists
    goal_file = workspace_dir / "crawler" / "crawler_goal.txt"
    if not goal_file.exists():
        print("Error: crawler_goal.txt not found.")
        print("Please create a crawler_goal.txt file with your crawler instructions.")
        sys.exit(1)
    
    # Generate log file name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = workspace_dir / "crawler" / "log" / f"crawler_{timestamp}.log"
    
    # Get timeout from environment or use default (60 minutes = 3600 seconds)
    timeout = int(env_vars.get('CRAWLER_TIMEOUT', '3600'))
    
    print("Configuration:")
    print(f"  Auth Provider: {env_vars['AUTH_PROVIDER']}")
    print(f"  Model: {env_vars['MODEL_NAME']}")
    if env_vars.get('MODEL_BASE_URL'):
        print(f"  Base URL: {env_vars['MODEL_BASE_URL']}")
    print(f"  Goal file: crawler_goal.txt")
    print(f"  Timeout: {timeout} seconds ({timeout//60} minutes)")
    print()
    
    # Run crawler (verbose=False to suppress output after initialization)
    return_code = run(
        goal_file=str(goal_file),
        log_file=log_file,
        env_vars=env_vars,
        workspace_dir=workspace_dir,
        verbose=False,
        timeout=timeout,
        mode=mode
    )
    
    print()
    print("="*40)
    print("✓ Crawler Execution Complete!")
    print("="*40)
    print()
    print(f"Log saved to: {log_file}")
    print()
    
    sys.exit(return_code)


if __name__ == "__main__":
    main()