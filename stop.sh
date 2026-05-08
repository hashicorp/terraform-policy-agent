#!/bin/bash
set -e

echo "=========================================="
echo "Stopping Services"
echo "=========================================="
echo ""

# Stop MCP Servers
echo "Stopping MCP Servers..."
docker stop mcp-server terraform-mcp-server 2>/dev/null || true
docker rm mcp-server terraform-mcp-server 2>/dev/null || true
echo "✓ MCP Servers stopped"

# Stop OpenCode containers if running
echo ""
echo "Stopping OpenCode containers..."
# Find containers by image name 'opencode-agent' or by container name patterns
OPENCODE_CONTAINERS=$(docker ps -a --filter "ancestor=icr.io/polaris-20251120/opencode-agent:latest" --format '{{.Names}}' || true)
if [ -n "$OPENCODE_CONTAINERS" ]; then
    echo "Found containers:"
    echo "$OPENCODE_CONTAINERS" | sed 's/^/  - /'
    echo "$OPENCODE_CONTAINERS" | xargs -I{} docker rm -f {}
    echo "✓ OpenCode containers stopped and removed"
else
    echo "✓ No OpenCode containers found"
fi

echo ""
echo "=========================================="
echo "✓ All Services Stopped!"
echo "=========================================="
echo ""
echo "To start services again:"
echo "  ./image_run.sh"
echo ""