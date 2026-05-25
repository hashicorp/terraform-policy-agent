---
name: operating-terraform-pac-agent
description: Operates the Terraform Policy Automation agent end to end. Use when checking prerequisites, preparing input guidance, running ./run.sh, reviewing data/output logs, or answering questions about generated Terraform policy artifacts.
---

# Operating Terraform PAC Pipeline

Use this skill when working with the Terraform Policy Automation pipeline in this repository.

Follow this workflow in order:

1. Prerequisite check
2. Pipeline execution
3. Output verification

Keep the user informed about the current step and do not skip prerequisite validation.

## Workflow

### Step 1: Prerequisite check

Read [prereq.md](prereq.md).

Use the helper scripts when useful:

- `python3 skills/operating-terraform-pac-agent/scripts/dotenv_tool.py .env`
- `python3 skills/operating-terraform-pac-agent/scripts/precheck_tool.py`

If prerequisites are not satisfied, stop and tell the user exactly what must be fixed.

### Step 2: Run pipeline

Read [run-pipeline.md](run-pipeline.md).

Only run the pipeline after prerequisites and input are confirmed.

### Step 3: Verify output

Read [verify.md](verify.md).

Inspect generated files under `data/output`, review stage logs, and answer the user using the actual output files.

## Notes

- Prefer stable binary paths in `.env`. On macOS, avoid `/tmp` for mounted binaries when possible.
- Prefer stage log files under `data/output` over console-only output.
- If a file is large, inspect only the relevant sections.
- Do not claim success if any critical stage failed.