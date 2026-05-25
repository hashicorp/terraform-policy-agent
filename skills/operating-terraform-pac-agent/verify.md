# Verify Output

Use this guide after the pipeline has run.

## Goal

Verify whether the pipeline succeeded and answer questions using generated artifacts under `data/output`.

## Checklist

```text
Terraform PAC verification progress:
- [ ] Inspect data/output structure
- [ ] Review stage logs
- [ ] Check summary files
- [ ] Identify generated policies
- [ ] Answer user questions from actual output
```

## What to review

Inspect the following when they exist:

- `data/output/stage0_extraction.log`
- `data/output/goals/goal-*_stage1.log`
- `data/output/<PolicyName>/stage2_generation.log`
- `data/output/stage3_summary.log`
- `data/output/summary.md`
- `data/output/summary.json`
- relevant generated `report.md`, `requirement.txt`, `.hcl`, `.tf`, and `gwt.json` files

Use the helper script for a first-pass summary:

```bash
python3 skills/operating-terraform-pac-agent/scripts/precheck_tool.py --summarize-output
```

Prefer `summary.json` as the structured source when generating a user-facing summary table.
Use `summary.md` as a human-readable cross-check, not the only output.

## Verification procedure

1. Inspect the `data/output` directory structure first.
2. Check whether `summary.md` and `summary.json` exist.
3. Review stage logs for failures or warnings.
4. Look for error indicators such as:
   - `ERROR`
   - `Error`
   - `failed`
   - `timed out`
   - `Traceback`
   - non-zero exit indications
5. If `summary.json` exists, extract a concise table for the user.
6. Identify generated policy directories and summarize what was produced.
7. If the user asks about a specific policy, answer from the generated files rather than assumptions.

## Reporting

Provide a concise verification summary with:

- overall pipeline status
- generated artifacts
- detected failures or warnings
- references to specific log files
- direct answers to the user’s questions

When `summary.json` is available, include a compact markdown table with these columns:

- Policy Name
- Source
- Status
- Total test cases
- Passed
- Failed

If possible, infer Sentinel correspondence from `source`, `policy_file_path`, related requirement files, or the original input context, and mention it in surrounding text. Do not add a Limitation column by default.

Example shape:

```md
| Policy Name | Source | Status | Total test cases | Passed | Failed |
|-------------|--------|--------|------------------|--------|--------|
| CloudFront_Associated_WAF | AWS Security Hub (CloudFront.6) | ✅ Success | 5 | 5 | 0 |
```

## Rules

- Prefer stage logs over console-only output.
- `run.log` may help, but it is not the primary source of truth.
- If files are large, inspect only relevant sections.
- Do not claim success if any critical stage failed.