# Changelog

All notable changes to this project will be documented in this file.

---

## [Unreleased]

### Security
- Stage logs and `execution_metrics.json` are written to a private host-only `DATA_DIR/.logs/run-<random>/` directory instead of the container-writable `OUTPUT_DIR`, so a container can no longer plant symlinks that redirect host log writes. `OUTPUT_DIR` overlapping `DATA_DIR/.logs` (e.g. `.`) and unsafe pre-existing `.logs` are rejected. Per-stage token usage is stored in the checkpoint so `--resume` still reports it for skipped stages (checkpoints from older versions report 0 for those stages, with a warning). `result_check.py` exits 1 when no safe private log directory exists (e.g. legacy runs with logs only in `OUTPUT_DIR`); overlap checks are case-insensitive and component-wise, and `--log-dir` is not symlink-resolved.
- Pipeline backups, checkpoint snapshots and restores refuse symlinks and special files in the output tree and no longer follow links (the direct-step shell backup refuses links only; see Limits); snapshots are written atomically with a version marker (older unversioned snapshots are rejected on resume), `.checkpoint`/`.backup` are covered by the mount overlap checks, and a container that cannot be confirmed removed after a timeout or failed exit blocks copying and checkpointing.
- Direct `--step` runs through `run_with_local_preparation.sh` now write a fresh private log run directory (path printed) and `result_check.py --log-dir` only accepts a real `run-*` directory directly under the configured `DATA_DIR/.logs`, validating the root first.
- Shell hardening: `OUTPUT_DIR` is normalized lexically (`.`/empty/trailing-slash parts dropped, `..` and absolute values rejected) and a missing relative `DATA_DIR` is an error in direct step runs (it never falls back to the current directory); spaces, `..` and symlinks in the trusted `DATA_DIR` itself remain supported. `LOCAL_SKILLS_DIR` must be disjoint from the output directory in both directions (case-insensitive, including missing paths and dangling links) and is checked before any directory is created. The interactive backup validates source and destination lexically below `DATA_DIR` (no `..`, no symlink or non-directory component) before copying.
- Container wrappers run in their own process groups: on timeout, failure or a handled `SIGINT`/`SIGTERM`/`SIGHUP`/`SIGQUIT` the group gets `SIGTERM` then `SIGKILL` before engine cleanup, survivors fail the stage, and unconfirmed cleanup blocks copies, checkpoints and new stages. Checkpoint metadata (`pipeline_checkpoint.json`) is prepared before the snapshot swap and a filesystem commit marker keeps a matching old or new snapshot/metadata pair after a single handled interrupt; if rollback fails the previous snapshot is kept in `DATA_DIR/.checkpoint/.stage<N>-*/`.
- Direct `--step` private logs carry the same canonical stage header (with goal/policy name) as orchestrator logs, a `Direct step:` line and the return code; the `run.sh local --step N` interface is unchanged.
- `result_check.py` reads `DATA_DIR`/`OUTPUT_DIR` with precedence: non-empty exported variable, then unquoted `.env` value, then default; `--log-dir` validation is unchanged.
- Limits: the data directory and its ancestors, extra mounts from `DOCKER_RUN_EXTRA_ARGS` and other host processes writing concurrently are trusted/not defended; the direct-step shell backup still copies special files such as FIFOs with `cp -R -P` (recreated, data not read), a pre-existing behavior that is not fixed; SIGKILL, power loss, fsync durability and closely repeated interrupts during rollback are not covered; logs written by earlier versions into `OUTPUT_DIR` are not cleaned up. Verified with fake-engine unit tests only (no real container engine, Docker daemon or model was used).

---

## [0.0.33] - 2026-10-26

### Added
- `SECURITY.md`, `CONTRIBUTING.md`, a pull request template and issue templates.
- Data and privacy notice and token-handling guidance in the README.
- OPA/Rego (`.rego`) policy input is documented and supported in external-repository mode (`*_test.rego` files are skipped), with a sample in `sample-data/input/opa/`. New README section "Supported inputs and limits" (tested providers: AWS, Azure, GCP) and an LLM-output review notice.
- `DOCKER_RUN_EXTRA_ARGS` accepts shell-style quoting, so values containing spaces can be quoted (for example `-v "/path with spaces:/data"`).
- Documented download and manual install of the Terraform and TFPolicy binaries (TFPolicy 0.3.0 or later). The setup wizard now downloads Terraform 1.17.0 and TFPolicy 0.5.0.
- Documented the optional Stage 4 (`ENABLE_STAGE4`).

### Changed
- Secrets (`GITHUB_COPILOT_ACCESS_TOKEN`, `MODEL_API_KEY`) are no longer shown in the container command printed by `--dryrun`; they are passed to the container by name instead of by value.
- The image is pulled from Docker Hub (`docker.io/hashicorp/terraform-policy-agent`) with no registry login. Docker is the default container CLI (`DOCKER_CLI=docker` in `.env.example`) and Podman is supported as an alternative. Added a "What is in the image" README section. The default container name prefix (`CONTAINER_PREFIX`) is now `terraform-policy-agent-skills`.
- `./pre-check.sh` now shows only the check for the configured mode (local or external).
- Consistent product name ("Terraform Policy Agent") across docs, skills and script output. The User Guide's Step 1 now uses `git clone` or a release archive.
- Model guidance: Claude Sonnet 4.6 and newer, all Claude Opus models and current GPT models work well.
- The distributed package is licensed under MPL-2.0.

### Removed
- `COST_ESTIMATE.md` is no longer shipped.
- Screenshots that showed sensitive or outdated details.
- Unused `POLICY_DB` / `POLICY_SUMMARY` settings.

---

## [0.0.32] - 2026-10-05

### Added
- Schema-aware policy validation: generated policies are checked against the provider schema (tfpolicy >= 0.3.0).
- Updated `tfpac-setup` / `tfpac-run` skills.

### Changed
- Container image bumped to `0.0.32` (`IMAGE_TAG`, docs, skills and footer template).
- UX review fixes across `run.sh`, `pre_check.py`, `run_pipeline.py`, `run_with_external_repo.sh` and `run_with_local_preparation.sh`.
- Updated tfpolicy download link in `.env.example` to the releases index.
- Updated policy generation and resource validation prompts.

### Fixed
- Corrected `OPENCODE_MODEL` format for the GitHub Copilot provider.
- Updated the API pre-check for GitHub Copilot and expanded the target models for the Amazon Bedrock API check.

---
