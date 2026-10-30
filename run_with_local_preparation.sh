#!/bin/bash
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MPL-2.0

set -e

# Cleanup function to stop container on exit
# Note: ${DOCKER_CLI:-docker} is used instead of ${DOCKER_CLI}, because this trap
# is registered before DOCKER_CLI is resolved and may run while it is still unset.
cleanup() {
    if [ -n "$CONTAINER_NAME" ] && "${DOCKER_CLI:-docker}" ps -q -f name="^${CONTAINER_NAME}$" | grep -q .; then
        echo ""
        echo "Stopping container: ${CONTAINER_NAME}"
        "${DOCKER_CLI:-docker}" stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    fi
}

# Register cleanup on script exit (normal exit, SIGINT, SIGTERM)
trap cleanup EXIT INT TERM

# Simple wrapper for running OpenCode skills in Docker
# Usage: ./docker/run.sh [skill] [options]
#
# TEMPORARY IMPLEMENTATION NOTE:
# ================================
# Currently, running without arguments delegates to run_pipeline.py (Python-based orchestration).
# This creates a circular dependency where:
#   - run.sh (no args) → calls run_pipeline.py
#   - run_pipeline.py → calls docker run (which uses run.sh internally)
#
# FUTURE MIGRATION PLAN:
# ================================
# 1. Create a new skill: "pipeline-orchestration" or "full-pipeline"
# 2. Move run_pipeline.py logic into the skill's prompt
# 3. Remove the circular dependency
# 4. run.sh will then call: ./docker/run.sh pipeline-orchestration
#
# This temporary approach allows us to:
# - Keep existing run_pipeline.py functionality working
# - Provide a unified entry point (run.sh)
# - Gradually migrate to skill-based orchestration
#
# TODO: Create pipeline-orchestration skill and remove this exemption

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"

# Shared helpers (resolve_path, load_env_file, resolve_container_cli, ...)
source "${SCRIPT_DIR}/common.sh"

# Preserve environment variables that should not be overridden by .env
ENV_OVERRIDABLE_VARS=(CONTAINER_NAME DATA_DIR INPUT_DIR OUTPUT_DIR INPUT_FILE LOCAL_SKILLS_DIR)
preserve_env_vars "${ENV_OVERRIDABLE_VARS[@]}"

# Load environment variables from .env file if it exists
# Priority: 1. Current directory, 2. Project root, 3. Package root
load_env_file true "${PROJECT_ROOT}" "${PACKAGE_ROOT}" || true

# Restore preserved variables if they were already set
restore_env_vars "${ENV_OVERRIDABLE_VARS[@]}"

# Resolve the container CLI (docker or podman); also done in run.sh, because this
# script can be invoked directly and must not depend on run.sh having exported it.
resolve_container_cli

IMAGE_NAME="${IMAGE_NAME:-docker.io/hashicorp/terraform-policy-agent}"
IMAGE_TAG="${IMAGE_TAG:-0.0.33}"
# Use CONTAINER_PREFIX if CONTAINER_NAME is not set
CONTAINER_PREFIX="${CONTAINER_PREFIX:-terraform-policy-agent-skills}"
CONTAINER_NAME="${CONTAINER_NAME:-${CONTAINER_PREFIX}}"

# Check if container with the same name is already running
RUNNING_CONTAINERS=$("${DOCKER_CLI}" ps -q -f name="^${CONTAINER_NAME}$")
if [ -n "$RUNNING_CONTAINERS" ]; then
    echo "ERROR: Container with name '${CONTAINER_NAME}' is already running"
    echo ""
    echo "Please choose one of the following options:"
    echo "  1. Stop the container: ${DOCKER_CLI} stop ${CONTAINER_NAME}"
    echo "  2. Set a different CONTAINER_NAME or CONTAINER_PREFIX in .env file"
    echo ""
    echo "Currently running container:"
    "${DOCKER_CLI}" ps -f name="^${CONTAINER_NAME}$" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"
    exit 1
fi

DATA_DIR="${DATA_DIR:-./data}"
INPUT_DIR="${INPUT_DIR:-input}"
OUTPUT_DIR="${OUTPUT_DIR:-output}"
INPUT_FILE="${INPUT_FILE:-policy_goal.txt}"

# Binary paths (required for runtime mount)
TERRAFORM_BINARY_PATH="${TERRAFORM_BINARY_PATH:-}"
TFPOLICY_BINARY_PATH="${TFPOLICY_BINARY_PATH:-}"

# Validate required environment variables based on AUTH_PROVIDER
validate_env_vars() {
    local auth_provider="${AUTH_PROVIDER:-litellm}"
    
    case "$auth_provider" in
        github-copilot)
            # GitHub Copilot requires MODEL_NAME and OAuth tokens
            if [ -z "$MODEL_NAME" ]; then
                echo "ERROR: MODEL_NAME is required for GitHub Copilot provider"
                echo ""
                echo "Please set the following environment variables:"
                echo "  export AUTH_PROVIDER='github-copilot'"
                echo "  export MODEL_NAME='claude-sonnet-4.6'"
                echo "  export GITHUB_COPILOT_ACCESS_TOKEN='gho_your_access_token'"
                exit 1
            fi
            if [ -z "${GITHUB_COPILOT_ACCESS_TOKEN:-}" ]; then
                echo "ERROR: GITHUB_COPILOT_ACCESS_TOKEN is required for GitHub Copilot provider"
                echo ""
                echo "You can find your token in ~/.local/share/opencode/auth.json on your host"
                exit 1
            fi
            ;;
        amazon-bedrock)
            # Amazon Bedrock requires MODEL_NAME and MODEL_API_KEY (Bearer Token)
            if [ -z "$MODEL_NAME" ] || [ -z "${MODEL_API_KEY:-}" ]; then
                echo "ERROR: Required environment variables not set for Amazon Bedrock provider"
                echo ""
                echo "Please set the following environment variables:"
                echo "  export AUTH_PROVIDER='amazon-bedrock'"
                echo "  export MODEL_NAME='anthropic.claude-opus-4-5-20251101-v1:0'"
                echo "  export MODEL_API_KEY='your-base64-encoded-bearer-token'"
                exit 1
            fi
            ;;
        litellm|*)
            # LiteLLM requires MODEL_BASE_URL, MODEL_API_KEY, and MODEL_NAME
            if [ -z "$MODEL_BASE_URL" ] || [ -z "$MODEL_API_KEY" ] || [ -z "$MODEL_NAME" ]; then
                echo "ERROR: Required environment variables not set for LiteLLM provider"
                echo ""
                echo "Please set the following environment variables:"
                echo "  export MODEL_BASE_URL='https://your-litellm-endpoint.com'"
                echo "  export MODEL_API_KEY='sk-your-api-key'"
                echo "  export MODEL_NAME='aws/claude-sonnet-4-5'"
                exit 1
            fi
            ;;
    esac
}

# Show usage
show_usage() {
    echo "Usage: $0 [skill] [options]"
    echo ""
    echo "Run full pipeline (no arguments):"
    echo "  $0                              # Run all stages (0→1→2→3)"
    echo ""
    echo "Run individual skills:"
    echo "  step0-extraction"
    echo "  step1-requirement --goal-file FILE"
    echo "  step2-generation --policy-dir DIR"
    echo "  step3-summary"
    echo "  step4-validation-fixtures --policy-dir DIR"
    echo ""
    echo "Examples:"
    echo "  $0                              # Full pipeline"
    echo "  $0 step0-extraction             # Uses INPUT_DIR and INPUT_FILE from .env"
    echo "  $0 step1-requirement --goal-file goal-001.txt"
    echo "  $0 step2-generation --policy-dir CloudFront_Associated_WAF"
    echo "  $0 step3-summary"
    echo "  $0 step4-validation-fixtures --policy-dir CloudFront_Associated_WAF"
    echo "  $0 --dryrun step0-extraction    # Print command without executing"
    echo ""
    echo "Note: INPUT_DIR and INPUT_FILE are read from .env (defaults: input/policy_goal.txt)"
    echo ""
    echo "Global options:"
    echo "  --dryrun                      Print container command without executing"
    echo "  --prompt \"<custom prompt>\"  Override default prompt"
}

# Check for --dryrun flag first
DRYRUN=false
if [ "$1" = "--dryrun" ]; then
    DRYRUN=true
    shift
fi

# No arguments or --resume or --no-confirm [--resume] = run full pipeline
NO_CONFIRM_PIPELINE=false
if [ "$1" = "--no-confirm" ]; then
    NO_CONFIRM_PIPELINE=true
    shift
fi

RESUME_PIPELINE=false
if [ "$1" = "--resume" ]; then
    RESUME_PIPELINE=true
    shift
fi

if [ $# -eq 0 ] && [ "$DRYRUN" = false ]; then
    PIPELINE_ARGS=""
    if [ "$RESUME_PIPELINE" = true ]; then
        PIPELINE_ARGS="resume"
        echo "=========================================="
        echo "Resuming Pipeline (skipping completed stages)"
        echo "=========================================="
    else
        echo "=========================================="
        echo "Running Full Pipeline"
        echo "=========================================="
        echo "This will execute all 4 stages sequentially:"
        echo "  Stage 0: Policy Extraction"
        echo "  Stage 1: Requirement Generation"
        echo "  Stage 2: Policy Generation"
        echo "  Stage 3: Summary Generation"
    fi
    echo ""

    # Check if run_pipeline.py exists
    if [ ! -f "${SCRIPT_DIR}/run_pipeline.py" ]; then
        echo "ERROR: run_pipeline.py not found at ${SCRIPT_DIR}/run_pipeline.py"
        echo ""
        echo "Please ensure run_pipeline.py exists in docker/ directory."
        exit 1
    fi

    # Validate environment variables
    validate_env_vars

    # Check required binary paths
    if [ -z "$TERRAFORM_BINARY_PATH" ]; then
        echo "ERROR: TERRAFORM_BINARY_PATH environment variable not set"
        echo "Please set: export TERRAFORM_BINARY_PATH=/path/to/terraform"
        exit 1
    fi

    if [ -z "$TFPOLICY_BINARY_PATH" ]; then
        echo "ERROR: TFPOLICY_BINARY_PATH environment variable not set"
        echo "Please set: export TFPOLICY_BINARY_PATH=/path/to/tfpolicy"
        exit 1
    fi

    # Resolve paths before validation
    TERRAFORM_BINARY_PATH_RESOLVED=$(resolve_path "$TERRAFORM_BINARY_PATH" "file")
    TFPOLICY_BINARY_PATH_RESOLVED=$(resolve_path "$TFPOLICY_BINARY_PATH" "file")

    # Verify binary files exist and are executable
    if [ ! -f "$TERRAFORM_BINARY_PATH_RESOLVED" ]; then
        echo "ERROR: Terraform binary not found at: $TERRAFORM_BINARY_PATH_RESOLVED"
        exit 1
    fi

    if [ ! -x "$TERRAFORM_BINARY_PATH_RESOLVED" ]; then
        echo "ERROR: Terraform binary is not executable: $TERRAFORM_BINARY_PATH_RESOLVED"
        echo "Run: chmod +x $TERRAFORM_BINARY_PATH_RESOLVED"
        exit 1
    fi

    if [ ! -f "$TFPOLICY_BINARY_PATH_RESOLVED" ]; then
        echo "ERROR: tfpolicy binary not found at: $TFPOLICY_BINARY_PATH_RESOLVED"
        exit 1
    fi

    if [ ! -x "$TFPOLICY_BINARY_PATH_RESOLVED" ]; then
        echo "ERROR: tfpolicy binary is not executable: $TFPOLICY_BINARY_PATH_RESOLVED"
        echo "Run: chmod +x $TFPOLICY_BINARY_PATH_RESOLVED"
        exit 1
    fi

    # Run Python pipeline (with optional resume and no-confirm arguments)
    echo "Delegating to run_pipeline.py..."
    echo ""
    # MAX_WORKERS is read from environment variable in run_pipeline.py
    # --no-confirm is forwarded as a CLI argument to skip interactive prompts
    PYTHON_ARGS=()
    [ -n "$PIPELINE_ARGS" ] && PYTHON_ARGS+=("$PIPELINE_ARGS")
    [ "$NO_CONFIRM_PIPELINE" = true ] && PYTHON_ARGS+=("no-confirm")
    python3 "${SCRIPT_DIR}/run_pipeline.py" "${PYTHON_ARGS[@]}"
    exit $?
fi


# Get skill from first argument
SKILL="$1"
shift || true

if [ "$SKILL" = "--help" ] || [ "$SKILL" = "-h" ]; then
    show_usage
    exit 0
fi

# Validate skill name
if [ "$DRYRUN" = true ]; then
    case "$SKILL" in
        step0-extraction|step1-requirement|step2-generation|step3-summary|step4-validation-fixtures)
            ;;
        *)
            echo "=========================================="
            echo "  Pre-run Summary"
            echo "=========================================="
            if [ "${ENABLE_STAGE4:-false}" = "true" ]; then
                echo "  Workflow : step0-extraction, step1-requirement, step2-generation, step3-summary, step4-validation-fixtures"
            else
                echo "  Workflow : step0-extraction, step1-requirement, step2-generation, step3-summary"
            fi
            if [ "$RESUME_PIPELINE" = true ]; then
                echo "  Resume   : Skipping completed stages"
            fi
            INPUT_FILE_PATH="${DATA_DIR:-./data}/${INPUT_DIR:-input}/${INPUT_FILE:-policy_goal.txt}"
            echo "  Input    : ${INPUT_FILE_PATH}"
            echo "  Output   : ${DATA_DIR:-./data}/${OUTPUT_DIR:-output}"
            echo "  Model    : ${AUTH_PROVIDER:-litellm} / ${MODEL_NAME:-}"
            echo "  Image    : ${IMAGE_NAME}:${IMAGE_TAG}"
            echo "=========================================="
            exit 0
            ;;
    esac
fi

# Initialize variables
PROMPT=""
GOAL_FILE=""
POLICY_DIR=""

# Parse skill-specific arguments
case "$SKILL" in
    step0-extraction)
        while [[ $# -gt 0 ]]; do
            case $1 in
                --prompt)
                    PROMPT="$2"
                    shift 2
                    ;;
                *)
                    echo "Unknown option for step0-extraction: $1"
                    echo "Usage: $0 step0-extraction [--prompt \"<prompt>\"]"
                    echo "Note: INPUT_DIR and INPUT_FILE are read from .env (defaults: input/policy_goal.txt)"
                    exit 1
                    ;;
            esac
        done
        
        if [ -z "$PROMPT" ]; then
            PROMPT="Read policy descriptions from /workspace/data/${INPUT_DIR}/${INPUT_FILE} and extract individual goals to /workspace/data/${OUTPUT_DIR}/goals/"
        fi
        ;;
        
    step1-requirement)
        while [[ $# -gt 0 ]]; do
            case $1 in
                --goal-file)
                    GOAL_FILE="$2"
                    shift 2
                    ;;
                --prompt)
                    PROMPT="$2"
                    shift 2
                    ;;
                *)
                    echo "Unknown option for step1-requirement: $1"
                    echo "Usage: $0 step1-requirement --goal-file FILE [--prompt \"<prompt>\"]"
                    exit 1
                    ;;
            esac
        done
        
        if [ -z "$GOAL_FILE" ]; then
            echo "ERROR: step1-requirement requires --goal-file"
            echo "Usage: $0 step1-requirement --goal-file goal-001.txt"
            exit 1
        fi
        
        if [ -z "$PROMPT" ]; then
            PROMPT="Read the goal from /workspace/data/${OUTPUT_DIR}/goals/${GOAL_FILE} and generate requirements in /workspace/data/${OUTPUT_DIR}/

CRITICAL: You MUST strictly follow ALL instructions in the step1-requirement skill without deviation."
        fi
        ;;
        
    step2-generation)
        while [[ $# -gt 0 ]]; do
            case $1 in
                --policy-dir)
                    POLICY_DIR="$2"
                    shift 2
                    ;;
                --prompt)
                    PROMPT="$2"
                    shift 2
                    ;;
                *)
                    echo "Unknown option for step2-generation: $1"
                    echo "Usage: $0 step2-generation --policy-dir DIR [--prompt \"<prompt>\"]"
                    exit 1
                    ;;
            esac
        done
        
        if [ -z "$POLICY_DIR" ]; then
            echo "ERROR: step2-generation requires --policy-dir"
            echo "Usage: $0 step2-generation --policy-dir CloudFront_Associated_WAF"
            exit 1
        fi
        
        if [ -z "$PROMPT" ]; then
            PROMPT="Read requirements from /workspace/data/${OUTPUT_DIR}/${POLICY_DIR}/requirement.txt and generate policy files in /workspace/data/${OUTPUT_DIR}/${POLICY_DIR}/

CRITICAL: You MUST strictly follow ALL instructions in the step2-generation skill without deviation."
        fi
        ;;
        
    step3-summary)
        while [[ $# -gt 0 ]]; do
            case $1 in
                --prompt)
                    PROMPT="$2"
                    shift 2
                    ;;
                *)
                    echo "Unknown option for step3-summary: $1"
                    echo "Usage: $0 step3-summary [--prompt \"<prompt>\"]"
                    exit 1
                    ;;
            esac
        done
        
        if [ -z "$PROMPT" ]; then
            PROMPT="Collect results from all policies in /workspace/data/${OUTPUT_DIR}/ and generate summary in /workspace/data/${OUTPUT_DIR}/"
        fi
        ;;
        
    step4-validation-fixtures)
        while [[ $# -gt 0 ]]; do
            case $1 in
                --policy-dir)
                    POLICY_DIR="$2"
                    shift 2
                    ;;
                --prompt)
                    PROMPT="$2"
                    shift 2
                    ;;
                *)
                    echo "Unknown option for step4-validation-fixtures: $1"
                    echo "Usage: $0 step4-validation-fixtures --policy-dir DIR [--prompt \"<prompt>\"]"
                    exit 1
                    ;;
            esac
        done
        
        if [ -z "$POLICY_DIR" ]; then
            echo "ERROR: step4-validation-fixtures requires --policy-dir"
            echo "Usage: $0 step4-validation-fixtures --policy-dir CloudFront_Associated_WAF"
            exit 1
        fi
        
        if [ -z "$PROMPT" ]; then
            PROMPT="Read gwt.json and main.tf from /workspace/data/${OUTPUT_DIR}/${POLICY_DIR}/ and generate validation fixtures (pass_config.tf and fail_config.tf) in /workspace/data/${OUTPUT_DIR}/${POLICY_DIR}/

CRITICAL: You MUST strictly follow ALL instructions in the step4-validation-fixtures skill without deviation."
        fi
        ;;
        
    *)
        echo "ERROR: Unknown skill '${SKILL}'"
        echo ""
        show_usage
        exit 1
        ;;
esac

# Check if image exists
if ! "${DOCKER_CLI}" image inspect "${IMAGE_NAME}:${IMAGE_TAG}" >/dev/null 2>&1; then
    echo "ERROR: Container image '${IMAGE_NAME}:${IMAGE_TAG}' not found"
    echo "Pull it with: ${DOCKER_CLI} pull ${IMAGE_NAME}:${IMAGE_TAG}"
    exit 1
fi

# Validate environment variables
validate_env_vars

# Check required binary paths
if [ -z "$TERRAFORM_BINARY_PATH" ]; then
    echo "ERROR: TERRAFORM_BINARY_PATH environment variable not set"
    echo "Please set: export TERRAFORM_BINARY_PATH=/path/to/terraform"
    exit 1
fi

if [ -z "$TFPOLICY_BINARY_PATH" ]; then
    echo "ERROR: TFPOLICY_BINARY_PATH environment variable not set"
    echo "Please set: export TFPOLICY_BINARY_PATH=/path/to/tfpolicy"
    exit 1
fi

# Resolve paths before validation
TERRAFORM_BINARY_PATH_RESOLVED=$(resolve_path "$TERRAFORM_BINARY_PATH" "file")
TFPOLICY_BINARY_PATH_RESOLVED=$(resolve_path "$TFPOLICY_BINARY_PATH" "file")

# Verify binary files exist and are executable
if [ ! -f "$TERRAFORM_BINARY_PATH_RESOLVED" ]; then
    echo "ERROR: Terraform binary not found at: $TERRAFORM_BINARY_PATH_RESOLVED"
    exit 1
fi

if [ ! -x "$TERRAFORM_BINARY_PATH_RESOLVED" ]; then
    echo "ERROR: Terraform binary is not executable: $TERRAFORM_BINARY_PATH_RESOLVED"
    echo "Run: chmod +x $TERRAFORM_BINARY_PATH_RESOLVED"
    exit 1
fi

if [ ! -f "$TFPOLICY_BINARY_PATH_RESOLVED" ]; then
    echo "ERROR: tfpolicy binary not found at: $TFPOLICY_BINARY_PATH_RESOLVED"
    exit 1
fi

if [ ! -x "$TFPOLICY_BINARY_PATH_RESOLVED" ]; then
    echo "ERROR: tfpolicy binary is not executable: $TFPOLICY_BINARY_PATH_RESOLVED"
    echo "Run: chmod +x $TFPOLICY_BINARY_PATH_RESOLVED"
    exit 1
fi

# Resolve DATA_DIR path (handle both absolute and relative paths)
DATA_DIR_RESOLVED=$(resolve_path "$DATA_DIR" "directory")

# OUTPUT_DIR must be relative to DATA_DIR.
if [[ "$OUTPUT_DIR" = /* ]]; then
    echo "ERROR: OUTPUT_DIR must be relative to DATA_DIR, not an absolute path: ${OUTPUT_DIR}" >&2
    exit 1
fi
assert_not_overlapping_private_logs "$DATA_DIR_RESOLVED" "OUTPUT_DIR mount" "${DATA_DIR_RESOLVED}/${OUTPUT_DIR}"

# Create data directories on host
mkdir -p "${DATA_DIR_RESOLVED}/${INPUT_DIR}"

OUTPUT_DIR_HOST="${DATA_DIR_RESOLVED}/${OUTPUT_DIR}"
# Check if OUTPUT_DIR is empty for step0-extraction (unless called from run_pipeline.py)
if [ "$SKILL" = "step0-extraction" ] && [ "${SKIP_OUTPUT_DIR_CHECK:-}" != "1" ] && [ "$DRYRUN" != true ]; then
    if [ -d "${OUTPUT_DIR_HOST}" ] && [ -n "$(find "${OUTPUT_DIR_HOST}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
        if [ "$NO_CONFIRM_PIPELINE" = true ]; then
            echo "ERROR: OUTPUT_DIR already exists and is not empty: ${OUTPUT_DIR_HOST}"
            echo "Please set a new OUTPUT_DIR in .env."
            exit 1
        fi
        echo ""
        echo "⚠️  OUTPUT_DIR is not empty: ${OUTPUT_DIR_HOST}"
        echo "Choose how to handle existing output:"
        echo "  [1] Backup  — copy to ${DATA_DIR_RESOLVED}/.backup/output_<timestamp>, then continue"
        echo "  [2] Clean   — delete existing output, then continue"
        echo "  [3] Cancel  — abort"
        while true; do
            read -r -p "Enter choice [1/2/3]: " _CHOICE
            case "${_CHOICE}" in
                1)
                    _TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
                    _BACKUP_DIR="${DATA_DIR_RESOLVED}/.backup/output_${_TIMESTAMP}"
                    backup_output_dir "${OUTPUT_DIR_HOST}" "${_BACKUP_DIR}" || exit 1
                    echo "✅ Backed up to: ${_BACKUP_DIR}"
                    break
                    ;;
                2)
                    rm -rf "${OUTPUT_DIR_HOST}"
                    echo "🧹 Cleaned: ${OUTPUT_DIR_HOST}"
                    break
                    ;;
                3)
                    echo "Aborted."
                    exit 0
                    ;;
                *)
                    echo "Please enter 1, 2, or 3."
                    ;;
            esac
        done
    fi
fi

mkdir -p "${OUTPUT_DIR_HOST}"

# Container-side input and output directory paths
CONTAINER_INPUT_DIR="/workspace/data/${INPUT_DIR}"
CONTAINER_OUTPUT_DIR="/workspace/data/${OUTPUT_DIR}"

echo "=========================================="
if [ "$DRYRUN" = true ]; then
    echo "Dry-Run Mode: Container Command"
else
    echo "Running Terraform Policy Agent Skill"
fi
echo "=========================================="
echo "Input : ${DATA_DIR_RESOLVED}/${INPUT_DIR}/${INPUT_FILE}"
echo "Output: ${OUTPUT_DIR_HOST}"
echo "Model : ${MODEL_NAME}"
echo "Skill : ${SKILL}"
echo "Prompt: ${PROMPT}"
echo "Image : ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# Build the docker command with binary mounts and separate input/output mounts
# Binaries are mounted to /tmp and copied to /usr/local/bin by entrypoint.sh for concurrent safety
# Build OPENCODE_MODEL: the model identifier used in opencode.json ({env:OPENCODE_MODEL})
# Format: {provider}/{model} e.g. litellm/aws/claude-sonnet-4-5, amazon-bedrock/anthropic.claude-opus-4-5-20251101-v1:0
case "${AUTH_PROVIDER:-litellm}" in
    github-copilot)
        OPENCODE_MODEL="github-copilot/${MODEL_NAME}"
        ;;
    amazon-bedrock)
        OPENCODE_MODEL="amazon-bedrock/${MODEL_NAME}"
        ;;
    litellm|*)
        OPENCODE_MODEL="litellm/${MODEL_NAME}"
        ;;
esac

# Secrets are passed to the container by NAME only (`-e VAR`), never by value, so
# they do not appear in the printed (--dryrun) command, in `ps` output, or in
# `docker inspect` of the command line. The container runtime reads the values
# from this script's environment, so make sure they are exported.
export GITHUB_COPILOT_ACCESS_TOKEN GITHUB_COPILOT_REFRESH_TOKEN MODEL_API_KEY

# Build the container command ONCE as an argument array.
# Binaries are mounted to /tmp and copied to /usr/local/bin by entrypoint.sh for concurrent safety.
# Input is mounted read-only, output read-write.
DOCKER_ARGS=("${DOCKER_CLI}" run --rm --name "${CONTAINER_NAME}" --add-host=host.docker.internal:host-gateway)

# Host-specific flags from .env (e.g. --security-opt label=disable on SELinux hosts).
# Split with shell-style quoting (shlex), so values containing spaces can be quoted:
#   DOCKER_RUN_EXTRA_ARGS='-v "/path with spaces:/data"'
# The value is parsed, never evaluated, so $(...) and backticks are not executed.
if [ -n "${DOCKER_RUN_EXTRA_ARGS:-}" ]; then
    # Validate first so a quoting mistake fails loudly instead of being dropped.
    if ! python3 -c 'import shlex, sys; shlex.split(sys.argv[1])' "${DOCKER_RUN_EXTRA_ARGS}" 2>/dev/null; then
        echo "ERROR: could not parse DOCKER_RUN_EXTRA_ARGS (unbalanced quotes?): ${DOCKER_RUN_EXTRA_ARGS}" >&2
        exit 1
    fi
    while IFS= read -r -d '' _arg; do
        DOCKER_ARGS+=("$_arg")
    done < <(python3 -c 'import shlex, sys; sys.stdout.write("".join(a + "\0" for a in shlex.split(sys.argv[1])))' "${DOCKER_RUN_EXTRA_ARGS}")
fi

DOCKER_ARGS+=(
    -v "${TERRAFORM_BINARY_PATH_RESOLVED}:/tmp/host-binaries/terraform:ro"
    -v "${TFPOLICY_BINARY_PATH_RESOLVED}:/tmp/host-binaries/tfpolicy:ro"
    -v "${DATA_DIR_RESOLVED}/${INPUT_DIR}:${CONTAINER_INPUT_DIR}:ro"
    -v "${DATA_DIR_RESOLVED}/${OUTPUT_DIR}:${CONTAINER_OUTPUT_DIR}"
)

# Mount local skills directory if specified (overrides image's skills)
if [ -n "${LOCAL_SKILLS_DIR:-}" ]; then
    LOCAL_SKILLS_DIR_RESOLVED=$(resolve_path "$LOCAL_SKILLS_DIR" "directory")
    if [ -d "$LOCAL_SKILLS_DIR_RESOLVED" ]; then
        assert_not_overlapping_private_logs "$DATA_DIR_RESOLVED" "LOCAL_SKILLS_DIR mount" "$LOCAL_SKILLS_DIR_RESOLVED"
        [ "$DRYRUN" = true ] || echo "Mounting local skills directory: ${LOCAL_SKILLS_DIR_RESOLVED}"
        # Mount to both locations:
        # - /workspace/.opencode/skills: Used by OpenCode
        # - /skills: Used for cross-skill references
        DOCKER_ARGS+=(
            -v "${LOCAL_SKILLS_DIR_RESOLVED}:/workspace/.opencode/skills"
            -v "${LOCAL_SKILLS_DIR_RESOLVED}:/skills"
        )
    else
        [ "$DRYRUN" = true ] || echo "WARNING: LOCAL_SKILLS_DIR specified but not found: ${LOCAL_SKILLS_DIR}"
    fi
fi

DOCKER_ARGS+=(-e "MODEL_NAME=${MODEL_NAME}" -e "OUTPUT_DIR=${CONTAINER_OUTPUT_DIR}" -e "OPENCODE_MODEL=${OPENCODE_MODEL}")

if [ -n "${AUTH_PROVIDER:-}" ]; then
    DOCKER_ARGS+=(-e "AUTH_PROVIDER=${AUTH_PROVIDER}")
fi

# Provider-specific environment variables (secrets by name only)
case "${AUTH_PROVIDER:-litellm}" in
    github-copilot)
        # GitHub Copilot requires OAuth tokens
        [ -n "${GITHUB_COPILOT_ACCESS_TOKEN:-}" ]  && DOCKER_ARGS+=(-e GITHUB_COPILOT_ACCESS_TOKEN)
        [ -n "${GITHUB_COPILOT_REFRESH_TOKEN:-}" ] && DOCKER_ARGS+=(-e GITHUB_COPILOT_REFRESH_TOKEN)
        [ -n "${GITHUB_COPILOT_EXPIRES:-}" ]       && DOCKER_ARGS+=(-e "GITHUB_COPILOT_EXPIRES=${GITHUB_COPILOT_EXPIRES}")
        ;;
    amazon-bedrock)
        # Amazon Bedrock requires API key (Bearer Token)
        DOCKER_ARGS+=(-e MODEL_API_KEY)
        ;;
    litellm|*)
        # LiteLLM requires base URL and API key
        DOCKER_ARGS+=(-e "MODEL_BASE_URL=${MODEL_BASE_URL}" -e MODEL_API_KEY)
        ;;
esac

# Collapse newlines / repeated whitespace in the prompt into single spaces so it is
# passed to `opencode run` as one line (this matches the behaviour of the previous
# eval-based implementation, which word-split the command string).
PROMPT_ONE_LINE="$(set -f; echo ${PROMPT})"

CONTAINER_SCRIPT="opencode run '/${SKILL} ${PROMPT_ONE_LINE}' && echo '' && echo '==========================================' && echo '✅ Usage Statistics (opencode stats)' && echo '==========================================' && opencode stats"
DOCKER_ARGS+=("${IMAGE_NAME}:${IMAGE_TAG}" sh -c "${CONTAINER_SCRIPT}")

if [ "$DRYRUN" = true ]; then
    # Print the exact command, one flag per line, shell-quoted
    echo "Container command that would be executed:"
    echo ""
    _first=true
    for _arg in "${DOCKER_ARGS[@]}"; do
        if [ "$_first" = true ]; then
            printf '%q' "$_arg"
            _first=false
        elif [[ "$_arg" == -* ]]; then
            printf ' \\\n  %q' "$_arg"
        else
            printf ' %q' "$_arg"
        fi
    done
    echo ""
    echo ""
    echo "=========================================="
    echo "ℹ️  Dry-run mode: Command not executed"
    echo "=========================================="
    echo ""
    exit 0
fi

# Execute the container run command
if "${DOCKER_ARGS[@]}"; then
    exit_code=0
else
    exit_code=$?
fi


# Append footer to HCL files for step2-generation
if [ $exit_code -eq 0 ] && [ "$SKILL" = "step2-generation" ]; then
    echo ""
    echo "=========================================="
    echo "Appending footer to generated HCL files"
    echo "=========================================="
    
    # Get the policy directory path on the host
    POLICY_DIR_HOST="${DATA_DIR_RESOLVED}/${OUTPUT_DIR}/${POLICY_DIR}"
    
    # Path to append_footer.py script
    APPEND_FOOTER_SCRIPT="${SCRIPT_DIR}/append_footer.py"
    
    if [ -f "$APPEND_FOOTER_SCRIPT" ]; then
        # Run the append_footer.py script
        python3 "$APPEND_FOOTER_SCRIPT" "$POLICY_DIR_HOST" || {
            echo "⚠️  Warning: Failed to append footer to HCL files"
        }
    else
        echo "⚠️  Warning: append_footer.py script not found at $APPEND_FOOTER_SCRIPT"
    fi
    
    echo ""
fi

echo ""
echo "=========================================="
if [ $exit_code -eq 0 ]; then
    echo "✅ Skill execution completed successfully"
else
    echo "❌ Skill execution failed with exit code: $exit_code"
    echo "⚠️  Partial output may remain in: ${OUTPUT_DIR_HOST}/"
    if [ "$NO_CONFIRM_PIPELINE" = true ] || [ "${SKIP_FAIL_OUTPUT_CLEANUP:-0}" = "1" ]; then
        echo "    Partial outputs left as-is — review and remove if not needed, then rerun."
    else
        echo ""
        echo "Choose how to handle partial output:"
        echo "  [1] Clean  — delete partial output now"
        echo "  [2] Keep   — leave as-is and review manually"
        while true; do
            read -r -p "Enter choice [1/2]: " _CHOICE
            case "${_CHOICE}" in
                1)
                    rm -rf "${OUTPUT_DIR_HOST}"
                    echo "🧹 Cleaned: ${OUTPUT_DIR_HOST}"
                    break
                    ;;
                2)
                    echo "📁 Kept: ${OUTPUT_DIR_HOST}"
                    break
                    ;;
                *)
                    echo "Please enter 1 or 2."
                    ;;
            esac
        done
    fi
fi
echo "=========================================="
echo ""

exit $exit_code
