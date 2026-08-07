# Verify Output

Use this guide after the pipeline has run.

## Goal

Verify whether the pipeline succeeded and answer questions using generated artifacts under `DATA_DIR/OUTPUT_DIR`.

## Checklist

```text
Terraform PAC verification progress:
- [ ] Inspect DATA_DIR/OUTPUT_DIR structure
- [ ] Review stage logs
- [ ] Check summary files
- [ ] Identify generated policies
- [ ] Answer user questions from actual output
```

## What to review

Inspect the following when they exist:

- `DATA_DIR/OUTPUT_DIR/stage0_extraction.log`
- `DATA_DIR/OUTPUT_DIR/goals/goal-*_stage1.log`
- `DATA_DIR/OUTPUT_DIR/<PolicyName>/stage2_generation.log`
- `DATA_DIR/OUTPUT_DIR/stage3_summary.log`
- `DATA_DIR/OUTPUT_DIR/summary.md`
- `DATA_DIR/OUTPUT_DIR/summary.json`
- relevant generated `report.md`, `requirement.txt`, `.hcl`, `.tf`, and `gwt.json` files

Use the helper script for a first-pass summary:

**For `conversion_external` workflow:**
First, identify the output directory name (format: `output-{timestamp}`), then specify it:
```bash
python3 skills/tfpac-run/scripts/result_check.py output-{timestamp}
```

**For other workflows:**
```bash
python3 skills/tfpac-run/scripts/result_check.py
```

Prefer `summary.json` as the structured source when generating a user-facing summary table.
Use `summary.md` as a human-readable cross-check, not the only output.

## Verification procedure

1. Inspect the `DATA_DIR/OUTPUT_DIR` directory structure first.
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

If the workflow is Sentinel conversion (conversion_local or conversion_external) and possible, infer Sentinel correspondence from `source`, `policy_file_path`, related requirement files, or the original input context, and mention it in surrounding text. Do not add a Limitation column by default.

**For `conversion_external` workflow:**
After postprocess, the deployed files are under `EXTERNAL_REPO_DIR`. Use these paths when referencing generated artifacts:
- `EXTERNAL_REPO_DIR/<sentinel_dir>/tfpolicy/<sentinel_basename>/<sentinel_basename>.policy.hcl`
- `EXTERNAL_REPO_DIR/<sentinel_dir>/tfpolicy/<sentinel_basename>/<sentinel_basename>.policytest.hcl`
- `EXTERNAL_REPO_DIR/<sentinel_dir>/tfpolicy/<sentinel_basename>/<sentinel_basename>.tf`
- `EXTERNAL_REPO_DIR/<sentinel_dir>/tfpolicy/<sentinel_basename>/<sentinel_basename>.report.md`

Use the deployed paths (not `DATA_DIR/output-<timestamp>/`) when citing file locations to the user.

Example shape:

```md
| Policy Name | Source | Status | Total test cases | Passed | Failed |
|-------------|--------|--------|------------------|--------|--------|
| CloudFront_Associated_WAF | AWS Security Hub (CloudFront.6) | ✅ Success | 5 | 5 | 0 |
```

File reference example (`conversion_external`):
```
EXTERNAL_REPO_DIR/path/to/tfpolicy/cloudfront_associated_waf/cloudfront_associated_waf.policy.hcl
```

## Rules

- Prefer stage logs over console-only output.
- If files are large, inspect only relevant sections.
- Do not claim success if any critical stage failed.