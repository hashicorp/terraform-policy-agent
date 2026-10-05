# Changelog

All notable changes to this project will be documented in this file.

---

## [0.0.32] - 2026-10-05

### Added
- Schema-aware policy validation: generated policies are checked against the provider schema (tfpolicy >= 0.3.0).
- Updated `tfpac-setup` / `tfpac-run` skills and `terraform-policy-agent-skills` submodule.

### Changed
- Container image bumped to `0.0.32` (`IMAGE_TAG`, docs, skills and footer template).
- UX review fixes across `run.sh`, `pre_check.py`, `run_pipeline.py`, `run_with_external_repo.sh` and `run_with_local_preparation.sh`.
- Updated tfpolicy download link in `.env.example` to the releases index.
- Updated policy generation and resource validation prompts.

### Fixed
- Corrected `OPENCODE_MODEL` format for the GitHub Copilot provider.
- Updated the API pre-check for GitHub Copilot and expanded the target models for the Amazon Bedrock API check.

---

## [0.0.31] - 2026-??-??

### Added
- ???

### Changed
- ???

### Fixed
- ???

---

## [0.0.30] - 2026-??-??

### Added
- ???

### Changed
- ???

### Fixed
- ???

---

## [0.0.29] - 2025-??-??

### Added
- ???

### Changed
- ???

### Fixed
- ???

---
