# Run Pipeline

**⚠️ IMPORTANT: Execute ALL instructions in this file step by step as written. Do not skip any steps.**

**⚠️ IMPORTANT: Commands in this pipeline may take significant time to complete. Do not kill or interrupt running commands prematurely. Wait for each command to finish naturally before proceeding.**

**⚠️ IMPORTANT: After completing all steps in this file, proceed to [verify.md](verify.md) for output verification.**

Use this guide after prerequisites are confirmed.

## Goal

Run the full Terraform Policy Automation pipeline and capture enough context for later verification.

## Execution Mode

**All commands should be executed in background mode to avoid occupying the terminal.**

Use this pattern for all pipeline commands:
```bash
nohup <command> > <command_name>.log 2>&1 & echo $!
```

This returns the PID of the background shell process and writes stdout and stderr to a log file named after the command.

When using background mode, inform the user:
- Logs are written to `<command_name>.log` (e.g., `run.sh.log`)
- They can inspect progress with `tail -f <command_name>.log`
- `./stop.sh` can be used as a container cleanup fallback

## Execution

Run the full pipeline from the repository root.

**⚠️ IMPORTANT: The following `DATA_DIR/OUTPUT_DIR` directory check should be performed for ALL workflows EXCEPT `conversion_external`. Skip this check entirely if the user selected the `conversion_external` workflow.**

Before execution (except for `conversion_external` workflow), inspect `DATA_DIR/OUTPUT_DIR`:
```bash
ls -la DATA_DIR/OUTPUT_DIR
```

If the directory already contains files from a previous run, ask the user how to proceed:
- keep existing files as-is
- move them aside to a backup location (`DATA_DIR/OUTPUT_DIR_backup_{timestamp}`) and delete the original `DATA_DIR/OUTPUT_DIR` contents
- clean them up before starting

Do not delete or move existing user files without explicit confirmation.

After that (or immediately for `conversion_external`), execute the appropriate command based on the selected workflow:

**NOTE: Before executing any command, always ask the user for confirmation. When asking for permission, first run the applicable `docker ps` check below and include any warning in the same confirmation message. Wait for explicit approval (e.g., "yes" or "no") before running it. Do not execute commands without user consent.**

### For `conversion_local` workflow:

Before presenting the confirmation request, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** Container(s) with prefix `{CONTAINER_PREFIX}` are already running. It is recommended to stop them or wait until they finish before proceeding.

#### Normal mode (no `--policy` flag):

```bash
nohup ./run.sh --no-confirm local > /dev/null 2>&1 & echo $!
```

#### Single-policy mode (`SINGLE_POLICY_MODE=true`):

**Step 1 — resolve LOG_DIR**

Read `DATA_DIR` from `.env`:
```bash
python3 skills/tfpac-run/scripts/dotenv_tool.py .env
```

Compute `<LOG_DIR>` as: `DATA_DIR/log`.

**Step 2 — resolve placeholders**

- `<GOAL_FILE>`: List files under `DATA_DIR/OUTPUT_DIR/goals/`. Read the contents of each `goal-?.txt` file, then select the filename (not the full path) whose content most closely matches the conversion intent of `POLICY_NAME`.
- `<POLICY_DIR>`: List directories directly under `DATA_DIR/OUTPUT_DIR/` that contain both `requirement.txt` and `report.md`. Find the one that most closely matches `POLICY_NAME` — first by directory name similarity, then if ambiguous, by reading `requirement.txt` and `report.md`. Use only the directory name (not the full path).

**Step 3 — run pipeline steps (log files go under LOG_DIR)**

Execute each step in order, waiting for completion before proceeding:

```bash
nohup ./run.sh --no-confirm local --step 0 > <LOG_DIR>/run.sh-step0.log 2>&1 & echo $!
```
```bash
nohup ./run.sh --no-confirm local --step 1 --goal-file <GOAL_FILE> > <LOG_DIR>/run.sh-step1.log 2>&1 & echo $!
```
```bash
nohup ./run.sh --no-confirm local --step 2 --policy-dir <POLICY_DIR> > <LOG_DIR>/run.sh-step2.log 2>&1 & echo $!
```
```bash
nohup ./run.sh --no-confirm local --step 3 > <LOG_DIR>/run.sh-step3.log 2>&1 & echo $!
```

### For `conversion_external` workflow:

Before presenting the confirmation request, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** Container(s) with prefix `{CONTAINER_PREFIX}` are already running. It is recommended to stop them or wait until they finish before proceeding.

#### Normal mode (no `--policy` flag):

```bash
nohup ./run.sh --no-confirm external > /dev/null 2>&1 & echo $!
```

This executes all 4 stages in sequence:

- Stage 0: Policy Extraction
- Stage 1: Requirement Generation
- Stage 2: Policy Generation
- Stage 3: Summary Generation

The run may take around 10 minutes depending on model latency and the number of policies.

#### Single-policy mode (`SINGLE_POLICY_MODE=true`):

Execute in order:

**Step 1 — preprocess**
```bash
./run.sh --no-confirm external --phase preprocess
```

**Step 2 — resolve env vars (DATA_DIR / INPUT_DIR / OUTPUT_DIR)**

After preprocess completes, run:
```bash
python3 skills/tfpac-run/scripts/set_env_for_external_mode.py .env
```

This script:
- Finds the latest `input-<timestamp>` and `output-<timestamp>` directories under `DATA_DIR`
- Updates `DATA_DIR`, `INPUT_DIR`, `OUTPUT_DIR`, `INPUT_FILE` in `.env`
- Prints JSON with resolved values including `log_dir` (use this as `<LOG_DIR>` below)

**Step 3 — resolve placeholders**

Resolve placeholders using the result of `set_env_for_external_mode.py`:
- `<LOG_DIR>`: the `log_dir` value from the script output above
- `<GOAL_FILE>`: List files under `DATA_DIR/OUTPUT_DIR/goals/`. Read the contents of each `goal-?.txt` file, then select the filename (not the full path) whose content most closely matches the conversion intent of `POLICY_NAME`.
- `<POLICY_DIR>`: List directories directly under `DATA_DIR/OUTPUT_DIR/` that contain both `requirement.txt` and `report.md`. Find the one that most closely matches `POLICY_NAME` — first by directory name similarity, then if ambiguous, by reading `requirement.txt` and `report.md`. Use only the directory name (not the full path).

**Step 4 — run pipeline steps (log files go under LOG_DIR)**
```bash
nohup ./run.sh --no-confirm local --step 0 > <LOG_DIR>/run.sh-step0.log 2>&1 & echo $!
```
```bash
nohup ./run.sh --no-confirm local --step 1 --goal-file <GOAL_FILE> > <LOG_DIR>/run.sh-step1.log 2>&1 & echo $!
```
```bash
nohup ./run.sh --no-confirm local --step 2 --policy-dir <POLICY_DIR> > <LOG_DIR>/run.sh-step2.log 2>&1 & echo $!
```
```bash
nohup ./run.sh --no-confirm local --step 3 > <LOG_DIR>/run.sh-step3.log 2>&1 & echo $!
```

**Step 5 — postprocess**
```bash
./run.sh --no-confirm external --phase postprocess
```

## Monitoring Progress

### During execution:

After starting the `nohup` command in background mode, ask the user how often they want progress reports:

**"How often would you like to receive progress reports? (in seconds) [default: 60]"**

Provide ONLY these clickable suggestions: 30, 60 (default), 90, custom input.

Then repeat the following cycle:
1. Sleep for the specified interval (use `sleep <seconds>` command - do not count manually)
2. Read the last few lines of log files in `DATA_DIR/OUTPUT_DIR` to understand what's happening. Some stages may have multiple log files (e.g., Stage 1 has multiple goal files). Read the last few lines from each relevant log file. If there's only one log file, read that one.
3. Summarize the current activity based on what you read from the logs. Report only facts from the log content, avoid speculation or assumptions.
4. Always include the total line count: `Log line count total: <sum of all log file line counts>`
   - **Note:** This metric is essential to quantitatively show the user how much progress has been made and confirm that execution is actually progressing.

### When background execution completes:

When you determine from the log status that execution has completed, inform the user that execution has finished and proceed to the next step.

## Expected outputs

Generated files appear under `DATA_DIR/OUTPUT_DIR`.

Typical outputs include:

- `DATA_DIR/OUTPUT_DIR/goals/`
- `DATA_DIR/OUTPUT_DIR/<PolicyName>/requirement.txt`
- `DATA_DIR/OUTPUT_DIR/<PolicyName>/*.hcl`
- `DATA_DIR/OUTPUT_DIR/<PolicyName>/*.tf`
- `DATA_DIR/OUTPUT_DIR/<PolicyName>/report.md`
- `DATA_DIR/OUTPUT_DIR/summary.md`
- `DATA_DIR/OUTPUT_DIR/summary.json`

## Logs

Prefer stage logs under `DATA_DIR/OUTPUT_DIR`:

- `DATA_DIR/OUTPUT_DIR/stage0_extraction.log`
- `DATA_DIR/OUTPUT_DIR/goals/goal-*_stage1.log`
- `DATA_DIR/OUTPUT_DIR/<PolicyName>/stage2_generation.log`
- `DATA_DIR/OUTPUT_DIR/stage3_summary.log`

`run.log` is optional and useful, but stage logs are the primary source of truth.

## Failure handling

If execution fails:

1. Identify the stage that failed.
2. Read the corresponding log file.
3. Report the exact error or failure point.
4. Do not claim the pipeline completed successfully if a critical stage failed.

## Stopping a running pipeline

If you need to stop running Terraform PAC containers, use:

```bash
./stop.sh prefix_name
```

This stops running containers whose names start with prefix_name.

Optional variants:

```bash
./stop.sh --force
```

Use `stop.sh` as a cleanup fallback when the original process is no longer easy to control or when containers remain running unexpectedly. See "Verifying container cleanup after stopping" below for post-stop verification steps.

### Verifying container cleanup after stopping

After stopping the pipeline (whether by user request or command interruption), always verify that no containers remain running.

At first, check the value of `CONTAINER_PREFIX` value (target container prefix):

```bash
python3 skills/tfpac-run/scripts/dotenv_tool.py .env
```

Verify no containers with that prefix are still running:

```bash
docker ps | grep {ACTUAL CONTAINER_PREFIX}
```

If `CONTAINER_PREFIX` is not set, use the default `terraform-pac-agent-skills`:

```bash
docker ps | grep terraform-pac-agent-skills
```

If any containers are still running:

1. **Inform the user**: Report that residual containers were found and explain that they should be cleaned up to avoid wasting resources.
2. **Ask for permission**: Request explicit user confirmation before proceeding with cleanup, showing the command using ./stop.sh prefix_name (e.g., "May I execute the following cleanup command to remove these unnecessary containers? command: {ACTUAL COMMAND HERE}").
3. **Stop remaining containers**: Once approved, execute the stop command.

**NOTE: Retry processes may start after stopping.** After executing the stop command, wait a few seconds and re-check with `docker ps | grep {CONTAINER_PREFIX}` to ensure no retry containers have started. If any containers are still running, repeat the stop command until all containers are confirmed stopped.

4. **Ask next action**: After cleanup, ask the user whether to retry the command or end the process.
   - If the user chooses to retry, first check `DATA_DIR/OUTPUT_DIR` again with `ls -la DATA_DIR/OUTPUT_DIR`, and if the directory contains files, ask how to handle them (keep, backup, or cleanup) before retrying the pipeline command.

This verification step ensures a clean state and prevents resource waste from orphaned containers.