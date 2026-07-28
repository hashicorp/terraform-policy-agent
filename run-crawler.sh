#!/bin/bash
set -e

echo "=========================================="
echo "Starting Crawler Service (OpenCode)"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

source ".env"

CRAWLER_IMAGE_NAME="${IMAGE_NAME:-terraform-pac-agent-skills}"
CRAWLER_IMAGE_TAG="${IMAGE_TAG:-latest}"
CRAWLER_IMAGE_FULL_NAME="${CRAWLER_IMAGE_NAME}:${CRAWLER_IMAGE_TAG}"

# Container name configuration
CRAWLER_CONTAINER_PREFIX="${CRAWLER_CONTAINER_PREFIX:-crawler-agent}"
CRAWLER_CONTAINER_NAME="${CRAWLER_CONTAINER_NAME:-${CRAWLER_CONTAINER_PREFIX}}"
# Check if terraform-pac-agent-skills image exists
if ! docker image inspect "${CRAWLER_IMAGE_FULL_NAME}" &> /dev/null; then
    echo "Error: ${CRAWLER_IMAGE_FULL_NAME} image not found."
    echo "Please run './docker/build.sh' first to build the image."
    exit 1
fi

echo "✓ Docker image found"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

# Create required directories with proper permissions
echo "Creating required directories..."
mkdir -p crawler/report/delta crawler/report/summary crawler/log crawler/guide database
chmod -R 755 crawler database
echo "✓ Directories created"
echo ""

# Stop and remove existing container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CRAWLER_CONTAINER_NAME}$"; then
    echo "Stopping and removing existing crawler container..."
    docker stop "${CRAWLER_CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rm "${CRAWLER_CONTAINER_NAME}" >/dev/null 2>&1 || true
    echo "✓ Existing container removed"
    echo ""
fi

# Run the Python script
MODE="$1"
if [ -z "$MODE" ]; then
    echo "Error: Mode not specified."
    echo "Usage: $0 <mode>"
    echo "  mode: add, delete, update, apply"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 ${SCRIPT_DIR}/run_crawler.py --mode "$MODE"