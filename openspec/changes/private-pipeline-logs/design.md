# Design

- `DATA_DIR/.logs` is the log root. It is `lstat`ed (never followed): must be a real directory,
  owned by the current user, not group/other-writable; otherwise `ValueError` (fail loudly).
  Created 0700 if missing. Per run: `tempfile.mkdtemp(prefix="run-", dir=root)` (0700, unique).
- Overlap check (real paths, both directions) of the OUTPUT_DIR mount vs `.logs` runs first in
  `_validate_environment`, before any mkdir/Docker. `OUTPUT_DIR='.'` is therefore rejected;
  other absolute/nested OUTPUT_DIR values still work.
- Log names are host-generated and flat: `stage0.log`, `stage1_<idx>[_retry].log`,
  `stage2_<idx>[_retry].log`, `stage3[_retry].log`, `stage4_<idx>[_retry].log`,
  `execution_metrics.json`. `<idx>` is the numeric job index; policy/goal names are never joined.
- `_log_path()` is the single mapping; `_run_docker_command`, the stage-1 post-run appends,
  `_identify_policy_directory_for_goal(goal, log)`, and metrics collection (`_stage_logs`) all use it.
  Metrics keep counting only non-retry logs, as before.
- Invariants: no host open() of a path under OUTPUT_DIR for logging/metrics; concurrency, retries,
  reporting unchanged.
- Resume metrics: `_save_checkpoint(stage)` stores `_stage_tokens(stage)` (aggregated from the private
  logs via `_collect_stage_token_metrics`) as `stage<N>_tokens` in `DATA_DIR/.checkpoint/pipeline_checkpoint.json`.
  On resume, skipped stages use `_stored_stage_tokens` (validated numeric dict; otherwise zeros plus a
  warning that earlier logs are unavailable); executed stages use the current private logs. No paths
  are stored or imported and old logs are not copied.
- Review follow-ups: absolute `OUTPUT_DIR` is rejected (Python and shell; the shell mount is always
  `DATA_DIR/OUTPUT_DIR`). `OUTPUT_DIR` and `LOCAL_SKILLS_DIR` (when it is an existing directory) must not
  overlap `.logs` in either direction; checked in `run_pipeline.py` and in `run_with_local_preparation.sh`
  via `assert_not_overlapping_private_logs` (common.sh), so direct `--step` runs are protected too.
  `.logs` creation uses `mkdir(exist_ok=True)` then `lstat` validation.
- `skills/tfpac-run/scripts/result_check.py` reads only private logs: `--log-dir` for an exact run, else
  the newest valid real (non-symlink, owned, not group/other-writable) `run-*` under `.logs`; exits 1 when
  none is found.
