#!/bin/bash
set -e

# Cleanup function to stop container on exit
cleanup() {
    if [ -n "$CONTAINER_NAME" ] && docker ps -q -f name="^${CONTAINER_NAME}$" | grep -q .; then
        echo ""
        echo "Stopping container: ${CONTAINER_NAME}"
        docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    fi
}

# Register cleanup on script exit (normal exit, SIGINT, SIGTERM)
trap cleanup EXIT INT TERM

# Function to resolve path (handle both absolute and relative paths)
resolve_path() {
    local path="$1"
    local path_type="$2"  # "directory" or "file"
    
    if [[ "$path" = /* ]]; then
        # Absolute path
        echo "$path"
    else
        # Relative path
        if [ "$path_type" = "directory" ]; then
            # For directories
            echo "$(cd "$path" 2>/dev/null && pwd)" || echo "$(pwd)/${path}"
        else
            # For files
            local dir=$(dirname "$path")
            local file=$(basename "$path")
            echo "$(cd "$dir" 2>/dev/null && pwd)/${file}"
        fi
    fi
}

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

# Preserve environment variables that should not be overridden by .env
PRESERVED_CONTAINER_NAME="${CONTAINER_NAME}"
PRESERVED_DATA_DIR="${DATA_DIR}"
PRESERVED_INPUT_DIR="${INPUT_DIR}"
PRESERVED_OUTPUT_DIR="${OUTPUT_DIR}"
PRESERVED_INPUT_FILE="${INPUT_FILE}"

# Load environment variables from .env file if it exists
# Priority: 1. Current directory, 2. Project root, 3. Package root
if [ -f ".env" ]; then
    echo "Loading environment variables from $(pwd)/.env..."
    set -a
    source ".env"
    set +a
elif [ -f "${PROJECT_ROOT}/.env" ]; then
    echo "Loading environment variables from ${PROJECT_ROOT}/.env..."
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
elif [ -f "${PACKAGE_ROOT}/.env" ]; then
    echo "Loading environment variables from ${PACKAGE_ROOT}/.env..."
    set -a
    source "${PACKAGE_ROOT}/.env"
    set +a
fi

# Restore preserved variables if they were already set
[ -n "$PRESERVED_CONTAINER_NAME" ] && CONTAINER_NAME="$PRESERVED_CONTAINER_NAME"
[ -n "$PRESERVED_DATA_DIR" ] && DATA_DIR="$PRESERVED_DATA_DIR"
[ -n "$PRESERVED_INPUT_DIR" ] && INPUT_DIR="$PRESERVED_INPUT_DIR"
[ -n "$PRESERVED_OUTPUT_DIR" ] && OUTPUT_DIR="$PRESERVED_OUTPUT_DIR"
[ -n "$PRESERVED_INPUT_FILE" ] && INPUT_FILE="$PRESERVED_INPUT_FILE"

IMAGE_NAME="${IMAGE_NAME:-terraform-pac-agent-skills}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
# Use CONTAINER_PREFIX if CONTAINER_NAME is not set
CONTAINER_PREFIX="${CONTAINER_PREFIX:-terraform-pac-agent-skills}"
CONTAINER_NAME="${CONTAINER_NAME:-${CONTAINER_PREFIX}}"

# Check if container with the same name is already running
RUNNING_CONTAINERS=$(docker ps -q -f name="^${CONTAINER_NAME}$")
if [ -n "$RUNNING_CONTAINERS" ]; then
    echo "ERROR: Container with name '${CONTAINER_NAME}' is already running"
    echo ""
    echo "Please choose one of the following options:"
    echo "  1. Stop the container: docker stop ${CONTAINER_NAME}"
    echo "  2. Set a different CONTAINER_NAME or CONTAINER_PREFIX in .env file"
    echo ""
    echo "Currently running container:"
    docker ps -f name="^${CONTAINER_NAME}$" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"
    exit 1
fi

DATA_DIR="${DATA_DIR:-./data}"
INPUT_DIR="${INPUT_DIR:-input}"
OUTPUT_DIR="${OUTPUT_DIR:-output}"
INPUT_FILE="${INPUT_FILE:-policy_goal.txt}"
DRYRUN=false

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
    echo ""
    echo "Examples:"
    echo "  $0                              # Full pipeline"
    echo "  $0 step0-extraction             # Uses INPUT_DIR and INPUT_FILE from .env"
    echo "  $0 step1-requirement --goal-file goal-001.txt"
    echo "  $0 step2-generation --policy-dir CloudFront_Associated_WAF"
    echo "  $0 step3-summary"
    echo "  $0 --dryrun step0-extraction    # Print command without executing"
    echo ""
    echo "Note: INPUT_DIR and INPUT_FILE are read from .env (defaults: input/policy_goal.txt)"
    echo ""
    echo "Global options:"
    echo "  --dryrun                      Print docker command without executing"
    echo "  --prompt \"<custom prompt>\"  Override default prompt"
}

# No arguments = run full pipeline
if [ $# -eq 0 ]; then
    echo "=========================================="
    echo "Running Full Pipeline"
    echo "=========================================="
    echo "This will execute all 4 stages sequentially:"
    echo "  Stage 0: Policy Extraction"
    echo "  Stage 1: Requirement Generation"
    echo "  Stage 2: Policy Generation"
    echo "  Stage 3: Summary Generation"
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
    
    # Run Python pipeline
    echo "Delegating to run_pipeline.py..."
    echo ""
    # MAX_WORKERS is read from environment variable in run_pipeline.py
    python3 "${SCRIPT_DIR}/run_pipeline.py"
    exit $?
fi

# Check for --dryrun flag first
if [ "$1" = "--dryrun" ]; then
    DRYRUN=true
    shift
fi

# Get skill from first argument
SKILL="$1"
shift || true

if [ "$SKILL" = "--help" ] || [ "$SKILL" = "-h" ]; then
    show_usage
    exit 0
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
        
    *)
        echo "ERROR: Unknown skill '${SKILL}'"
        echo ""
        show_usage
        exit 1
        ;;
esac

# Check if image exists
if ! docker image inspect "${IMAGE_NAME}:${IMAGE_TAG}" >/dev/null 2>&1; then
    echo "ERROR: Docker image '${IMAGE_NAME}:${IMAGE_TAG}' not found"
    echo "Please run './docker/build.sh' first"
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

# Create data directories on host
mkdir -p "${DATA_DIR_RESOLVED}/${INPUT_DIR}"

OUTPUT_DIR_HOST="${DATA_DIR_RESOLVED}/${OUTPUT_DIR}"
# Check if OUTPUT_DIR is empty for step0-extraction (unless called from run_pipeline.py)
if [ "$SKILL" = "step0-extraction" ] && [ "${SKIP_OUTPUT_DIR_CHECK:-}" != "1" ]; then
    if [ -d "${OUTPUT_DIR_HOST}" ] && [ -n "$(find "${OUTPUT_DIR_HOST}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
        echo "ERROR: OUTPUT_DIR already exists and is not empty: ${OUTPUT_DIR_HOST}"
        echo "Please set a new OUTPUT_DIR in .env."
        exit 1
    fi
fi

mkdir -p "${OUTPUT_DIR_HOST}"

# Container-side input and output directory paths
CONTAINER_INPUT_DIR="/workspace/data/${INPUT_DIR}"
CONTAINER_OUTPUT_DIR="/workspace/data/${OUTPUT_DIR}"

echo "=========================================="
if [ "$DRYRUN" = true ]; then
    echo "Dry-Run Mode: Docker Command"
else
    echo "Running Terraform PaC Agent Skill"
fi
echo "=========================================="
echo "Skill: ${SKILL}"
echo "Prompt: ${PROMPT}"
echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Model: ${MODEL_NAME}"
echo ""

# Build the docker command with binary mounts and separate input/output mounts
# Binaries are mounted to /tmp and copied to /usr/local/bin by entrypoint.sh for concurrent safety
# Build environment variables based on AUTH_PROVIDER
ENV_VARS="-e MODEL_NAME=\"${MODEL_NAME}\" -e OUTPUT_DIR=\"${CONTAINER_OUTPUT_DIR}\""

# Add AUTH_PROVIDER if set
if [ -n "${AUTH_PROVIDER:-}" ]; then
    ENV_VARS="$ENV_VARS -e AUTH_PROVIDER=\"${AUTH_PROVIDER}\""
fi

# Add provider-specific environment variables
case "${AUTH_PROVIDER:-litellm}" in
    github-copilot)
        # GitHub Copilot requires OAuth tokens
        if [ -n "${GITHUB_COPILOT_ACCESS_TOKEN:-}" ]; then
            ENV_VARS="$ENV_VARS -e GITHUB_COPILOT_ACCESS_TOKEN=\"${GITHUB_COPILOT_ACCESS_TOKEN}\""
        fi
        if [ -n "${GITHUB_COPILOT_REFRESH_TOKEN:-}" ]; then
            ENV_VARS="$ENV_VARS -e GITHUB_COPILOT_REFRESH_TOKEN=\"${GITHUB_COPILOT_REFRESH_TOKEN}\""
        fi
        if [ -n "${GITHUB_COPILOT_EXPIRES:-}" ]; then
            ENV_VARS="$ENV_VARS -e GITHUB_COPILOT_EXPIRES=\"${GITHUB_COPILOT_EXPIRES}\""
        fi
        ;;
    litellm|*)
        # LiteLLM requires base URL and API key
        ENV_VARS="$ENV_VARS -e MODEL_BASE_URL=\"${MODEL_BASE_URL}\" -e MODEL_API_KEY=\"${MODEL_API_KEY}\""
        ;;
esac

DOCKER_CMD="docker run --rm \\
  --name \"${CONTAINER_NAME}\" \\
  -v \"${TERRAFORM_BINARY_PATH_RESOLVED}:/tmp/host-binaries/terraform:ro\" \\
  -v \"${TFPOLICY_BINARY_PATH_RESOLVED}:/tmp/host-binaries/tfpolicy:ro\" \\
  -v \"${DATA_DIR_RESOLVED}/${INPUT_DIR}:${CONTAINER_INPUT_DIR}:ro\" \\
  -v \"${DATA_DIR_RESOLVED}/${OUTPUT_DIR}:${CONTAINER_OUTPUT_DIR}\" \\
  ${ENV_VARS} \\
  \"${IMAGE_NAME}:${IMAGE_TAG}\" \\
  opencode run \"/${SKILL} ${PROMPT}\""

if [ "$DRYRUN" = true ]; then
    # Print the command in dry-run mode
    echo "Docker command that would be executed:"
    echo ""
    echo "$DOCKER_CMD"
    echo ""
    echo "=========================================="
    echo "ℹ️  Dry-run mode: Command not executed"
    echo "=========================================="
    echo ""
    exit 0
fi

# Run the container with separate input/output mounts and binary mounts
# Input: read-only mount (host's INPUT_DIR -> container's INPUT_DIR with same name)
# Output: read-write mount (host's OUTPUT_DIR -> container's OUTPUT_DIR with same name)
# Binaries: read-only mount to /tmp/host-binaries/ (copied to /usr/local/bin by entrypoint.sh)

# Build docker run command with environment variables
DOCKER_RUN_CMD="docker run --rm --name \"${CONTAINER_NAME}\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD -v \"${TERRAFORM_BINARY_PATH_RESOLVED}:/tmp/host-binaries/terraform:ro\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD -v \"${TFPOLICY_BINARY_PATH_RESOLVED}:/tmp/host-binaries/tfpolicy:ro\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD -v \"${DATA_DIR_RESOLVED}/${INPUT_DIR}:${CONTAINER_INPUT_DIR}:ro\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD -v \"${DATA_DIR_RESOLVED}/${OUTPUT_DIR}:${CONTAINER_OUTPUT_DIR}\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e MODEL_NAME=\"${MODEL_NAME}\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e OUTPUT_DIR=\"${CONTAINER_OUTPUT_DIR}\""

# Add AUTH_PROVIDER if set
if [ -n "${AUTH_PROVIDER:-}" ]; then
    DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e AUTH_PROVIDER=\"${AUTH_PROVIDER}\""
fi

# Add provider-specific environment variables
case "${AUTH_PROVIDER:-litellm}" in
    github-copilot)
        # GitHub Copilot requires OAuth tokens
        if [ -n "${GITHUB_COPILOT_ACCESS_TOKEN:-}" ]; then
            DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e GITHUB_COPILOT_ACCESS_TOKEN=\"${GITHUB_COPILOT_ACCESS_TOKEN}\""
        fi
        if [ -n "${GITHUB_COPILOT_REFRESH_TOKEN:-}" ]; then
            DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e GITHUB_COPILOT_REFRESH_TOKEN=\"${GITHUB_COPILOT_REFRESH_TOKEN}\""
        fi
        if [ -n "${GITHUB_COPILOT_EXPIRES:-}" ]; then
            DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e GITHUB_COPILOT_EXPIRES=\"${GITHUB_COPILOT_EXPIRES}\""
        fi
        ;;
    litellm|*)
        # LiteLLM requires base URL and API key
        DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e MODEL_BASE_URL=\"${MODEL_BASE_URL}\""
        DOCKER_RUN_CMD="$DOCKER_RUN_CMD -e MODEL_API_KEY=\"${MODEL_API_KEY}\""
        ;;
esac

DOCKER_RUN_CMD="$DOCKER_RUN_CMD \"${IMAGE_NAME}:${IMAGE_TAG}\""
DOCKER_RUN_CMD="$DOCKER_RUN_CMD opencode run \"/${SKILL} ${PROMPT}\""

# Execute the docker run command
eval $DOCKER_RUN_CMD

exit_code=$?

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
fi
echo "=========================================="
echo ""

exit $exit_code

# Made with Bob
