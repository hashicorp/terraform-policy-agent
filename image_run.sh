#!/bin/bash
set -e

# Parse command line arguments
STEP=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --step)
            STEP="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--step <0|1|2|3>]"
            echo ""
            echo "Options:"
            echo "  --step <0|1|2|3>  Run only a specific step"
            echo "                    0: Policy Extraction"
            echo "                    1: Requirement Generation"
            echo "                    2: Policy Generation"
            echo "                    3: Summary Generation"
            echo "                    (If not specified, runs all steps)"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "Starting Services (Using Registry Images)"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if required images exist
echo "Checking for required Docker images..."
if ! docker image inspect icr.io/polaris-20251120/opencode-agent:latest &> /dev/null; then
    echo "Error: icr.io/polaris-20251120/opencode-agent:latest image not found."
    echo "Please pull the image first using:"
    echo "  docker pull icr.io/polaris-20251120/opencode-agent:latest"
    exit 1
fi

if ! docker image inspect icr.io/polaris-20251120/mcp-server:latest &> /dev/null; then
    echo "Error: icr.io/polaris-20251120/mcp-server:latest image not found."
    echo "Please pull the image first using:"
    echo "  docker pull icr.io/polaris-20251120/mcp-server:latest"
    exit 1
fi

echo "✓ Docker images found"
echo ""

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "Loading environment variables from .env file..."
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ $key =~ ^#.*$ ]] && continue
        [[ -z $key ]] && continue
        # Remove inline comments and trim whitespace
        value=$(echo "$value" | sed 's/#.*//' | xargs)
        # Export the variable
        export "$key=$value"
    done < .env
    echo "✓ Environment variables loaded"
else
    echo "Error: .env file not found."
    echo "Please create a .env file with the following variables:"
    echo ""
    echo "MODEL_BASE_URL=your-model-base-url"
    echo "MODEL_NAME=your-model-name"
    echo "MODEL_API_KEY=your-api-key"
    echo "OUTPUT_DIR=./output"
    echo "MAX_WORKERS=5"
    echo ""
    exit 1
fi

# Check required variables based on AUTH_PROVIDER
AUTH_PROVIDER="${AUTH_PROVIDER:-litellm}"

if [ "$AUTH_PROVIDER" = "github-copilot" ]; then
    # GitHub Copilot requires different variables
    if [ -z "$GITHUB_COPILOT_ACCESS_TOKEN" ]; then
        echo "Error: GITHUB_COPILOT_ACCESS_TOKEN not set in .env file"
        echo "Required for GitHub Copilot authentication"
        exit 1
    fi
    if [ -z "$MODEL_NAME" ]; then
        echo "Error: MODEL_NAME not set in .env file"
        exit 1
    fi
    # Set dummy values for compatibility with pipeline script
    MODEL_API_KEY="${GITHUB_COPILOT_ACCESS_TOKEN}"
    MODEL_BASE_URL="https://api.githubcopilot.com"
else
    # LiteLLM or other providers require MODEL_API_KEY
    if [ -z "$MODEL_API_KEY" ]; then
        echo "Error: MODEL_API_KEY not set in .env file"
        exit 1
    fi
fi

if [ -z "$OUTPUT_DIR" ]; then
    echo "Error: OUTPUT_DIR not set in .env file"
    exit 1
fi

# Set default values if not set
MAX_WORKERS="${MAX_WORKERS:-5}"
API_PROVIDER="${API_PROVIDER:-litellm}"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_USE_CROSS_REGION="${AWS_USE_CROSS_REGION:-true}"

# Set provider-specific defaults
if [ "$API_PROVIDER" = "litellm" ]; then
    MODEL_BASE_URL="${MODEL_BASE_URL:-https://ete-litellm.ai-models.vpc-int.res.ibm.com}"
    MODEL_NAME="${MODEL_NAME:-aws/claude-sonnet-4-5}"
elif [ "$API_PROVIDER" = "bedrock" ]; then
    # Bedrock doesn't use MODEL_BASE_URL, keep it empty if not set
    MODEL_BASE_URL="${MODEL_BASE_URL:-}"
    MODEL_NAME="${MODEL_NAME:-anthropic.claude-opus-4-5-20251101-v1:0}"
fi

# Check if policy_goal.txt exists
if [ -f "policy_goal.txt" ]; then
    POLICY="policy_goal.txt"
    echo "✓ Policy file found: policy_goal.txt"
else
    echo "Error: policy_goal.txt not found."
    echo "Please create a policy_goal.txt file with your policy list."
    echo "Example:"
    echo "  AWS Security Hub: CloudTrail.4, EC2.7, EC2.8"
    echo ""
    exit 1
fi

echo ""
echo "Step 1/2: Starting MCP Servers..."

# Create network if it doesn't exist
docker network create mcp-network 2>/dev/null || true

# Start Python MCP Server
docker run -d \
    --name mcp-server \
    -p 127.0.0.1:8300:8300 \
    -v "$(pwd):/workspace" \
    --restart unless-stopped \
    --network mcp-network \
    icr.io/polaris-20251120/mcp-server:latest

# Start Terraform MCP Server
docker run -d \
    --name terraform-mcp-server \
    -p 127.0.0.1:8500:8080 \
    -e TRANSPORT_MODE=streamable-http \
    -e TRANSPORT_HOST=0.0.0.0 \
    -e MCP_SESSION_MODE=stateless \
    --restart unless-stopped \
    --network mcp-network \
    hashicorp/terraform-mcp-server:0.3.3

echo "✓ MCP Servers started"

# Wait for MCP servers to be ready
echo ""
echo "Waiting for MCP servers to be ready..."
sleep 5

echo ""
echo "Step 2/2: Running pipeline with OpenCode..."
echo "  Policy file: $POLICY"
echo "  Output: $OUTPUT_DIR"
echo "  Workers: $MAX_WORKERS"
echo "  Auth Provider: $AUTH_PROVIDER"
echo "  Model Base URL: $MODEL_BASE_URL"
echo "  Model Name: $MODEL_NAME"
echo "  API Provider: $API_PROVIDER"
echo "  AWS Region: $AWS_REGION"
echo "  AWS Cross-Region: $AWS_USE_CROSS_REGION"
echo ""

# Run the pipeline in Docker container (run_pipeline-opencode.py is inside the image)
# Build command arguments as array to avoid quoting issues
# Use -t flag for pseudo-TTY to enable real-time output display
DOCKER_CMD=(
    docker run --rm -t
    --name opencode-pipeline
    --network mcp-network
    -v "$(pwd):/root/workspace"
    -v "/var/run/docker.sock:/var/run/docker.sock"
    -e "MODEL_BASE_URL=$MODEL_BASE_URL"
    -e "MODEL_API_KEY=$MODEL_API_KEY"
    -e "MODEL_NAME=$MODEL_NAME"
    -e "API_PROVIDER=$API_PROVIDER"
    -e "AWS_REGION=$AWS_REGION"
    -e "AWS_USE_CROSS_REGION=$AWS_USE_CROSS_REGION"
    -e "AUTH_PROVIDER=$AUTH_PROVIDER"
    -e "HOST_WORKSPACE_PATH=$(pwd)"
    -e "PYTHONUNBUFFERED=1"
)

# Add GitHub Copilot credentials if using GitHub Copilot
if [ "$AUTH_PROVIDER" = "github-copilot" ]; then
    DOCKER_CMD+=(
        -e "GITHUB_COPILOT_ACCESS_TOKEN=$GITHUB_COPILOT_ACCESS_TOKEN"
        -e "GITHUB_COPILOT_REFRESH_TOKEN=${GITHUB_COPILOT_REFRESH_TOKEN:-$GITHUB_COPILOT_ACCESS_TOKEN}"
        -e "GITHUB_COPILOT_EXPIRES=${GITHUB_COPILOT_EXPIRES:-0}"
    )
fi

DOCKER_CMD+=(
    icr.io/polaris-20251120/opencode-agent:latest
    python /usr/local/bin/run_pipeline-opencode.py
    --policy "$POLICY"
    --output-dir "$OUTPUT_DIR"
    --api-key "$MODEL_API_KEY"
    --max-workers "$MAX_WORKERS"
    --model-base-url "$MODEL_BASE_URL"
    --model-name "$MODEL_NAME"
    --api-provider "$API_PROVIDER"
    --aws-region "$AWS_REGION"
)

# Add cross-region flag if enabled
if [ "$AWS_USE_CROSS_REGION" = "true" ]; then
    DOCKER_CMD+=(--aws-use-cross-region)
fi

# Add --step parameter if specified
if [ -n "$STEP" ]; then
    DOCKER_CMD+=(--step "$STEP")
fi

# Execute the command
"${DOCKER_CMD[@]}"

echo ""
echo "=========================================="
if [ -n "$STEP" ]; then
    echo "✓ Step $STEP Complete!"
else
    echo "✓ Pipeline Complete!"
fi
echo "=========================================="
echo ""
echo "MCP Servers are still running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "To stop MCP servers:"
echo "  docker stop mcp-server terraform-mcp-server"
echo "  docker rm mcp-server terraform-mcp-server"
echo ""