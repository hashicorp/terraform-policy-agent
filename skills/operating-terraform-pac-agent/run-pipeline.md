# Run Pipeline

Use this guide after prerequisites are confirmed.

## Goal

Run the full Terraform Policy Automation pipeline and capture enough context for later verification.

Before execution:
- ask the user whether they want to run the pipeline in the foreground or background
- check whether `data/input` or `data/output` already contains files from a previous run
- if prior files exist, ask whether to keep them, move them aside, or clean them up before starting

Do not choose execution mode or cleanup behavior silently if the user has not indicated a preference.

## Checklist

```text
Terraform PAC run progress:
- [ ] Confirm prerequisites are complete
- [ ] Confirm input file is ready
- [ ] Check whether data/input or data/output already contains prior files
- [ ] If prior files exist, ask whether to keep, move, or clean them
- [ ] Ask whether to run in foreground or background
- [ ] Run ./run.sh with the chosen mode
- [ ] Capture or reference console output
- [ ] Point user to data/output logs
```

## Execution

Run the full pipeline from the repository root.

Before execution, inspect `data/input` and `data/output`.

If either directory already contains files from a previous run, ask the user how to proceed:
- keep existing files as-is
- move them aside to a backup location
- clean them up before starting

Do not delete or move existing user files without explicit confirmation.

After that, ask the user to choose one of these execution modes.

### Foreground mode

Use this when the user wants to watch progress interactively:

```bash
./run.sh
```

If you want to capture console output for later inspection:

```bash
./run.sh | tee run.log
```

### Background mode

Use this when the user wants the pipeline to continue running without occupying the terminal:

```bash
nohup ./run.sh > run.log 2>&1 & echo $!
```

This returns the PID of the background shell process and writes stdout and stderr to `run.log`.

When using background mode, tell the user:
- where logs are written
- that they can inspect progress with `tail -f run.log`
- that `./stop.sh` can be used as a container cleanup fallback

This executes all 4 stages in sequence:

- Stage 0: Policy Extraction
- Stage 1: Requirement Generation
- Stage 2: Policy Generation
- Stage 3: Summary Generation

The run may take around 10 minutes depending on model latency and the number of policies.

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

The number of generated policy directories should roughly correspond to the number of extracted goals.

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

Preferred behavior:
- If the user started `./run.sh` directly, stopping that process should trigger its cleanup trap and stop the container.
- If the user started the full Python pipeline, stopping the parent process should allow its cleanup handler to stop tracked containers.

Fallback behavior:
- If the user wants to stop running Terraform PAC containers directly, use:

```bash
./stop.sh
```

This stops running containers whose names start with `terraform-pac-agent-skills`.

Optional variants:

```bash
./stop.sh --force
./stop.sh terraform-pac-agent-skills
```

Use `stop.sh` as a cleanup fallback when the original process is no longer easy to control or when containers remain running unexpectedly.