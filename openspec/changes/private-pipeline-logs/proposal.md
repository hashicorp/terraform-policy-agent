# Proposal: private pipeline logs

## Problem
`run_pipeline.py` opened stage logs (`open(..., 'w'/'a')`) and `execution_metrics.json` inside
`OUTPUT_DIR`, which is mounted read-write into the agent container. A container (or prompt-injected
agent) can pre-plant e.g. `Policy/stage2_generation.log -> /host/file`; the host then truncates or
appends to the symlink target.

## Change
All host-written logs and `execution_metrics.json` move to a private host-only directory
`DATA_DIR/.logs/run-<random>/`, never mounted into any container. Nothing is copied back to OUTPUT_DIR.

## Out of scope / limitations
- Other host reads/writes of the container-controlled artifact tree (e.g. `rmtree`, `copytree`
  checkpoints, summary verification) are unchanged.
- DATA_DIR and its ancestors are assumed host-operator controlled.
- `--resume` starts a new private run directory. Token metrics for skipped stages are taken from
  aggregates stored in the host checkpoint JSON (`stage<N>_tokens`), never from old logs. Checkpoints
  created by an older version have no stored tokens: those stages report 0 with an explicit warning.
- `DOCKER_RUN_EXTRA_ARGS` mounts are operator-trusted and not parsed; they must not expose `DATA_DIR/.logs` or its ancestors.
- INPUT_DIR (mounted read-only) overlapping `.logs` is not rejected (read exposure only).
