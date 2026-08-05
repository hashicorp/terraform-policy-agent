#!/bin/bash
# Copyright IBM Corp. 2026

set -euo pipefail

PREFIX="terraform-pac-agent-skills"
FORCE=false

show_usage() {
    echo "Usage: $0 [--force] [prefix]"
    echo ""
    echo "Stop Terraform PAC Agent containers by name prefix."
    echo "This is a fallback cleanup command for running or orphaned containers."
    echo ""
    echo "Options:"
    echo "  --force    Also remove matching containers with docker rm -f"
    echo "  --help     Show this help message"
    echo ""
    echo "Arguments:"
    echo "  prefix     Container name prefix (default: terraform-pac-agent-skills)"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 --force"
    echo "  $0 terraform-pac-agent-skills"
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

running_containers=$(docker ps --format '{{.Names}}' | grep "^${PREFIX}" || true)

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
    docker stop "${container_name}" >/dev/null

    if [ "${FORCE}" = true ]; then
        echo "Removing container: ${container_name}"
        docker rm -f "${container_name}" >/dev/null 2>&1 || true
    fi
done <<< "${running_containers}"

echo ""
echo "Done."

# Made with Bob
