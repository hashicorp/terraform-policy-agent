#!/usr/bin/env python3
"""
Terraform Policy Automation Agent Skills - Pipeline Execution Script

This script automates the execution of all stages in the policy generation pipeline:
- Stage 0: Policy Extraction
- Stage 1: Requirement Generation (parallel execution)
- Stage 2: Policy Generation (parallel execution)
- Stage 3: Summary Generation

Based on MANUAL_STEPS.md

Prerequisites:
  1. Place your policy descriptions in data/input/policy_goal.txt
  2. Set environment variables: MODEL_BASE_URL, MODEL_API_KEY, MODEL_NAME
  3. Build Docker image: ./docker/build.sh
  4. (Optional) Set MAX_WORKERS environment variable to control parallelism (default: 5)

Usage:
  python3 run_pipeline.py

For individual stage execution, use docker/run.sh:
  ./docker/run.sh --skill <skill-name> --prompt "<prompt>"
"""

import os
import sys
import subprocess
import time
import signal
import atexit
import re
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime


class PipelineExecutor:
    """Executes the Terraform PAC Agent Skills pipeline"""
    
    def __init__(self, script_dir: Path):
        # script_dir is the directory where run_pipeline.py is located
        self.script_dir = script_dir
        self.project_root = script_dir.parent
        
        # Get DATA_DIR from environment, default to ./data
        data_dir_str = os.getenv("DATA_DIR", "./data")
        if os.path.isabs(data_dir_str):
            self.data_dir = Path(data_dir_str)
        else:
            # Relative path - resolve from current working directory
            self.data_dir = Path.cwd() / data_dir_str
        
        # Get INPUT_DIR from environment, default to input
        input_dir_name = os.getenv("INPUT_DIR", "input")
        
        # Get OUTPUT_DIR from environment, default to output
        output_dir_name = os.getenv("OUTPUT_DIR", "output")
        
        # Get MAX_WORKERS from environment, default to 5
        self.max_workers = int(os.getenv("MAX_WORKERS", "5"))
        
        self.input_dir = self.data_dir / input_dir_name
        self.output_dir = self.data_dir / output_dir_name
        self.goals_dir = self.output_dir / "goals"
        
        # run.sh path - same directory as run_pipeline.py
        self.run_sh = script_dir / "run.sh"
        
        # LLM configuration
        self.auth_provider = os.getenv("AUTH_PROVIDER", "litellm")
        self.model_base_url = os.getenv("MODEL_BASE_URL")
        self.model_api_key = os.getenv("MODEL_API_KEY")
        self.model_name = os.getenv("MODEL_NAME")
        
        # GitHub Copilot OAuth tokens (only needed if AUTH_PROVIDER=github-copilot)
        self.github_copilot_access_token = os.getenv("GITHUB_COPILOT_ACCESS_TOKEN")
        self.github_copilot_refresh_token = os.getenv("GITHUB_COPILOT_REFRESH_TOKEN")
        self.github_copilot_expires = os.getenv("GITHUB_COPILOT_EXPIRES")
        
        # Timeout configuration (in seconds)
        self.stage0_timeout = int(os.getenv("STAGE0_TIMEOUT", "600"))  # 10 minutes
        self.stage1_timeout = int(os.getenv("STAGE1_TIMEOUT", "300"))  # 5 minutes
        self.stage2_timeout = int(os.getenv("STAGE2_TIMEOUT", "900"))  # 15 minutes
        self.stage3_timeout_base = int(os.getenv("STAGE3_TIMEOUT_BASE", "180"))  # 3 minutes base
        self.stage3_timeout_per_policy = int(os.getenv("STAGE3_TIMEOUT_PER_POLICY", "60"))  # 1 minute per policy
        self.stage4_timeout = int(os.getenv("STAGE4_TIMEOUT", "300"))  # 5 minutes

        # Retry configuration
        self.max_retries = int(os.getenv("MAX_RETRIES", "1"))  # Default: 1 retry (backward compatible)

        # Stage 4 enable flag
        self.enable_stage4 = os.getenv("ENABLE_STAGE4", "false").lower() in ("true", "1", "yes")
        
        # Container configuration
        self.container_prefix = os.getenv("CONTAINER_PREFIX", "terraform-pac-agent-skills")
        
        # Track running containers for cleanup
        self.running_containers: Set[str] = set()
        self.cleanup_registered = False
        
        # Validate environment
        self._validate_environment()
    
    def _validate_environment(self):
        """Validate required environment variables and directories"""
        # Note: Environment variable validation (AUTH_PROVIDER, MODEL_*, binary paths)
        # is handled by run.sh before calling this script.
        # This avoids duplication and keeps validation logic in one place.
        
        # Create input directory
        self.input_dir.mkdir(parents=True, exist_ok=True)
        
        # OUTPUT_DIR must not contain existing artifacts when starting from stage 0/full pipeline
        stage_arg = next((arg for arg in sys.argv[1:] if arg == "--step"), None)
        stage_value = None
        if stage_arg:
            try:
                stage_index = sys.argv.index("--step")
                stage_value = sys.argv[stage_index + 1]
            except (ValueError, IndexError):
                stage_value = None
        
        should_validate_output_dir = stage_value in (None, "0")
        if should_validate_output_dir and self.output_dir.exists() and any(self.output_dir.iterdir()):
            raise ValueError(
                f"OUTPUT_DIR already exists and is not empty: {self.output_dir}. "
                "Please set a new OUTPUT_DIR in .env."
            )
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.goals_dir.mkdir(parents=True, exist_ok=True)
        
        # Register cleanup handlers
        if not self.cleanup_registered:
            atexit.register(self._cleanup_containers)
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            self.cleanup_registered = True
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals (Ctrl+C)"""
        print("\n\n⚠️  Interrupt received! Cleaning up containers...")
        self._cleanup_containers()
        sys.exit(1)
    
    def _cleanup_containers(self):
        """Stop and remove all running containers"""
        if not self.running_containers:
            return
        
        print(f"\n🧹 Cleaning up {len(self.running_containers)} container(s)...")
        for container_name in list(self.running_containers):
            try:
                # Try to stop the container
                subprocess.run(
                    ["docker", "stop", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                # Try to remove the container
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                print(f"  ✓ Cleaned up: {container_name}")
            except Exception as e:
                print(f"  ✗ Failed to cleanup {container_name}: {e}")
            finally:
                self.running_containers.discard(container_name)
        
        print("✅ Cleanup complete\n")
    
    def _clean_log_line(self, line: str) -> str:
        """
        Clean log line by removing ANSI escape sequences and excessive whitespace
        
        Args:
            line: Raw log line from Docker output
        
        Returns:
            Cleaned log line
        """
        # Remove ANSI escape sequences (color codes, cursor movements, etc.)
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        cleaned = ansi_escape.sub('', line)
        
        # Remove carriage returns that might cause overwriting
        cleaned = cleaned.replace('\r', '')
        
        # Replace excessive spaces (more than 2 consecutive spaces) with single space
        # but preserve leading indentation
        if cleaned.strip():  # Only process non-empty lines
            # Count leading spaces
            leading_spaces = len(cleaned) - len(cleaned.lstrip(' '))
            # Clean the rest of the line
            rest = cleaned.lstrip(' ')
            rest = re.sub(r' {3,}', ' ', rest)
            cleaned = ' ' * leading_spaces + rest
        
        return cleaned
    
    def _run_docker_command(
        self,
        skill: str,
        prompt: str,
        stage_name: str,
        container_suffix: str = "",
        log_file: Optional[Path] = None,
        timeout_seconds: int = 600,
        skill_args: Optional[List[str]] = None,
        verbose: bool = False
    ) -> bool:
        """
        Run a Docker command for a specific skill using run.sh
        
        Args:
            skill: Skill name (e.g., "step0-extraction")
            prompt: Natural language prompt for the skill (used only if skill_args not provided)
            stage_name: Human-readable stage name for logging
            container_suffix: Suffix for container name (for parallel execution)
            log_file: Path to log file for stdout/stderr
            timeout_seconds: Timeout in seconds (default: 600 = 10 minutes)
            skill_args: Optional list of skill-specific arguments (e.g., ["--goal-file", "goal-001.txt"])
            verbose: If True, stream output to console; if False, only write to log file (default: False)
        
        Returns:
            True if successful, False otherwise
        """
        # Build command with skill-specific args or fallback to prompt
        cmd = [str(self.run_sh), skill]
        if skill_args:
            cmd.extend(skill_args)
        else:
            cmd.extend(["--prompt", prompt])
        
        # Set unique container name for parallel execution
        container_name = self.container_prefix
        if container_suffix:
            container_name = f"{self.container_prefix}-{container_suffix}"
        
        log_handle = None
        try:
            # Open log file if specified
            if log_file:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                log_handle = open(log_file, 'w', encoding='utf-8')
                log_handle.write(f"{'='*80}\n")
                log_handle.write(f"{stage_name}\n")
                log_handle.write(f"{'='*80}\n")
                log_handle.write(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_handle.write(f"Command: {' '.join(cmd)}\n")
                log_handle.write(f"{'='*80}\n\n")
                log_handle.flush()
            
            # Set environment with container name
            env = os.environ.copy()
            env['CONTAINER_NAME'] = container_name
            # Skip OUTPUT_DIR empty check when called from run_pipeline.py
            # (run_pipeline.py creates log files in OUTPUT_DIR before calling run.sh)
            env['SKIP_OUTPUT_DIR_CHECK'] = '1'
            
            # Track this container
            self.running_containers.add(container_name)
            
            # Run command with streaming output and timeout
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )
            
            # Stream output to both console and log file with timeout
            start_time = time.time()
            
            # Use select for non-blocking I/O with timeout support
            import select
            
            # Stream output in real-time to log file and console
            while True:
                # Check timeout before reading
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    # Timeout exceeded - stop the Docker container
                    print(f"\n⏱️  Timeout reached, stopping container: {container_name}")
                    
                    # Stop the Docker container
                    try:
                        subprocess.run(
                            ["docker", "stop", container_name],
                            timeout=5,
                            capture_output=True
                        )
                    except Exception as e:
                        print(f"Warning: Failed to stop container: {e}")
                    
                    # Kill the run.sh process
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    
                    # Remove from tracking
                    self.running_containers.discard(container_name)
                    
                    timeout_msg = f"\n❌ {stage_name} timed out after {timeout_seconds} seconds ({timeout_seconds/60:.1f} minutes)\n"
                    print(timeout_msg)
                    if log_handle:
                        log_handle.write(timeout_msg)
                        log_handle.close()
                    return False
                
                # Check if process has finished
                if process.poll() is not None:
                    # Read any remaining output
                    if process.stdout:
                        remaining = process.stdout.read()
                        if remaining:
                            # Clean remaining output
                            cleaned_remaining = self._clean_log_line(remaining)
                            
                            if verbose:
                                print(cleaned_remaining, end='')
                            if log_handle:
                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                                log_handle.write(f"[{timestamp}] {cleaned_remaining}")
                                log_handle.flush()
                    break
                
                # Use select to check if data is available (with 1 second timeout)
                if process.stdout:
                    ready, _, _ = select.select([process.stdout], [], [], 1.0)
                    
                    if ready:
                        line = process.stdout.readline()
                        if line:
                            # Clean the line before writing
                            cleaned_line = self._clean_log_line(line)
                            
                            # Write to log file (and optionally console)
                            if verbose:
                                print(cleaned_line, end='')
                            if log_handle:
                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                                log_handle.write(f"[{timestamp}] {cleaned_line}")
                                log_handle.flush()
            
            # Get the return code (process has already finished)
            return_code = process.returncode
            
            if log_handle:
                log_handle.write(f"\n{'='*80}\n")
                log_handle.write(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_handle.write(f"Return code: {return_code}\n")
                log_handle.write(f"Execution time: {time.time() - start_time:.2f} seconds\n")
                log_handle.close()
            
            # Remove from tracking
            self.running_containers.discard(container_name)
            
            # Print completion message to console
            elapsed = time.time() - start_time
            if return_code != 0:
                print(f"[{stage_name}] Failed ({elapsed:.1f}s) ✗")
                if log_file:
                    print(f"  Log: {log_file}")
                return False
            else:
                print(f"[{stage_name}] Completed ({elapsed:.1f}s) ✓")
            
            return True
            
        except subprocess.TimeoutExpired:
            timeout_msg = f"\n❌ {stage_name} timed out after {timeout_seconds} seconds ({timeout_seconds/60:.1f} minutes)\n"
            print(timeout_msg)
            if log_handle and not log_handle.closed:
                log_handle.write(timeout_msg)
                log_handle.close()
            self.running_containers.discard(container_name)
            return False
        except Exception as e:
            error_msg = f"\n❌ {stage_name} failed with error: {e}\n"
            print(error_msg)
            if log_handle and not log_handle.closed:
                log_handle.write(error_msg)
                log_handle.close()
            self.running_containers.discard(container_name)
            return False
    
    def _verify_stage0_output(self) -> bool:
        """Verify that Stage 0 produced expected output files."""
        goals_dir = self.goals_dir
        
        if not goals_dir.exists():
            print(f"  ✗ Verification failed: Goals directory not created: {goals_dir}")
            return False
        
        goal_files = sorted([f for f in goals_dir.iterdir() if f.name.startswith("goal-") and f.name.endswith(".txt")])
        if not goal_files:
            print(f"  ✗ Verification failed: No goal files found in {goals_dir}")
            return False
        
        print(f"  ✓ Verification passed: {len(goal_files)} goal file(s) created")
        return True
    
    def _identify_policy_directory_for_goal(self, goal_file: Path, log_file: Optional[Path] = None) -> Optional[Path]:
        """Identify which policy directory was created for a given goal file.
        
        Uses a multi-stage approach:
        1. Grep policy directory names in goal file content
        2. If that fails, grep in log file
        3. Return None if identification fails
        
        Args:
            goal_file: Path to the goal file
            log_file: Path to the log file (optional)
            
        Returns:
            Path to the policy directory, or None if not identified
        """
        if not self.output_dir.exists():
            return None
        
        # Get all policy directories
        policy_dirs = [d for d in self.output_dir.iterdir()
                      if d.is_dir() and not d.name.startswith('.') and d.name != 'goals']
        
        if not policy_dirs:
            return None
        
        # Step 1: Search in goal file content
        try:
            goal_content = goal_file.read_text()
            matches = []
            for policy_dir in policy_dirs:
                if policy_dir.name in goal_content:
                    matches.append(policy_dir)
            
            if len(matches) == 1:
                return matches[0]
        except Exception:
            pass
        
        # Step 2: Search in log file if provided
        if log_file and log_file.exists():
            try:
                log_content = log_file.read_text()
                matches = []
                for policy_dir in policy_dirs:
                    if policy_dir.name in log_content:
                        matches.append(policy_dir)
                
                if len(matches) == 1:
                    return matches[0]
            except Exception:
                pass
        
        # Step 3: Could not identify uniquely
        return None
    
    def _verify_policy_directory(self, policy_dir: Path) -> bool:
        """Verify that a policy directory has required files.
        
        Args:
            policy_dir: Path to the policy directory
            
        Returns:
            True if valid, False otherwise
        """
        requirement_file = policy_dir / "requirement.txt"
        report_file = policy_dir / "report.md"
        
        if not requirement_file.exists():
            return False
        
        if not report_file.exists():
            return False
        
        return True
    
    def _extract_policytest_targets(self, test_file: Path) -> Optional[List[str]]:
        """Extract the target policy filenames declared in a .policytest.hcl file.

        Returns:
            The list of target filenames, or None if the file has no policytest
            block with a targets attribute.
        """
        try:
            text = test_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        block = re.search(r"policytest\s*\{(.*?)\}", text, re.DOTALL)
        if not block:
            return None

        targets = re.search(r"targets\s*=\s*\[(.*?)\]", block.group(1), re.DOTALL)
        if not targets:
            return None

        return re.findall(r'"([^"]+)"', targets.group(1))

    def _verify_stage2_output(self, policy_dir: Path) -> bool:
        """Verify that Stage 2 produced expected output files for a policy.

        A policy may own one or more `*.policytest.hcl` files. The discovered set must
        be exactly `<policy_name>.policytest.hcl` plus `<policy_name>-2..N.policytest.hcl`
        with no gaps, every file must declare its target policy, and no file may target
        a policy outside this directory.
        """
        policy_name = policy_dir.name

        # Check for policy file (.policy.hcl)
        policy_files = list(policy_dir.glob("*.policy.hcl"))
        if not policy_files:
            print(f"  ✗ Verification failed: No .policy.hcl file found in {policy_name}")
            return False

        # Check for test files (one or more *.policytest.hcl)
        test_files = sorted(policy_dir.glob("*.policytest.hcl"))
        if not test_files:
            print(f"  ✗ Verification failed: No .policytest.hcl file found in {policy_name}")
            return False

        # Naming convention: <policy_name>.policytest.hcl plus <policy_name>-N.policytest.hcl.
        # A file outside this convention is a leftover from an earlier attempt, and it would
        # still be executed by `tfpolicy test --policies=.`.
        suffix = ".policytest.hcl"
        indices: List[int] = []
        for test_file in test_files:
            stem = test_file.name[: -len(suffix)]
            if stem == policy_name:
                indices.append(1)
                continue
            numbered = re.fullmatch(rf"{re.escape(policy_name)}-(\d+)", stem)
            if not numbered:
                print(f"  ✗ Verification failed: Test file does not follow the naming "
                      f"convention in {policy_name}: {test_file.name} "
                      f"(expected {policy_name}{suffix} or {policy_name}-N{suffix})")
                return False
            indices.append(int(numbered.group(1)))

        if sorted(indices) != list(range(1, len(indices) + 1)):
            print(f"  ✗ Verification failed: Test file numbering has gaps or duplicates in "
                  f"{policy_name}: {[f.name for f in test_files]}")
            return False

        # Every test file must declare its target, and only this policy's own target.
        expected_target = f"{policy_name}.policy.hcl"
        for test_file in test_files:
            targets = self._extract_policytest_targets(test_file)
            if targets is None:
                print(f"  ✗ Verification failed: No policytest.targets block in "
                      f"{policy_name}/{test_file.name}")
                return False
            foreign = [t for t in targets if t.lower() != expected_target.lower()]
            if foreign:
                print(f"  ✗ Verification failed: {policy_name}/{test_file.name} targets "
                      f"policies outside this directory: {foreign} "
                      f"(expected only {expected_target})")
                return False

        # The test command must actually have run and passed.
        report_file = policy_dir / "report.md"
        if not report_file.exists():
            print(f"  ✗ Verification failed: report.md not found in {policy_name}")
            return False
        report_text = report_file.read_text(encoding="utf-8", errors="replace")
        if "## Test Execution" not in report_text:
            print(f"  ✗ Verification failed: report.md has no '## Test Execution' section "
                  f"in {policy_name}")
            return False
        if "- Status: Failure" in report_text:
            print(f"  ✗ Verification failed: report.md records a failing test run in "
                  f"{policy_name}")
            return False

        print(f"  ✓ Verification passed: 1 policy and {len(test_files)} test file(s) "
              f"created for {policy_name}")
        return True
    
    def _verify_stage4_output(self, policy_dir: Path) -> bool:
        """Verify that Stage 4 produced expected output files for a policy."""
        policy_name = policy_dir.name
        
        # Check for pass_config.tf
        pass_config = policy_dir / "pass_config.tf"
        if not pass_config.exists():
            print(f"  ✗ Verification failed: pass_config.tf not found in {policy_name}")
            return False
        
        # Check for fail_config.tf
        fail_config = policy_dir / "fail_config.tf"
        if not fail_config.exists():
            print(f"  ✗ Verification failed: fail_config.tf not found in {policy_name}")
            return False
        
        print(f"  ✓ Verification passed: Fixture files created for {policy_name}")
        return True
    
    def _verify_stage3_output(self) -> bool:
        """Verify that Stage 3 produced expected output files."""
        summary_json = self.output_dir / "summary.json"
        summary_md = self.output_dir / "summary.md"
        
        if not summary_json.exists():
            print(f"  ✗ Verification failed: summary.json not found")
            return False
        
        if not summary_md.exists():
            print(f"  ✗ Verification failed: summary.md not found")
            return False
        
        print(f"  ✓ Verification passed: Summary files created")
        return True
    
    def stage0_extraction(self) -> bool:
        """Stage 0: Extract individual goals from policy descriptions"""
        # Read INPUT_FILE from environment (default: "policy_goal.txt")
        input_file = os.getenv("INPUT_FILE", "policy_goal.txt")
        input_path = self.input_dir / input_file
        
        if not input_path.exists():
            print(f"❌ Input file not found: {input_path}")
            print(f"Please create the file with your policy descriptions:")
            print(f"  mkdir -p {self.input_dir}")
            print(f"  cat > {input_path} << 'EOF'")
            print(f"  Generate TF Policy for")
            print(f"  SecurityHub: IAM.21")
            print(f"  EOF")
            return False
        
        print(f"\n{'='*80}")
        print(f"Stage 0: Policy Extraction")
        print(f"{'='*80}\n")
        
        log_file = self.output_dir / "stage0_extraction.log"
        
        # Note: INPUT_FILE is read from .env, not passed as argument
        # Use configured timeout
        success = self._run_docker_command(
            skill="step0-extraction",
            prompt="",  # Uses default prompt from run.sh
            stage_name="Stage 0: Policy Extraction",
            log_file=log_file,
            timeout_seconds=self.stage0_timeout,
            skill_args=[]  # No arguments needed, INPUT_FILE from .env
        )
        
        if not success:
            return False
        
        # Verify output even if exit code was 0
        if not self._verify_stage0_output():
            print("\n❌ Stage 0 output verification failed")
            return False
        
        return True
    
    def _run_single_requirement(self, goal_file: Path, index: int, total: int, retry: bool = False) -> Tuple[str, bool, str]:
        """
        Run requirement generation for a single goal file
        
        Args:
            goal_file: Path to the goal file
            index: Current index in processing
            total: Total number of goals
            retry: Whether this is a retry attempt
        
        Returns:
            Tuple of (goal_name, success, error_message)
        """
        goal_name = goal_file.stem
        log_suffix = "_retry" if retry else ""
        log_file = self.goals_dir / f"{goal_name}_stage1{log_suffix}.log"
        
        retry_label = " (retry)" if retry else ""
        print(f"  [{index}/{total}] Processing{retry_label}: {goal_file.name}")
        
        # Use configured timeout (1.5x for retry)
        timeout = int(self.stage1_timeout * 1.5) if retry else self.stage1_timeout
        if retry:
            print(f"  Using increased timeout for retry: {timeout}s (base: {self.stage1_timeout}s, multiplier: 1.5x)")
        success = self._run_docker_command(
            skill="step1-requirement",
            prompt="",  # Not used when skill_args provided
            stage_name=f"Stage 1: Requirement ({goal_name}){retry_label}",
            container_suffix=f"{goal_name}{'-retry' if retry else ''}",
            log_file=log_file,
            timeout_seconds=timeout,
            skill_args=["--goal-file", goal_file.name]
        )
        
        if not success:
            # Append failure reason to log file
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"[run_pipeline.py] Docker execution failed\n")
                f.write(f"{'='*80}\n")
            return (goal_name, False, "Execution failed")
        
        # Try to identify which policy directory was created for this goal
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[run_pipeline.py] Post-execution verification\n")
            f.write(f"{'='*80}\n")
        
        policy_dir = self._identify_policy_directory_for_goal(goal_file, log_file)
        
        if policy_dir:
            # Log identified directory
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"✓ Identified policy directory: {policy_dir.name}\n")
            
            # Verify the identified directory has required files
            if not self._verify_policy_directory(policy_dir):
                # Directory is incomplete - delete it for retry
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"✗ Policy directory is incomplete (missing required files)\n")
                    f.write(f"  Required files: requirement.txt, report.md\n")
                
                try:
                    import shutil
                    shutil.rmtree(policy_dir)
                    msg = f"✓ Removed incomplete directory: {policy_dir.name}\n"
                    print(f"  ⚠️  {msg.strip()}")
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(msg)
                except Exception as e:
                    msg = f"✗ Could not remove directory {policy_dir.name}: {e}\n"
                    print(f"  ⚠️  {msg.strip()}")
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(msg)
                
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"[run_pipeline.py] Result: FAILED - Will retry\n")
                    f.write(f"{'='*80}\n")
                
                return (goal_name, False, f"Policy directory {policy_dir.name} missing required files")
            else:
                # Directory is complete
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"✓ Policy directory verification passed\n")
                    f.write(f"\n{'='*80}\n")
                    f.write(f"[run_pipeline.py] Result: SUCCESS\n")
                    f.write(f"{'='*80}\n")
        else:
            # Could not identify the policy directory
            # This is not necessarily an error - verification will happen at the end of stage1
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"⚠ Could not identify policy directory from log\n")
                f.write(f"  (Will be verified at the end of stage1)\n")
                f.write(f"\n{'='*80}\n")
                f.write(f"[run_pipeline.py] Result: SUCCESS (pending final verification)\n")
                f.write(f"{'='*80}\n")
        
        return (goal_name, True, "")
    
    def stage1_requirement(self) -> Tuple[bool, List[str]]:
        """Stage 1: Generate requirements for all goals (parallel execution with priority retry)
        
        Returns:
            Tuple of (all_succeeded, list_of_successful_policy_dirs)
        """
        from queue import PriorityQueue
        from threading import Lock
        
        goal_files = sorted(list(self.goals_dir.glob("goal-*.txt")))
        
        if not goal_files:
            print("❌ No goal files found")
            return False, []
        
        print(f"\n{'='*80}")
        print(f"Stage 1: Requirement Generation (Parallel)")
        print(f"{'='*80}")
        print(f"Found {len(goal_files)} goal(s) to process")
        print(f"Max workers: {self.max_workers}\n")
        
        # Priority queue: (priority, counter, goal_file, index, is_retry)
        # Lower priority number = higher priority (0 = retry, 1 = initial)
        task_queue = PriorityQueue()
        task_counter = 0
        results: Dict[str, Tuple[bool, str]] = {}
        retry_count: Dict[str, int] = {}
        goal_to_policy_dir: Dict[str, Optional[Path]] = {}  # Track which policy dir each goal created
        results_lock = Lock()
        
        # Add initial tasks to queue (priority=1 for initial tasks)
        for index, goal_file in enumerate(goal_files, 1):
            task_queue.put((1, task_counter, goal_file, index, False))
            task_counter += 1
            goal_name = goal_file.stem
            retry_count[goal_name] = 0
            goal_to_policy_dir[goal_name] = None
        
        total_tasks = len(goal_files)
        completed = 0
        failed = 0
        
        # Worker function that processes tasks from the queue
        def worker():
            nonlocal completed, failed, task_counter
            
            while True:
                try:
                    # Get task from queue (blocks if empty)
                    priority, _, goal_file, index, is_retry = task_queue.get(timeout=1)
                except:
                    # Queue is empty and timeout reached
                    break
                
                try:
                    # Execute the task
                    goal_name, success, error = self._run_single_requirement(
                        goal_file, index, total_tasks, retry=is_retry
                    )
                    
                    retry_label = " (retry)" if is_retry else ""
                    
                    with results_lock:
                        if success:
                            completed += 1
                            results[goal_name] = (success, error)
                            log_suffix = "_retry" if is_retry else ""
                            log_file = self.goals_dir / f"{goal_name}_stage1{log_suffix}.log"
                            
                            # Identify and track the policy directory for this goal
                            policy_dir = self._identify_policy_directory_for_goal(goal_file, log_file)
                            if policy_dir:
                                goal_to_policy_dir[goal_name] = policy_dir
                            
                            print(f"  ✓ Completed{retry_label}: {goal_name} (log: {log_file})")
                        else:
                            # Check if we should retry
                            if retry_count[goal_name] < self.max_retries:
                                # Add retry task with higher priority (0)
                                retry_count[goal_name] += 1
                                print(f"  ✗ Failed{retry_label}: {goal_name} - {error}")
                                print(f"  ⟳ Queuing retry {retry_count[goal_name]}/{self.max_retries} with high priority: {goal_name}")
                                task_queue.put((0, task_counter, goal_file, index, True))
                                task_counter += 1
                            else:
                                # Max retries reached, mark as final failure
                                failed += 1
                                results[goal_name] = (success, error)
                                print(f"  ✗ Failed{retry_label}: {goal_name} - {error} (max retries {self.max_retries} reached)")
                finally:
                    task_queue.task_done()
        
        # Start worker threads
        import threading
        threads = []
        for _ in range(self.max_workers):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)
        
        # Wait for all tasks to complete
        task_queue.join()
        
        # Wait for all threads to finish
        for t in threads:
            t.join()
        
        print(f"\n✅ Stage 1 completed: {completed} succeeded, {failed} failed\n")
        
        # Final verification: Check all policy directories for completeness
        # This catches cases where directories were created but files were deleted (e.g., by post-hooks)
        print("Performing final verification of policy directories...")
        
        successful_policy_dirs = []
        
        if self.output_dir.exists():
            policy_dirs = [d for d in self.output_dir.iterdir()
                          if d.is_dir() and not d.name.startswith('.') and d.name != 'goals']
            
            incomplete_dirs = []
            for policy_dir in policy_dirs:
                if not self._verify_policy_directory(policy_dir):
                    incomplete_dirs.append(policy_dir)
                else:
                    # This directory is complete and can proceed to stage2
                    successful_policy_dirs.append(policy_dir.name)
            
            if incomplete_dirs:
                print(f"\n⚠️  Found {len(incomplete_dirs)} incomplete policy director{'y' if len(incomplete_dirs) == 1 else 'ies'}:")
                
                # Try to identify which goals these directories belong to
                for policy_dir in incomplete_dirs:
                    # Try to find the corresponding goal
                    goal_identified = False
                    for goal_file in goal_files:
                        identified_dir = self._identify_policy_directory_for_goal(goal_file)
                        if identified_dir and identified_dir == policy_dir:
                            goal_name = goal_file.stem
                            print(f"  - {policy_dir.name} (from {goal_file.name})")
                            
                            # Mark this goal as failed if it was previously successful
                            with results_lock:
                                if goal_name in results and results[goal_name][0]:
                                    # Was marked as success, but directory is incomplete
                                    results[goal_name] = (False, f"Policy directory {policy_dir.name} missing required files")
                                    completed -= 1
                                    failed += 1
                                    # Remove from goal_to_policy_dir mapping
                                    goal_to_policy_dir[goal_name] = None
                            
                            goal_identified = True
                            break
                    
                    if not goal_identified:
                        print(f"  - {policy_dir.name} (could not identify source goal)")
                
                print(f"\n⚠️  Stage 1 final status: {completed} succeeded, {failed} failed")
                print(f"✓ {len(successful_policy_dirs)} policy director{'y' if len(successful_policy_dirs) == 1 else 'ies'} will proceed to Stage 2\n")
        
        # Return success status and list of successful policy directories
        return (failed == 0, successful_policy_dirs)
    
    def _run_single_generation(self, policy_dir: str, index: int, total: int, retry: bool = False) -> Tuple[str, bool, str]:
        """
        Run policy generation for a single policy directory
        
        Args:
            policy_dir: Name of the policy directory
            index: Current index in processing
            total: Total number of policies
            retry: Whether this is a retry attempt
        
        Returns:
            Tuple of (policy_name, success, error_message)
        """
        log_suffix = "_retry" if retry else ""
        log_file = self.output_dir / policy_dir / f"stage2_generation{log_suffix}.log"
        
        retry_label = " (retry)" if retry else ""
        print(f"  [{index}/{total}] Processing{retry_label}: {policy_dir}")
        
        # Use configured timeout (1.5x for retry)
        timeout = int(self.stage2_timeout * 1.5) if retry else self.stage2_timeout
        if retry:
            print(f"  Using increased timeout for retry: {timeout}s (base: {self.stage2_timeout}s, multiplier: 1.5x)")
        success = self._run_docker_command(
            skill="step2-generation",
            prompt="",  # Not used when skill_args provided
            stage_name=f"Stage 2: Generation ({policy_dir}){retry_label}",
            container_suffix=f"{policy_dir.replace('/', '-')}{'-retry' if retry else ''}",
            log_file=log_file,
            timeout_seconds=timeout,
            skill_args=["--policy-dir", policy_dir]
        )
        
        if not success:
            return (policy_dir, False, "Execution failed")
        
        # Verify output even if exit code was 0
        policy_path = self.output_dir / policy_dir
        if not self._verify_stage2_output(policy_path):
            return (policy_dir, False, "Output verification failed")
        
        return (policy_dir, True, "")
    
    def stage2_generation(self, policy_dirs_filter: Optional[List[str]] = None) -> bool:
        """Stage 2: Generate policies and tests (parallel execution with priority retry)
        
        Args:
            policy_dirs_filter: Optional list of policy directory names to process.
                              If provided, only these directories will be processed.
                              If None, all policy directories will be processed.
        """
        from queue import PriorityQueue
        from threading import Lock
        
        # Get all policy directories
        all_policy_dirs = sorted([
            d.name for d in self.output_dir.iterdir()
            if d.is_dir() and d.name != "goals"
        ])
        
        # Apply filter if provided
        if policy_dirs_filter is not None:
            policy_dirs = [d for d in all_policy_dirs if d in policy_dirs_filter]
            skipped_dirs = [d for d in all_policy_dirs if d not in policy_dirs_filter]
            
            if skipped_dirs:
                print(f"\n⚠️  Skipping {len(skipped_dirs)} policy director{'y' if len(skipped_dirs) == 1 else 'ies'} that failed in Stage 1:")
                for skipped_dir in skipped_dirs:
                    print(f"  - {skipped_dir}")
                print()
        else:
            policy_dirs = all_policy_dirs
        
        if not policy_dirs:
            print("❌ No policy directories to process")
            return False
        
        print(f"\n{'='*80}")
        print(f"Stage 2: Policy Generation (Parallel)")
        print(f"{'='*80}")
        print(f"Found {len(policy_dirs)} policy/policies to process")
        print(f"Max workers: {self.max_workers}\n")
        
        # Priority queue: (priority, counter, policy_dir, index, is_retry)
        # Lower priority number = higher priority (0 = retry, 1 = initial)
        task_queue = PriorityQueue()
        task_counter = 0
        results: Dict[str, Tuple[bool, str]] = {}
        retry_count: Dict[str, int] = {}
        results_lock = Lock()
        
        # Add initial tasks to queue (priority=1 for initial tasks)
        for index, policy_dir in enumerate(policy_dirs, 1):
            task_queue.put((1, task_counter, policy_dir, index, False))
            task_counter += 1
            retry_count[policy_dir] = 0
        
        total_tasks = len(policy_dirs)
        completed = 0
        failed = 0
        
        # Worker function that processes tasks from the queue
        def worker():
            nonlocal completed, failed, task_counter
            
            while True:
                try:
                    # Get task from queue (blocks if empty)
                    priority, _, policy_dir, index, is_retry = task_queue.get(timeout=1)
                except:
                    # Queue is empty and timeout reached
                    break
                
                try:
                    # Execute the task
                    policy_name, success, error = self._run_single_generation(
                        policy_dir, index, total_tasks, retry=is_retry
                    )
                    
                    retry_label = " (retry)" if is_retry else ""
                    
                    with results_lock:
                        if success:
                            completed += 1
                            results[policy_name] = (success, error)
                            log_suffix = "_retry" if is_retry else ""
                            log_file = self.output_dir / policy_name / f"stage2_generation{log_suffix}.log"
                            print(f"  ✓ Completed{retry_label}: {policy_name} (log: {log_file})")
                        else:
                            # Check if we should retry
                            if retry_count[policy_dir] < self.max_retries:
                                # Add retry task with higher priority (0)
                                retry_count[policy_dir] += 1
                                print(f"  ✗ Failed{retry_label}: {policy_name} - {error}")
                                print(f"  ⟳ Queuing retry {retry_count[policy_dir]}/{self.max_retries} with high priority: {policy_name}")
                                task_queue.put((0, task_counter, policy_dir, index, True))
                                task_counter += 1
                            else:
                                # Max retries reached, mark as final failure
                                failed += 1
                                results[policy_name] = (success, error)
                                print(f"  ✗ Failed{retry_label}: {policy_name} - {error} (max retries {self.max_retries} reached)")
                finally:
                    task_queue.task_done()
        
        # Start worker threads
        import threading
        threads = []
        for _ in range(self.max_workers):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)
        
        # Wait for all tasks to complete
        task_queue.join()
        
        # Wait for all threads to finish
        for t in threads:
            t.join()
        
        print(f"\n✅ Stage 2 completed: {completed} succeeded, {failed} failed\n")
        
        return failed == 0
    
    def _run_single_fixtures(self, policy_dir: str, index: int, total: int, retry: bool = False) -> Tuple[str, bool, str]:
        """
        Run validation fixtures generation for a single policy directory
        
        Args:
            policy_dir: Name of the policy directory
            index: Current index in processing
            total: Total number of policies
            retry: Whether this is a retry attempt
        
        Returns:
            Tuple of (policy_name, success, error_message)
        """
        log_suffix = "_retry" if retry else ""
        log_file = self.output_dir / policy_dir / f"stage4_fixtures{log_suffix}.log"
        
        retry_label = " (retry)" if retry else ""
        print(f"  [{index}/{total}] Processing{retry_label}: {policy_dir}")
        
        # Use configured timeout (1.5x for retry)
        timeout = int(self.stage4_timeout * 1.5) if retry else self.stage4_timeout
        if retry:
            print(f"  Using increased timeout for retry: {timeout}s (base: {self.stage4_timeout}s, multiplier: 1.5x)")
        success = self._run_docker_command(
            skill="step4-validation-fixtures",
            prompt="",  # Not used when skill_args provided
            stage_name=f"Stage 4: Fixtures ({policy_dir}){retry_label}",
            container_suffix=f"{policy_dir.replace('/', '-')}-fixtures{'-retry' if retry else ''}",
            log_file=log_file,
            timeout_seconds=timeout,
            skill_args=["--policy-dir", policy_dir]
        )
        
        if not success:
            return (policy_dir, False, "Execution failed")
        
        # Verify output even if exit code was 0
        policy_path = self.output_dir / policy_dir
        if not self._verify_stage4_output(policy_path):
            return (policy_dir, False, "Output verification failed")
        
        return (policy_dir, True, "")
    
    def stage3_summary(self) -> bool:
        """Stage 3: Generate summary of all policies.

        Stage 3 can exit with code 0 without writing summary.json/summary.md, so a
        bounded retry is applied — matching the retry behaviour of Stages 1, 2 and 4.
        """
        print(f"\n{'='*80}")
        print(f"Stage 3: Summary Generation")
        print(f"{'='*80}\n")

        # Count policy directories to calculate dynamic timeout
        policy_count = len([d for d in self.output_dir.iterdir() if d.is_dir() and d.name != "goals"])
        # Use configured timeout: base + per-policy
        base_timeout = self.stage3_timeout_base + (policy_count * self.stage3_timeout_per_policy)

        total_attempts = self.max_retries + 1
        for attempt in range(total_attempts):
            is_retry = attempt > 0
            log_suffix = "_retry" if is_retry else ""
            log_file = self.output_dir / f"stage3_summary{log_suffix}.log"

            # Use increased timeout for retry (1.5x), same multiplier as Stage 2
            timeout_seconds = int(base_timeout * 1.5) if is_retry else base_timeout
            retry_label = " (retry)" if is_retry else ""
            if is_retry:
                print(f"  ⟳ Queuing retry {attempt}/{self.max_retries} for Stage 3")
                print(f"  Using increased timeout for retry: {timeout_seconds}s "
                      f"(base: {base_timeout}s, multiplier: 1.5x)")

            success = self._run_docker_command(
                skill="step3-summary",
                prompt="",
                stage_name=f"Stage 3: Summary Generation{retry_label}",
                container_suffix="retry" if is_retry else "",
                log_file=log_file,
                timeout_seconds=timeout_seconds
            )

            # Verify output even if exit code was 0
            if success and self._verify_stage3_output():
                return True

            if attempt < total_attempts - 1:
                print("\n⚠️  Stage 3 did not produce the required summary files, retrying...")

        print(f"\n❌ Stage 3 output verification failed after {total_attempts} attempt(s) "
              f"(max retries {self.max_retries} reached)")
        return False
    
    def stage4_fixtures(self, policy_dirs_filter: Optional[List[str]] = None) -> bool:
        """Stage 4: Generate validation fixtures (parallel execution with priority retry)
        
        Args:
            policy_dirs_filter: Optional list of policy directory names to process.
                              If provided, only these directories will be processed.
                              If None, all policy directories will be processed.
        """
        from queue import PriorityQueue
        from threading import Lock
        
        # Get all policy directories
        all_policy_dirs = sorted([
            d.name for d in self.output_dir.iterdir()
            if d.is_dir() and d.name != "goals"
        ])
        
        # Apply filter if provided
        if policy_dirs_filter is not None:
            policy_dirs = [d for d in all_policy_dirs if d in policy_dirs_filter]
            skipped_dirs = [d for d in all_policy_dirs if d not in policy_dirs_filter]
            
            if skipped_dirs:
                print(f"\n⚠️  Skipping {len(skipped_dirs)} policy director{'y' if len(skipped_dirs) == 1 else 'ies'} that failed in Stage 2:")
                for skipped_dir in skipped_dirs:
                    print(f"  - {skipped_dir}")
                print()
        else:
            policy_dirs = all_policy_dirs
        
        if not policy_dirs:
            print("❌ No policy directories to process")
            return False
        
        print(f"\n{'='*80}")
        print(f"Stage 4: Validation Fixtures Generation (Parallel)")
        print(f"{'='*80}")
        print(f"Found {len(policy_dirs)} policy/policies to process")
        print(f"Max workers: {self.max_workers}\n")
        
        # Priority queue: (priority, counter, policy_dir, index, is_retry)
        # Lower priority number = higher priority (0 = retry, 1 = initial)
        task_queue = PriorityQueue()
        task_counter = 0
        results: Dict[str, Tuple[bool, str]] = {}
        retry_count: Dict[str, int] = {}
        results_lock = Lock()
        
        # Add initial tasks to queue (priority=1 for initial tasks)
        for index, policy_dir in enumerate(policy_dirs, 1):
            task_queue.put((1, task_counter, policy_dir, index, False))
            task_counter += 1
            retry_count[policy_dir] = 0
        
        total_tasks = len(policy_dirs)
        completed = 0
        failed = 0
        
        # Worker function that processes tasks from the queue
        def worker():
            nonlocal completed, failed, task_counter
            
            while True:
                try:
                    # Get task from queue (blocks if empty)
                    priority, _, policy_dir, index, is_retry = task_queue.get(timeout=1)
                except:
                    # Queue is empty and timeout reached
                    break
                
                try:
                    # Execute the task
                    policy_name, success, error = self._run_single_fixtures(
                        policy_dir, index, total_tasks, retry=is_retry
                    )
                    
                    retry_label = " (retry)" if is_retry else ""
                    
                    with results_lock:
                        if success:
                            completed += 1
                            results[policy_name] = (success, error)
                            log_suffix = "_retry" if is_retry else ""
                            log_file = self.output_dir / policy_name / f"stage4_fixtures{log_suffix}.log"
                            print(f"  ✓ Completed{retry_label}: {policy_name} (log: {log_file})")
                        else:
                            # Check if we should retry
                            if retry_count[policy_dir] < self.max_retries:
                                # Add retry task with higher priority (0)
                                retry_count[policy_dir] += 1
                                print(f"  ✗ Failed{retry_label}: {policy_name} - {error}")
                                print(f"  ⟳ Queuing retry {retry_count[policy_dir]}/{self.max_retries} with high priority: {policy_name}")
                                task_queue.put((0, task_counter, policy_dir, index, True))
                                task_counter += 1
                            else:
                                # Max retries reached, mark as final failure
                                failed += 1
                                results[policy_name] = (success, error)
                                print(f"  ✗ Failed{retry_label}: {policy_name} - {error} (max retries {self.max_retries} reached)")
                finally:
                    task_queue.task_done()
        
        # Start worker threads
        import threading
        threads = []
        for _ in range(self.max_workers):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)
        
        # Wait for all tasks to complete
        task_queue.join()
        
        # Wait for all threads to finish
        for t in threads:
            t.join()
        
        print(f"\n✅ Stage 4 completed: {completed} succeeded, {failed} failed\n")
        
        return failed == 0
        
    def run_full_pipeline(self) -> bool:
        """
        Run the complete pipeline from start to finish
        
        Returns:
            True if all stages successful, False otherwise
        """
        print("\n" + "="*80)
        print("Terraform Policy Automation Agent Skills - Full Pipeline")
        print("="*80)
        print(f"Model: {self.model_name}")
        print(f"Container Prefix: {self.container_prefix}")
        print(f"Input: {self.input_dir}/{os.getenv('INPUT_FILE', 'policy_goal.txt')}")
        print(f"Max Workers: {self.max_workers}")
        print("="*80 + "\n")
        
        start_time = time.time()
        
        # Stage 0: Extraction
        stage0_start = time.time()
        if not self.stage0_extraction():
            print("\n❌ Pipeline failed at Stage 0")
            return False
        stage0_duration = time.time() - stage0_start
        
        # Stage 1: Requirement Generation (parallel)
        stage1_start = time.time()
        stage1_success, successful_policy_dirs = self.stage1_requirement()
        if not stage1_success:
            print("\n⚠️  Stage 1 had failures")
            if not successful_policy_dirs:
                print("❌ No policies succeeded in Stage 1, cannot proceed to Stage 2")
                return False
            print(f"✓ {len(successful_policy_dirs)} policy/policies succeeded and will proceed to Stage 2\n")
        stage1_duration = time.time() - stage1_start
        
        # Stage 2: Policy Generation (parallel) - only process successful policies from Stage 1
        stage2_start = time.time()
        stage2_success = self.stage2_generation(policy_dirs_filter=successful_policy_dirs)
        stage2_duration = time.time() - stage2_start
        if not stage2_success:
            print("\n⚠️  Stage 2 had failures, but continuing...")
        
        # Stage 3: Summary
        stage3_start = time.time()
        if not self.stage3_summary():
            print("\n❌ Pipeline failed at Stage 3")
            return False
        stage3_duration = time.time() - stage3_start
        
        # Stage 4: Validation Fixtures Generation (parallel) - only if enabled
        stage4_duration = 0
        if self.enable_stage4:
            # Get list of policies that succeeded in Stage 2
            stage2_successful_dirs = []
            for policy_dir in successful_policy_dirs:
                policy_path = self.output_dir / policy_dir
                if self._verify_stage2_output(policy_path):
                    stage2_successful_dirs.append(policy_dir)
            
            if stage2_successful_dirs:
                stage4_start = time.time()
                if not self.stage4_fixtures(policy_dirs_filter=stage2_successful_dirs):
                    print("\n⚠️  Stage 4 had failures, but continuing...")
                stage4_duration = time.time() - stage4_start
            else:
                print("\n⚠️  No policies succeeded in Stage 2, skipping Stage 4")
        else:
            print("\n⏭️  Stage 4 is disabled (set ENABLE_STAGE4=true to enable)")
        
        elapsed_time = time.time() - start_time
        
        print("\n" + "="*80)
        print("✅ Full pipeline completed!")
        print(f"Total time: {elapsed_time:.2f} seconds ({elapsed_time/60:.1f} minutes)")
        print("\n" + "-"*80)
        print("EXECUTION TIME BY STAGE")
        print("-"*80)
        print(f"Stage 0 duration: {stage0_duration:.2f} seconds")
        print(f"Stage 1 duration: {stage1_duration:.2f} seconds")
        print(f"Stage 2 duration: {stage2_duration:.2f} seconds")
        print(f"Stage 3 duration: {stage3_duration:.2f} seconds")
        if self.enable_stage4:
            print(f"Stage 4 duration: {stage4_duration:.2f} seconds")
        print("-"*80)
        print(f"\nLogs location:")
        print(f"  Stage 0: {self.output_dir}/stage0_extraction.log")
        print(f"  Stage 1: {self.goals_dir}/goal-*_stage1.log")
        print(f"  Stage 2: {self.output_dir}/<PolicyName>/stage2_generation.log")
        print(f"  Stage 3: {self.output_dir}/stage3_summary.log")
        if self.enable_stage4:
            print(f"  Stage 4: {self.output_dir}/<PolicyName>/stage4_fixtures.log")
        print("="*80 + "\n")
        

        # Collect token usage metrics from log files
        print("\n" + "="*80)
        print("TOKEN USAGE METRICS")
        print("="*80)
        
        # Stage 0: Extract from stage0_extraction.log
        stage0_log = self.output_dir / "stage0_extraction.log"
        stage0_tokens = self._extract_token_usage_from_log(str(stage0_log)) if stage0_log.exists() else {
            'total_tokens_in': 0, 'total_tokens_out': 0, 'total_cost': 0, 'cache_read': 0, 'cache_write': 0
        }
        print(f"Stage 0 tokens: {stage0_tokens['total_tokens_in']+stage0_tokens['total_tokens_out']:,} (In: {stage0_tokens['total_tokens_in']:,}, Out: {stage0_tokens['total_tokens_out']:,}, Cache Read: {stage0_tokens['cache_read']:,}, Cache Write: {stage0_tokens['cache_write']:,})")
        
        # Stage 1: Extract from all stage1_requirement_*.log files in goals directory
        stage1_logs = []
        if self.goals_dir.exists():
            stage1_logs = list(self.goals_dir.glob("*_stage1.log"))
        stage1_tokens = self._collect_stage_token_metrics("stage1", stage1_logs)
        print(f"Stage 1 tokens: {stage1_tokens['total_tokens_in']+stage1_tokens['total_tokens_out']:,} (In: {stage1_tokens['total_tokens_in']:,}, Out: {stage1_tokens['total_tokens_out']:,}, Cache Read: {stage1_tokens['cache_read']:,}, Cache Write: {stage1_tokens['cache_write']:,})")
        
        # Stage 2: Extract from all stage2_generation.log files in policy directories
        stage2_logs = []
        for policy_dir in self.output_dir.iterdir():
            if policy_dir.is_dir() and not policy_dir.name.startswith('.') and policy_dir.name != 'goals':
                stage2_log = policy_dir / "stage2_generation.log"
                if stage2_log.exists():
                    stage2_logs.append(stage2_log)
        stage2_tokens = self._collect_stage_token_metrics("stage2", stage2_logs)
        print(f"Stage 2 tokens: {stage2_tokens['total_tokens_in']+stage2_tokens['total_tokens_out']:,} (In: {stage2_tokens['total_tokens_in']:,}, Out: {stage2_tokens['total_tokens_out']:,}, Cache Read: {stage2_tokens['cache_read']:,}, Cache Write: {stage2_tokens['cache_write']:,})")
        
        # Stage 3: Extract from stage3_summary.log
        stage3_log = self.output_dir / "stage3_summary.log"
        stage3_tokens = self._extract_token_usage_from_log(str(stage3_log)) if stage3_log.exists() else {
            'total_tokens_in': 0, 'total_tokens_out': 0, 'total_cost': 0, 'cache_read': 0, 'cache_write': 0
        }
        print(f"Stage 3 tokens: {stage3_tokens['total_tokens_in']+stage3_tokens['total_tokens_out']:,} (In: {stage3_tokens['total_tokens_in']:,}, Out: {stage3_tokens['total_tokens_out']:,}, Cache Read: {stage3_tokens['cache_read']:,}, Cache Write: {stage3_tokens['cache_write']:,})")
        
        # Stage 4: Extract from all stage4_fixtures.log files in policy directories (if enabled)
        stage4_tokens = {'total_tokens_in': 0, 'total_tokens_out': 0, 'total_cost': 0, 'cache_read': 0, 'cache_write': 0}
        if self.enable_stage4:
            stage4_logs = []
            for policy_dir in self.output_dir.iterdir():
                if policy_dir.is_dir() and not policy_dir.name.startswith('.') and policy_dir.name != 'goals':
                    stage4_log = policy_dir / "stage4_fixtures.log"
                    if stage4_log.exists():
                        stage4_logs.append(stage4_log)
            stage4_tokens = self._collect_stage_token_metrics("stage4", stage4_logs)
            print(f"Stage 4 tokens: {stage4_tokens['total_tokens_in']+stage4_tokens['total_tokens_out']:,} (In: {stage4_tokens['total_tokens_in']:,}, Out: {stage4_tokens['total_tokens_out']:,}, Cache Read: {stage4_tokens['cache_read']:,}, Cache Write: {stage4_tokens['cache_write']:,})")
        
        # Calculate totals
        total_tokens_in = (stage0_tokens['total_tokens_in'] + stage1_tokens['total_tokens_in'] +
                            stage2_tokens['total_tokens_in'] + stage3_tokens['total_tokens_in'] +
                            stage4_tokens['total_tokens_in'])
        total_tokens_out = (stage0_tokens['total_tokens_out'] + stage1_tokens['total_tokens_out'] +
                            stage2_tokens['total_tokens_out'] + stage3_tokens['total_tokens_out'] +
                            stage4_tokens['total_tokens_out'])
        total_tokens = total_tokens_in + total_tokens_out
        total_cache_read = (stage0_tokens['cache_read'] + stage1_tokens['cache_read'] +
                            stage2_tokens['cache_read'] + stage3_tokens['cache_read'] +
                            stage4_tokens['cache_read'])
        total_cache_write = (stage0_tokens['cache_write'] + stage1_tokens['cache_write'] +
                             stage2_tokens['cache_write'] + stage3_tokens['cache_write'] +
                             stage4_tokens['cache_write'])
        total_cost = (stage0_tokens['total_cost'] + stage1_tokens['total_cost'] +
                        stage2_tokens['total_cost'] + stage3_tokens['total_cost'] +
                        stage4_tokens['total_cost'])
        
        print(f"\nTotal tokens: {total_tokens:,} (In: {total_tokens_in:,}, Out: {total_tokens_out:,})")
        print(f"Total cache: Cache Read: {total_cache_read:,}, Cache Write: {total_cache_write:,}")
        print(f"Total cost: ${total_cost:.2f}")
        
        # Save execution time and token metrics to JSON file
        total_duration = stage0_duration + stage1_duration + stage2_duration + stage3_duration + stage4_duration
        metrics_file = os.path.join(self.output_dir, 'execution_metrics.json')
        metrics_data = {
            'start_time': datetime.fromtimestamp(start_time).isoformat(),
            'end_time': datetime.now().isoformat(),
            'stage0_duration_seconds': stage0_duration,
            'stage1_duration_seconds': stage1_duration,
            'stage2_duration_seconds': stage2_duration,
            'stage3_duration_seconds': stage3_duration,
            'stage4_duration_seconds': stage4_duration,
            'total_duration_seconds': total_duration,
            'stage0_duration_formatted': self._format_duration(stage0_duration),
            'stage1_duration_formatted': self._format_duration(stage1_duration),
            'stage2_duration_formatted': self._format_duration(stage2_duration),
            'stage3_duration_formatted': self._format_duration(stage3_duration),
            'stage4_duration_formatted': self._format_duration(stage4_duration),
            'total_duration_formatted': self._format_duration(total_duration),
            'stage0_tokens_in': stage0_tokens['total_tokens_in'],
            'stage0_tokens_out': stage0_tokens['total_tokens_out'],
            'stage0_tokens': stage0_tokens['total_tokens_in'] + stage0_tokens['total_tokens_out'],
            'stage0_cache_read': stage0_tokens['cache_read'],
            'stage0_cache_write': stage0_tokens['cache_write'],
            'stage1_tokens_in': stage1_tokens['total_tokens_in'],
            'stage1_tokens_out': stage1_tokens['total_tokens_out'],
            'stage1_tokens': stage1_tokens['total_tokens_in'] + stage1_tokens['total_tokens_out'],
            'stage1_cache_read': stage1_tokens['cache_read'],
            'stage1_cache_write': stage1_tokens['cache_write'],
            'stage2_tokens_in': stage2_tokens['total_tokens_in'],
            'stage2_tokens_out': stage2_tokens['total_tokens_out'],
            'stage2_tokens': stage2_tokens['total_tokens_in'] + stage2_tokens['total_tokens_out'],
            'stage2_cache_read': stage2_tokens['cache_read'],
            'stage2_cache_write': stage2_tokens['cache_write'],
            'stage3_tokens_in': stage3_tokens['total_tokens_in'],
            'stage3_tokens_out': stage3_tokens['total_tokens_out'],
            'stage3_tokens': stage3_tokens['total_tokens_in'] + stage3_tokens['total_tokens_out'],
            'stage3_cache_read': stage3_tokens['cache_read'],
            'stage3_cache_write': stage3_tokens['cache_write'],
            'stage4_tokens_in': stage4_tokens['total_tokens_in'],
            'stage4_tokens_out': stage4_tokens['total_tokens_out'],
            'stage4_tokens': stage4_tokens['total_tokens_in'] + stage4_tokens['total_tokens_out'],
            'stage4_cache_read': stage4_tokens['cache_read'],
            'stage4_cache_write': stage4_tokens['cache_write'],
            'total_tokens_in': total_tokens_in,
            'total_tokens_out': total_tokens_out,
            'total_tokens': total_tokens,
            'total_cache_read': total_cache_read,
            'total_cache_write': total_cache_write,
            'total_cost': total_cost
        }
        with open(metrics_file, 'w', encoding='utf-8') as f:
            json.dump(metrics_data, f, indent=2, ensure_ascii=False)
        print(f"\nExecution metrics (with token usage) saved to: {metrics_file}")
        return True

    def _extract_execution_time_from_log(self, log_file: str) -> float:
        """
        Extract execution time from log file by finding first and last timestamps.
        Supports multiple timestamp formats.
        Returns time in seconds.
        """
        first_timestamp = None
        last_timestamp = None
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    timestamp = None
                    
                    # Try pattern 1: [YYYY-MM-DD HH:MM:SS]
                    match = re.search(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]', line)
                    if match:
                        timestamp_str = match.group(1)
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    
                    # Try pattern 2: Timestamp: YYYY-MM-DD HH:MM:SS
                    if not timestamp:
                        match = re.search(r'Timestamp:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if match:
                            timestamp_str = match.group(1)
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    
                    # Try pattern 3: Completed at: YYYY-MM-DD HH:MM:SS
                    if not timestamp:
                        match = re.search(r'Completed at:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if match:
                            timestamp_str = match.group(1)
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    
                    # Try pattern 4: Started at: YYYY-MM-DD HH:MM:SS
                    if not timestamp:
                        match = re.search(r'Started at:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if match:
                            timestamp_str = match.group(1)
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                    
                    if timestamp:
                        if first_timestamp is None:
                            first_timestamp = timestamp
                        last_timestamp = timestamp
            
            if first_timestamp and last_timestamp:
                duration = (last_timestamp - first_timestamp).total_seconds()
                return duration
        except Exception as e:
            print(f"  Error extracting execution time from {log_file}: {e}")
        
        return 0


    def _extract_token_usage_from_log(self, log_file: str) -> Dict:
        """
        Extract token usage from opencode stats section in log file.
        """
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Get last occurrence of stats section
            parts = content.split('Usage Statistics (opencode stats)')
            if len(parts) < 2:
                return {
                    'total_tokens_in': 0,
                    'total_tokens_out': 0,
                    'total_cost': 0.0,
                    'cache_read': 0,
                    'cache_write': 0
                }
            
            stats = parts[-1]
            
            # Parse Input (e.g., "│Input 196.6K │")
            input_match = re.search(r'│\s*Input\s+([\d.]+)([KMB]?)', stats)
            tokens_in = float(input_match.group(1)) * {'K': 1000, 'M': 1000000, 'B': 1000000000}.get(input_match.group(2), 1) if input_match else 0
            
            # Parse Output (e.g., "│Output 2.8K │")
            output_match = re.search(r'│\s*Output\s+([\d.]+)([KMB]?)', stats)
            tokens_out = float(output_match.group(1)) * {'K': 1000, 'M': 1000000, 'B': 1000000000}.get(output_match.group(2), 1) if output_match else 0
            
            # Parse Cache Read (e.g., "│Cache Read 245.4K │")
            cache_read_match = re.search(r'│\s*Cache Read\s+([\d.]+)([KMB]?)', stats)
            cache_read = float(cache_read_match.group(1)) * {'K': 1000, 'M': 1000000, 'B': 1000000000}.get(cache_read_match.group(2), 1) if cache_read_match else 0
            
            # Parse Cache Write (e.g., "│Cache Write 0 │")
            cache_write_match = re.search(r'│\s*Cache Write\s+([\d.]+)([KMB]?)', stats)
            cache_write = float(cache_write_match.group(1)) * {'K': 1000, 'M': 1000000, 'B': 1000000000}.get(cache_write_match.group(2), 1) if cache_write_match else 0
            
            # Parse Total Cost (e.g., "│Total Cost $0.02 │")
            cost_match = re.search(r'│\s*Total Cost\s+\$?([\d.]+)', stats)
            cost = float(cost_match.group(1)) if cost_match else 0.0
            
            return {
                'total_tokens_in': int(tokens_in),
                'total_tokens_out': int(tokens_out),
                'total_cost': cost,
                'cache_read': int(cache_read),
                'cache_write': int(cache_write)
            }
        except Exception as e:
            print(f"  Error reading log file {log_file}: {e}")
            return {
                'total_tokens_in': 0,
                'total_tokens_out': 0,
                'total_cost': 0.0,
                'cache_read': 0,
                'cache_write': 0
            }



    def _collect_stage_token_metrics(self, stage_name: str, log_files: List[Path]) -> Dict:
        """
        Aggregate token usage from multiple log files.
        
        Args:
            stage_name: Name of the stage (for logging purposes)
            log_files: List of log file paths to aggregate
            
        Returns:
            Dictionary with total_tokens_in, total_tokens_out, total_cost, cache_read, and cache_write
        """
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0
        total_cache_read = 0
        total_cache_write = 0
        
        for log_file in log_files:
            metrics = self._extract_token_usage_from_log(str(log_file))
            total_tokens_in += metrics['total_tokens_in']
            total_tokens_out += metrics['total_tokens_out']
            total_cost += metrics['total_cost']
            total_cache_read += metrics['cache_read']
            total_cache_write += metrics['cache_write']
        
        return {
            'total_tokens_in': total_tokens_in,
            'total_tokens_out': total_tokens_out,
            'total_cost': total_cost,
            'cache_read': total_cache_read,
            'cache_write': total_cache_write
        }

    def _format_duration(self, seconds: float) -> str:
        """Format duration in seconds to human-readable format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"


def main():
    """Main entry point"""
    # Get script directory (where run_pipeline.py is located)
    script_dir = Path(__file__).parent.resolve()
    
    # Create executor
    try:
        executor = PipelineExecutor(script_dir)
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    
    # Execute full pipeline
    success = executor.run_full_pipeline()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

# Made with Bob