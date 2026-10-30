# Tasks

- [x] Add overlap check, private run dir creation, `_log_path`/`_stage_logs` to `run_pipeline.py`
- [x] Route stage0-4 + retry logs, stage1 appends, policy identification and metrics through private dir
- [x] Move `execution_metrics.json` to the private dir
- [x] Regression tests (`tests/test_private_logs.py`)
- [x] Update README / USER_GUIDE / CHANGELOG
- [x] Run `python3 -m unittest`, `bash -n`, `./pre-check.sh` (if feasible)
- [x] Persist per-stage token aggregates in checkpoint; resume reports use them (legacy checkpoint warns)
- [x] Resume/normal/legacy metrics tests; stage-1 symlink swap during mocked Popen
- [x] Oracle review follow-ups: result_check/skills docs, absolute OUTPUT_DIR + LOCAL_SKILLS_DIR overlap guards (Python+shell), mkdir race, metrics sentinel test
- [x] Oracle final code re-review approved before publication
