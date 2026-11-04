# Tests

Standard library only (`unittest`); no real container engine or model is used (fake engine/binaries).
Run from the repository root:

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests
bash -n common.sh run_with_local_preparation.sh
```

- `test_private_logs.py`, `test_private_copy.py`, `test_private_core_review.py`: orchestrator private logs, safe copy/checkpoint, path validation.
- `test_direct_step_logs.py`: direct `--step` shell runs and their private log.
- `test_private_shell_review.py`: OUTPUT_DIR/DATA_DIR guards, skills/output overlap before mkdir, backup checks, stage headers.
- `test_private_reader_review.py`: `result_check.py` env precedence and `--log-dir` validation.

These do not exercise a real Docker/Podman engine or an LLM.
