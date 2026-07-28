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
- Logs are written to `<command_name>.log` (e.g., `run.sh.log`, `run-crawler.sh.log`)
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

### For `generation` workflow:

Before presenting the confirmation request, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** Container(s) with prefix `{CONTAINER_PREFIX}` are already running. It is recommended to stop them or wait until they finish before proceeding.

```bash
nohup ./run.sh local > run.sh.log 2>&1 & echo $!
```

### For `generation_with_crawler` workflow:

First run the crawler to extract and add policy specifications to the database.

Before presenting the confirmation request for `./run-crawler.sh add`, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CRAWLER_CONTAINER_PREFIX:-crawler-agent}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** A container with name `{CRAWLER_CONTAINER_PREFIX}` is already running. It is recommended to stop it or wait until it finishes before proceeding.

```bash
nohup ./run-crawler.sh add > run-crawler.sh.log 2>&1 & echo $!
```

**Ask the user: "Please review the generated delta file in `crawler/report/delta/` and verify the policy information to be added is correct. May I proceed to update `crawler/crawler_goal.txt` with the delta file path and apply? (Yes/No)"**

After receiving Yes confirmation, update the file. Before presenting the confirmation request for `./run-crawler.sh apply`, run the same crawler prefix check above and include any warning, then execute:

```bash
nohup ./run-crawler.sh apply > run-crawler.sh.log 2>&1 & echo $!
```

**⚠️ CRITICAL: After crawler execution, you MUST run the policy generation pipeline. Do not forget this step!**

Then run the policy generation pipeline. Before presenting the confirmation request for `./run.sh local`, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** Container(s) with prefix `{CONTAINER_PREFIX}` are already running. It is recommended to stop them or wait until they finish before proceeding.

```bash
nohup ./run.sh local > run.sh.log 2>&1 & echo $!
```

### For `conversion_local` workflow:

Before presenting the confirmation request, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** Container(s) with prefix `{CONTAINER_PREFIX}` are already running. It is recommended to stop them or wait until they finish before proceeding.

```bash
nohup ./run.sh local > run.sh.log 2>&1 & echo $!
```

### For `conversion_external` workflow:

Before presenting the confirmation request, check:
```bash
docker ps --format '{{.Names}}' | grep "^${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
```
If containers are found, include this warning in the confirmation message:
> ⚠️ **Warning:** Container(s) with prefix `{CONTAINER_PREFIX}` are already running. It is recommended to stop them or wait until they finish before proceeding.

```bash
nohup ./run.sh external > run.sh.log 2>&1 & echo $!
```

This executes all 4 stages in sequence:

- Stage 0: Policy Extraction
- Stage 1: Requirement Generation
- Stage 2: Policy Generation
- Stage 3: Summary Generation

The run may take around 10 minutes depending on model latency and the number of policies.

## Monitoring Progress

**NOTE: This monitoring process applies to both `./run.sh` execution and both `./run-crawler.sh` executions (add and apply). Monitor each command separately using the same process described below.**

### During execution:

After starting the pipeline in background mode, ask the user how often they want progress reports:

**"How often would you like to receive progress reports? (in seconds) [default: 60]"**

Provide ONLY these clickable suggestions: 30, 60 (default), 90, custom input.

Then repeat the following cycle:
1. Sleep for the specified interval (use `sleep <seconds>` command - do not count manually)
2. Read the last few lines of log files in `DATA_DIR/OUTPUT_DIR` or `crawler/log` (only for crawler execution) to understand what's happening. Some stages may have multiple log files (e.g., Stage 1 has multiple goal files). Read the last few lines from each relevant log file. If there's only one log file, read that one.
   - For `crawler/log`: `crawler_{timestamp}` files are the main execution logs, and `guide_{timestamp}` files are logs for generating next-step guidance for the user. When multiple `crawler_*` or `guide_*` logs exist, only report on the files with the most recent timestamp.
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