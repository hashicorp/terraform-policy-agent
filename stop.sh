#!/bin/bash
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MPL-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGE_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"

# Load environment variables from .env file if it exists
# Priority: 1. Current directory, 2. Project root, 3. Package root
# (same lookup order as run.sh, so both scripts agree on which .env is in effect)
load_env_file() {
    local env_file="$1"
    # -u is relaxed while sourcing: a user-provided .env may reference variables
    # that are not set in this shell.
    set -a
    set +u
    # shellcheck disable=SC1090
    source "$env_file"
    set -u
    set +a
}

if [ -f ".env" ]; then
    load_env_file ".env"
elif [ -f "${PROJECT_ROOT}/.env" ]; then
    load_env_file "${PROJECT_ROOT}/.env"
elif [ -f "${PACKAGE_ROOT}/.env" ]; then
    load_env_file "${PACKAGE_ROOT}/.env"
fi

# Resolve the container CLI used to stop the containers (docker or podman).
# Priority: .env > environment variable > default (docker)
DOCKER_CLI="${DOCKER_CLI:-docker}"

if ! command -v "${DOCKER_CLI}" >/dev/null 2>&1; then
    echo "ERROR: Container CLI '${DOCKER_CLI}' not found in PATH"
    echo ""
    echo "Please choose one of the following options:"
    echo "  1. Install ${DOCKER_CLI}, or start it if it is already installed"
    echo "  2. Set DOCKER_CLI to an available CLI (docker or podman) in .env file"
    exit 1
fi

PREFIX="terraform-policy-agent-skills"
FORCE=false

show_usage() {
    echo "Usage: $0 [--force] [prefix]"
    echo ""
    echo "Stop Terraform Policy Agent containers by name prefix."
    echo "This is a fallback cleanup command for running or orphaned containers."
    echo ""
    echo "Options:"
    echo "  --force    Also remove matching containers with '${DOCKER_CLI} rm -f'"
    echo "  --help     Show this help message"
    echo ""
    echo "Arguments:"
    echo "  prefix     Container name prefix (default: terraform-policy-agent-skills)"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 --force"
    echo "  $0 terraform-policy-agent-skills"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            PREFIX="$1"
            shift
            ;;
    esac
done

running_containers=$("${DOCKER_CLI}" ps --format '{{.Names}}' | grep "^${PREFIX}" || true)

if [ -z "${running_containers}" ]; then
    echo "No running containers found for prefix: ${PREFIX}"
    exit 0
fi

echo "Matching running containers:"
echo "${running_containers}"
echo ""

while IFS= read -r container_name; do
    [ -z "${container_name}" ] && continue

    echo "Stopping container: ${container_name}"
    "${DOCKER_CLI}" stop "${container_name}" >/dev/null

    if [ "${FORCE}" = true ]; then
        echo "Removing container: ${container_name}"
        "${DOCKER_CLI}" rm -f "${container_name}" >/dev/null 2>&1 || true
    fi
done <<< "${running_containers}"

echo ""
echo "Done."
