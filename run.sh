#!/bin/bash
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MPL-2.0

set -e

# ============================================================================
# Terraform Policy Agent - Unified Run Script (v2)
# ============================================================================
# This script consolidates run_with_local_preparation.sh and run_with_external_repo.sh
# into a single entry point with subcommand pattern and auto-detection.
#
# Usage:
#   ./run.sh [subcommand] [options]
#
# Subcommands:
#   local      - Run local pipeline (default if EXTERNAL_REPO_DIR not set)
#   external   - Run external repo integration pipeline
#   (auto)     - Auto-detect based on EXTERNAL_REPO_DIR in .env
#
# Global Options:
#   --help        - Show help message
#   --version     - Show version (IMAGE_TAG from .env)
#   --dryrun      - Print commands without executing
#   --no-confirm  - Skip pre-run summary and confirmation prompt
#   --resume      - Resume pipeline from last completed stage (skip completed stages)
#
# Examples:
#   ./run.sh                                    # Auto-detect mode
#   ./run.sh local                              # Force local mode
#   ./run.sh external                           # Force external mode
#   ./run.sh local --step 2 --policy-dir X      # Local step 2 only
#   ./run.sh external --phase generate          # External generate phase
#   ./run.sh --version                          # Show version
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"

# Shared helpers (resolve_path, load_env_file, resolve_container_cli, ...)
source "${SCRIPT_DIR}/common.sh"

# Version information
VERSION="2.0.0"

# ============================================================================
# Helper Functions
# ============================================================================

# Show version information
show_version() {
    echo "Terraform Policy Agent - Run Script v${VERSION}"
    if [ -n "${IMAGE_TAG:-}" ]; then
        echo "Image Tag: ${IMAGE_TAG}"
    fi
}

# Show global help
show_global_help() {
    cat << 'EOF'
Terraform Policy Agent - Unified Run Script

USAGE:
    ./run.sh [subcommand] [options]

SUBCOMMANDS:
    local      Run local pipeline (full or targeted steps)
    external   Run external repository integration pipeline
    (auto)     Auto-detect mode based on EXTERNAL_REPO_DIR in .env

GLOBAL OPTIONS:
    --help        Show this help message
    --version     Show version information
    --dryrun      Print commands without executing
    --no-confirm  Skip pre-run summary and confirmation prompt

AUTO-DETECTION:
    When no subcommand is specified, the script auto-detects the mode:
    - If EXTERNAL_REPO_DIR is set in .env → external mode
    - Otherwise → local mode

EXAMPLES:
    # Auto-detect mode
    ./run.sh

    # Explicit modes
    ./run.sh local                              # Full local pipeline
    ./run.sh external                           # Full external pipeline

    # Targeted execution
    ./run.sh local --step 2 --policy-dir X      # Local step 2 only
    ./run.sh external --phase generate          # External generate phase

    # Get help for specific subcommand
    ./run.sh local --help
    ./run.sh external --help

For more information, see the documentation in the project README.
EOF
}

# Show help for local subcommand
show_local_help() {
    cat << 'EOF'
Local Pipeline Mode

USAGE:
    ./run.sh local [options]

OPTIONS:
    --step <0|1|2|3>           Run specific step only
    --goal-file <file>         Goal file for step 1 (required for step 1)
    --policy-dir <dir>         Policy directory for step 2 (required for step 2)
    --prompt "<text>"          Override default prompt
    --dryrun                   Print command without executing
    --help                     Show this help message

STEPS:
    0  Policy Extraction
    1  Requirement Generation (requires --goal-file)
    2  Policy Generation (requires --policy-dir)
    3  Summary Generation

EXAMPLES:
    # Run full pipeline (all steps)
    ./run.sh local

    # Run specific step
    ./run.sh local --step 0
    ./run.sh local --step 1 --goal-file goal-001.txt
    ./run.sh local --step 2 --policy-dir CloudFront_Associated_WAF
    ./run.sh local --step 3

    # Dry-run mode
    ./run.sh --dryrun local --step 2 --policy-dir X

EOF
}

# Show help for external subcommand
show_external_help() {
    cat << 'EOF'
External Repository Integration Mode

USAGE:
    ./run.sh external [options]

OPTIONS:
    --phase <preprocess|generate|postprocess>  Run specific phase only
    --step <0|1|2|3>                          Run specific step (in generate phase)
    --mock-output <dir>                       Use pre-generated output (skip generate)
    --dryrun                                  Print command without executing
    --help                                    Show this help message

PHASES:
    preprocess   Extract Sentinel files from external repo
    generate     Run policy generation pipeline (steps 0-3)
    postprocess  Deploy generated policies back to external repo

STEPS (only valid with --phase generate or full pipeline):
    0  Policy Extraction
    1  Requirement Generation
    2  Policy Generation
    3  Summary Generation

EXAMPLES:
    # Run full pipeline (all phases)
    ./run.sh external

    # Run specific phase
    ./run.sh external --phase preprocess
    ./run.sh external --phase generate
    ./run.sh external --phase postprocess

    # Run specific step in generate phase
    ./run.sh external --phase generate --step 2
    ./run.sh external --step 2  # Runs all phases, but only step 2 in generate

    # Use mock output for testing
    ./run.sh external --mock-output archive_20260525_112836/output

REQUIREMENTS:
    - EXTERNAL_REPO_DIR must be set in .env
    - External repository must exist and be accessible

EOF
}

# ============================================================================
# Environment Setup
# ============================================================================

# Preserve environment variables that should not be overridden by .env
ENV_OVERRIDABLE_VARS=(CONTAINER_NAME DATA_DIR INPUT_DIR OUTPUT_DIR INPUT_FILE LOCAL_SKILLS_DIR PIPELINE_LOG_CAPTURED)
preserve_env_vars "${ENV_OVERRIDABLE_VARS[@]}"

# Load environment variables from .env file if it exists
# Priority: 1. Current directory, 2. Project root, 3. Package root
load_env_file false "${PROJECT_ROOT}" "${PACKAGE_ROOT}" || true

# Restore preserved variables if they were already set
restore_env_vars "${ENV_OVERRIDABLE_VARS[@]}"

# ============================================================================
# Container CLI Resolution
# ============================================================================
# Priority: .env > environment variable > default (docker). Exported for
# run_with_local_preparation.sh, run_with_external_repo.sh and run_pipeline.py.
resolve_container_cli

# ============================================================================
# Argument Parsing
# ============================================================================

# Global flags
DRYRUN=false
NO_CONFIRM=false
RESUME=false
SHOW_VERSION=false

# Check for global flags first
while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            show_version
            exit 0
            ;;
        --help)
            if [ $# -eq 1 ]; then
                show_global_help
                exit 0
            fi
            # --help with subcommand will be handled later
            break
            ;;
        --dryrun)
            DRYRUN=true
            shift
            ;;
        --no-confirm)
            NO_CONFIRM=true
            shift
            ;;
        --resume)
            RESUME=true
            shift
            ;;
        *)
            break
            ;;
    esac
done

# Determine subcommand
SUBCOMMAND=""
if [ $# -gt 0 ]; then
    case $1 in
        local|external)
            SUBCOMMAND="$1"
            shift
            ;;
        --help)
            show_global_help
            exit 0
            ;;
        # Backward compatibility: detect old positional args
        step0-extraction|step1-requirement|step2-generation|step3-summary|step4-validation-fixtures)
            # Silently delegate to run_with_local_preparation.sh for backward compatibility
            exec "${SCRIPT_DIR}/run_with_local_preparation.sh" "$@"
            ;;
        *)
            # Auto-detect mode
            SUBCOMMAND="auto"
            ;;
    esac
else
    # No arguments - auto-detect mode
    SUBCOMMAND="auto"
fi

# ============================================================================
# Auto-Detection Logic
# ============================================================================

if [ "$SUBCOMMAND" = "auto" ]; then
    if [ -n "${EXTERNAL_REPO_DIR:-}" ]; then
        echo "ℹ️  Auto-detected mode: external (EXTERNAL_REPO_DIR is set in .env)"
        echo "   Run './run.sh --help' to see all options, or './run.sh local' to force local mode."
        echo ""
        SUBCOMMAND="external"
    else
        echo "ℹ️  Auto-detected mode: local (EXTERNAL_REPO_DIR not set in .env)"
        echo "   Run './run.sh --help' to see all options, or './run.sh external' to force external mode."
        echo ""
        SUBCOMMAND="local"
    fi
fi

# ============================================================================
# Subcommand Execution
# ============================================================================

case "$SUBCOMMAND" in
    local)
        # Check for --help
        if [ "$1" = "--help" ]; then
            show_local_help
            exit 0
        fi
        
        # Parse local-specific options
        STEP=""
        GOAL_FILE=""
        POLICY_DIR=""
        PROMPT=""
        
        while [[ $# -gt 0 ]]; do
            case $1 in
                --step)
                    STEP="$2"
                    shift 2
                    ;;
                --goal-file)
                    GOAL_FILE="$2"
                    shift 2
                    ;;
                --policy-dir)
                    POLICY_DIR="$2"
                    shift 2
                    ;;
                --prompt)
                    PROMPT="$2"
                    shift 2
                    ;;
                --help)
                    show_local_help
                    exit 0
                    ;;
                *)
                    echo "ERROR: Unknown option for local mode: $1"
                    echo "Run './run.sh local --help' for usage information"
                    exit 1
                    ;;
            esac
        done
        
        # Build arguments for run_with_local_preparation.sh
        RUN_ARGS=()
        
        
        if [ -n "$STEP" ]; then
            # Map step number to skill name
            case "$STEP" in
                0)
                    RUN_ARGS+=("step0-extraction")
                    ;;
                1)
                    RUN_ARGS+=("step1-requirement")
                    if [ -z "$GOAL_FILE" ]; then
                        echo "ERROR: --goal-file is required for step 1"
                        echo "Usage: ./run.sh local --step 1 --goal-file goal-001.txt"
                        exit 1
                    fi
                    RUN_ARGS+=("--goal-file" "$GOAL_FILE")
                    ;;
                2)
                    RUN_ARGS+=("step2-generation")
                    if [ -z "$POLICY_DIR" ]; then
                        echo "ERROR: --policy-dir is required for step 2"
                        echo "Usage: ./run.sh local --step 2 --policy-dir CloudFront_Associated_WAF"
                        exit 1
                    fi
                    RUN_ARGS+=("--policy-dir" "$POLICY_DIR")
                    ;;
                3)
                    RUN_ARGS+=("step3-summary")
                    ;;
                *)
                    echo "ERROR: Invalid step number: $STEP"
                    echo "Valid steps: 0, 1, 2, 3"
                    exit 1
                    ;;
            esac
            
            if [ -n "$PROMPT" ]; then
                RUN_ARGS+=("--prompt" "$PROMPT")
            fi
        fi

        # ============================================================================
        # Pre-run Confirmation
        # ============================================================================

        if [ "$DRYRUN" = false ] && [ "$NO_CONFIRM" = false ]; then
            # Run pre-check (skip if resuming — already passed on first run)
            if [ "$RESUME" = false ]; then
                "${SCRIPT_DIR}/pre-check.sh" docker env binaries image mcp input local api
            fi

            # Show summary and ask for confirmation
            echo "=========================================="
            echo "  Pre-run Summary"
            echo "=========================================="
            INPUT_FILE_PATH="${DATA_DIR:-data}/${INPUT_DIR:-input}/${INPUT_FILE:-policy_goal.txt}"
            echo "  Input File (local mode)  : ${INPUT_FILE_PATH}"
            echo "  Output   : ${DATA_DIR:-data}/${OUTPUT_DIR:-output}"
            echo "  Model    : ${AUTH_PROVIDER:-litellm} / ${MODEL_NAME:-}"
            echo "=========================================="
            echo ""

            # Show workflow plan
            if [[ " ${RUN_ARGS[*]} " == *" step0-extraction "* ]]; then
                echo "  Stage 0: Policy Extraction"
            elif [[ " ${RUN_ARGS[*]} " == *" step1-requirement "* ]]; then
                echo "  Stage 1: Requirement Generation"
            elif [[ " ${RUN_ARGS[*]} " == *" step2-generation "* ]]; then
                echo "  Stage 2: Policy Generation"
            elif [[ " ${RUN_ARGS[*]} " == *" step3-summary "* ]]; then
                echo "  Stage 3: Summary Generation"
            else
                echo "=========================================="
                echo "Running Full Pipeline"
                echo "=========================================="
                if [ "$RESUME" = true ]; then
                    echo "This will execute all 4 stages sequentially (resuming from latest checkpoint):"
                else
                    echo "This will execute all 4 stages sequentially (from scratch):"
                fi
                echo "  Stage 0: Policy Extraction"
                echo "  Stage 1: Requirement Generation"
                echo "  Stage 2: Policy Generation"
                echo "  Stage 3: Summary Generation"
            fi
            echo ""

            read -r -p "Continue? [Y/n] " _CONFIRM
            case "${_CONFIRM:-N}" in
                [Yy]) ;;
                *) echo "Aborted."; exit 0 ;;
            esac
            echo ""
        fi

        # Delegate to run_with_local_preparation.sh
        # Build prefix flags: --dryrun first, then --no-confirm, then --resume
        EXEC_ARGS=()
        [ "$DRYRUN" = true ]      && EXEC_ARGS+=("--dryrun")
        [ "$NO_CONFIRM" = true ]  && EXEC_ARGS+=("--no-confirm")
        [ "$RESUME" = true ]      && EXEC_ARGS+=("--resume")
        EXEC_ARGS+=("${RUN_ARGS[@]}")
        exec "${SCRIPT_DIR}/run_with_local_preparation.sh" "${EXEC_ARGS[@]}"
        ;;
        
    external)
        # Check for --help
        if [ "$1" = "--help" ]; then
            show_external_help
            exit 0
        fi
        
        # Parse external-specific options
        PHASE=""
        STEP=""
        MOCK_OUTPUT=""
        
        while [[ $# -gt 0 ]]; do
            case $1 in
                --phase)
                    PHASE="$2"
                    shift 2
                    ;;
                --step)
                    STEP="$2"
                    shift 2
                    ;;
                --mock-output)
                    MOCK_OUTPUT="$2"
                    shift 2
                    ;;
                --help)
                    show_external_help
                    exit 0
                    ;;
                *)
                    echo "ERROR: Unknown option for external mode: $1"
                    echo "Run './run.sh external --help' for usage information"
                    exit 1
                    ;;
            esac
        done
        
        # Build arguments for run_with_external_repo.sh
        RUN_ARGS=()
        
        if [ -n "$PHASE" ]; then
            RUN_ARGS+=("--phase" "$PHASE")
        fi
        
        if [ -n "$STEP" ]; then
            RUN_ARGS+=("--step" "$STEP")
        fi
        
        if [ -n "$MOCK_OUTPUT" ]; then
            RUN_ARGS+=("--mock-output" "$MOCK_OUTPUT")
        fi

        if [ "$RESUME" = true ]; then
            RUN_ARGS+=("--resume")
        fi

        if [ "$DRYRUN" = true ]; then
            RUN_ARGS+=("--dryrun")
        fi

        # ============================================================================
        # Pre-run Confirmation
        # ============================================================================

        if [ "$DRYRUN" = false ] && [ "$NO_CONFIRM" = false ]; then
            # Run pre-check (skip if resuming — already passed on first run)
            if [ "$RESUME" = false ]; then
                "${SCRIPT_DIR}/pre-check.sh" docker env binaries image mcp api
            fi

            # Show summary and ask for confirmation
            echo "=========================================="
            echo "  Pre-run Summary"
            echo "=========================================="
            echo "  Input Policy Directory (external mode)  : ${EXTERNAL_REPO_DIR:-}"
            echo "  Output   : ${DATA_DIR:-data}/output-{timestamp}  (created at runtime)"
            if [ -z "$PHASE" ] || [ "$PHASE" = "generate" ]; then
                echo "  Model    : ${AUTH_PROVIDER:-litellm} / ${MODEL_NAME:-}"
                echo "  Image    : ${IMAGE_NAME:-docker.io/hashicorp/terraform-policy-agent}:${IMAGE_TAG:-0.0.33}"
            fi
            echo "=========================================="
            echo ""

            # Show workflow plan
            if [ -n "$PHASE" ]; then
                if [ "$PHASE" = "generate" ] && [ "$RESUME" = true ]; then
                    echo "  Phase: generate only (resuming from latest checkpoint)"
                else
                    echo "  Phase: ${PHASE} only"
                fi
            else
                echo "=========================================="
                echo "Running Full Pipeline (external mode)"
                echo "=========================================="
                echo "  Phase 1: Preprocess"
                if [ "$RESUME" = true ]; then
                    echo "  Phase 2: Generate  (resuming from latest checkpoint)"
                else
                    echo "  Phase 2: Generate"
                fi
                echo "  Phase 3: Postprocess"
            fi
            echo ""

            read -r -p "Continue? [Y/n] " _CONFIRM
            case "${_CONFIRM:-N}" in
                [Yy]) ;;
                *) echo "Aborted."; exit 0 ;;
            esac
            echo ""
        fi

        # Delegate to run_with_external_repo.sh
        exec "${SCRIPT_DIR}/run_with_external_repo.sh" "${RUN_ARGS[@]}"
        ;;
        
    *)
        echo "ERROR: Unknown subcommand: $SUBCOMMAND"
        echo ""
        show_global_help
        exit 1
        ;;
esac
