#!/bin/bash
# Wrapper script for pre_check.py
# Automatically detects available Python interpreter (python3 or python)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRE_CHECK_PY="${SCRIPT_DIR}/pre_check.py"

# Check if pre_check.py exists
if [ ! -f "$PRE_CHECK_PY" ]; then
    echo "Error: pre_check.py not found at $PRE_CHECK_PY" >&2
    exit 1
fi

# Detect available Python interpreter
PYTHON_CMD=""

if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    # Check if python is Python 3
    PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}' | cut -d. -f1)
    if [ "$PYTHON_VERSION" = "3" ]; then
        PYTHON_CMD="python"
    else
        echo "Error: Python 3 is required, but only Python 2 was found" >&2
        exit 1
    fi
else
    echo "Error: Python 3 is not installed" >&2
    echo "Please install Python 3 to use this tool" >&2
    exit 1
fi

# Check Python version is >= 3.10
PYTHON_MINOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.minor)")
PYTHON_MAJOR=$("$PYTHON_CMD" -c "import sys; print(sys.version_info.major)")
PYTHON_FULL=$("$PYTHON_CMD" --version 2>&1 | awk '{print $2}')
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
    echo "Error: Python 3.10 or higher is required, but found Python ${PYTHON_FULL}" >&2
    echo "" >&2
    echo "Please update Python:" >&2
    exit 1
fi

# Execute pre_check.py with all arguments
exec "$PYTHON_CMD" "$PRE_CHECK_PY" "$@"
