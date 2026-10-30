# Changelog

All notable changes to this project will be documented in this file.

---

## [Unreleased]

### Security
- Stage logs and `execution_metrics.json` are written to a private host-only `DATA_DIR/.logs/run-<random>/` directory instead of the container-writable `OUTPUT_DIR`, so a container can no longer plant symlinks that redirect host log writes. `OUTPUT_DIR` overlapping `DATA_DIR/.logs` (e.g. `.`) and unsafe pre-existing `.logs` are rejected. Per-stage token usage is stored in the checkpoint so `--resume` still reports it for skipped stages (checkpoints from older versions report 0 for those stages, with a warning). `result_check.py` exits 1 when no safe private log directory exists (e.g. legacy runs with logs only in `OUTPUT_DIR`); overlap checks are case-insensitive and component-wise, and `--log-dir` is not symlink-resolved.
- Backups, checkpoint snapshots and restores refuse symlinks and special files in the output tree and no longer follow links; snapshots are written atomically with a version marker (older unversioned snapshots are rejected on resume), `.checkpoint`/`.backup` are covered by the mount overlap checks, and a container that cannot be confirmed removed after a timeout or failed exit blocks copying and checkpointing.

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
