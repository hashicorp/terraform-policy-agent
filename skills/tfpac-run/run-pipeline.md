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
- Logs are written to `<command_name>.log` (e.g., `run.sh.log`, `run_crawler.sh.log`)
- They can inspect progress with `tail -f <command_name>.log`
- `./stop.sh` can be used as a container cleanup fallback

## Execution

Run the full pipeline from the repository root.

**⚠️ IMPORTANT: The following `data/output` directory check should be performed for ALL workflows EXCEPT `conversion_external`. Skip this check entirely if the user selected the `conversion_external` workflow.**

Before execution (except for `conversion_external` workflow), inspect `data/output`:
```bash
ls -la data/output
```

If the directory already contains files from a previous run, ask the user how to proceed:
- keep existing files as-is
- move them aside to a backup location (`data/output_backup_{timestamp}`) and delete the original `data/output` contents
- clean them up before starting

Do not delete or move existing user files without explicit confirmation.

After that (or immediately for `conversion_external`), execute the appropriate command based on the selected workflow:

**NOTE: Before executing any command, always ask the user for confirmation. Present the command that will be executed and wait for explicit approval (e.g., "yes" or "no") before running it. Do not execute commands without user consent.**

### For `conversion_local` workflow:

```bash
nohup ./run.sh local > run.sh.log 2>&1 & echo $!
```

### For `conversion_external` workflow:

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

### During execution:

After starting the pipeline in background mode, ask the user how often they want progress reports:

**"How often would you like to receive progress reports? (in seconds) [default: 60]"**

Provide ONLY these clickable suggestions: 30, 60 (default), 90, custom input.

Then repeat the following cycle:
1. Sleep for the specified interval (use `sleep <seconds>` command - do not count manually)
2. Read the last few lines of log files in `data/output` to understand what's happening. Some stages may have multiple log files (e.g., Stage 1 has multiple goal files). Read the last few lines from each relevant log file. If there's only one log file, read that one.
3. Summarize the current activity based on what you read from the logs. Report only facts from the log content, avoid speculation or assumptions.
4. Always include the total line count: `Log line count total: <sum of all log file line counts>`
   - **Note:** This metric is essential to quantitatively show the user how much progress has been made and confirm that execution is actually progressing.

### When background execution completes:

When you determine from the log status that execution has completed, inform the user that execution has finished and proceed to the next step.

## Expected outputs

Generated files appear under `data/output`.

Typical outputs include:

- `data/output/goals/`
- `data/output/<PolicyName>/requirement.txt`
- `data/output/<PolicyName>/*.hcl`
- `data/output/<PolicyName>/*.tf`
- `data/output/<PolicyName>/report.md`
- `data/output/summary.md`
- `data/output/summary.json`

## Logs

Prefer stage logs under `data/output`:

- `data/output/stage0_extraction.log`
- `data/output/goals/goal-*_stage1.log`
- `data/output/<PolicyName>/stage2_generation.log`
- `data/output/stage3_summary.log`

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
python3 skills/tfpac-run/dotenv_tool.py .env
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
   - If the user chooses to retry, first check `data/output` again with `ls -la data/output`, and if the directory contains files, ask how to handle them (keep, backup, or cleanup) before retrying the pipeline command.

This verification step ensures a clean state and prevents resource waste from orphaned containers.