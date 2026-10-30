#!/bin/bash
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MPL-2.0
#
# Shared helpers for run.sh, run_with_local_preparation.sh and
# run_with_external_repo.sh. This file is sourced, never executed, and must sit
# next to those scripts (it is packaged to the same directory).
#
# Compatible with bash 3.2 (macOS): no associative arrays.

# Resolve a path (absolute or relative).
# Usage: resolve_path <path> <directory|file>
resolve_path() {
    local path="$1"
    local path_type="$2"  # "directory" or "file"

    if [[ "$path" = /* ]]; then
        # Absolute path
        echo "$path"
    else
        # Relative path
        if [ "$path_type" = "directory" ]; then
            echo "$(cd "$path" 2>/dev/null && pwd)" || echo "$(pwd)/${path}"
        else
            local dir
            local file
            dir=$(dirname "$path")
            file=$(basename "$path")
            echo "$(cd "$dir" 2>/dev/null && pwd)/${file}"
        fi
    fi
}

# Fail if a host path that will be mounted into the container overlaps
# DATA_DIR/.logs (the private, host-only log root) in either direction.
# Usage: assert_not_overlapping_private_logs <data_dir_resolved> <label> <path>
assert_not_overlapping_private_logs() {
    python3 - "$1" "$2" "$3" <<'PY' || exit 1
import os, sys
from pathlib import Path
data, label, path = sys.argv[1:4]
logs = os.path.realpath(os.path.join(data, ".logs"))
p = os.path.realpath(path)
# casefolded component-wise compare: catches case aliases on case-insensitive filesystems
a, b = (tuple(c.casefold() for c in Path(x).parts) for x in (p, logs))
if a[:len(b)] == b or b[:len(a)] == a:
    print(f"ERROR: {label} ({p}) overlaps the private log directory ({logs}). "
          f"Containers must never be able to write to DATA_DIR/.logs.", file=sys.stderr)
    sys.exit(1)
PY
}

# Remember the current value of variables that an .env file must not override
# (for example DATA_DIR exported by the caller).
# Usage: preserve_env_vars VAR [VAR...]   (call before load_env_file)
preserve_env_vars() {
    local v
    for v in "$@"; do
        printf -v "PRESERVED_${v}" '%s' "${!v:-}"
    done
}

# Put back the values saved by preserve_env_vars, if they were non-empty.
# Usage: restore_env_vars VAR [VAR...]    (call after load_env_file)
restore_env_vars() {
    local v p
    for v in "$@"; do
        p="PRESERVED_${v}"
        if [ -n "${!p:-}" ]; then
            printf -v "$v" '%s' "${!p}"
        fi
    done
}

# Load the first .env found, in priority order: current directory, then each
# directory given as an argument. Sets ENV_FILE_LOADED and ENV_FILE_PATH.
# Returns 1 if no .env file exists.
# Usage: load_env_file <verbose: true|false> [dir...]
load_env_file() {
    local verbose="$1"
    shift
    local candidate
    ENV_FILE_LOADED=false
    ENV_FILE_PATH=""
    for candidate in "$(pwd)" "$@"; do
        if [ -f "${candidate}/.env" ]; then
            if [ "$verbose" = "true" ]; then
                echo "Loading environment variables from ${candidate}/.env..."
            fi
            set -a
            # shellcheck disable=SC1091
            source "${candidate}/.env"
            set +a
            ENV_FILE_LOADED=true
            ENV_FILE_PATH="${candidate}/.env"
            return 0
        fi
    done
    return 1
}

# Resolve the container CLI used to run the agent (docker or podman) and export it,
# together with DOCKER_RUN_EXTRA_ARGS, for the child scripts and run_pipeline.py.
# Priority: .env > environment variable > default (docker)
#
# DOCKER_CLI is deliberately NOT preserved across the .env load: a value set in
# .env is meant to win over an exported environment variable, so that .env stays
# the single place where the container CLI is configured.
resolve_container_cli() {
    DOCKER_CLI="${DOCKER_CLI:-docker}"

    if ! command -v "${DOCKER_CLI}" >/dev/null 2>&1; then
        echo "ERROR: Container CLI '${DOCKER_CLI}' not found in PATH"
        echo ""
        echo "Please choose one of the following options:"
        echo "  1. Install ${DOCKER_CLI}, or start it if it is already installed"
        echo "  2. Set DOCKER_CLI to an available CLI (docker or podman) in .env file"
        exit 1
    fi

    export DOCKER_CLI
    export DOCKER_RUN_EXTRA_ARGS="${DOCKER_RUN_EXTRA_ARGS:-}"
}
