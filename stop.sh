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

# Stop Roo containers (from roo-headless image) if running
echo ""
echo "Stopping Roo containers..."
# Find containers by image name 'roo-headless' or by container name patterns
ROO_CONTAINERS=$(docker ps -a --filter "ancestor=roo-headless" --format '{{.Names}}' || true)
if [ -n "$ROO_CONTAINERS" ]; then
    echo "Found containers:"
    echo "$ROO_CONTAINERS" | sed 's/^/  - /'
    echo "$ROO_CONTAINERS" | xargs -I{} docker rm -f {}
    echo "✓ Roo containers stopped and removed"
else
    echo "✓ No Roo containers found"
fi

echo ""
echo "=========================================="
echo "✓ All Services Stopped!"
echo "=========================================="
echo ""
echo "To start services again:"
echo "  ./image_run.sh"
echo ""