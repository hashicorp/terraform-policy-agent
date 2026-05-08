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
            echo "  --step <0|1|2|3>  Run only a specific pipeline step in Phase 2"
            echo "                    0: Policy Extraction"
            echo "                    1: Requirement Generation"
            echo "                    2: Policy Generation"
            echo "                    3: Summary Generation"
            echo "                    (If not specified, runs all steps)"
            echo ""
            echo "Note: Phase 1 (Sentinel extraction) and Phase 3 (deployment) always run"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "External Repo Integration Pipeline"
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
    set -a  # automatically export all variables
    source .env
    set +a  # stop automatically exporting
    echo "✓ Environment variables loaded"
else
    echo "Error: .env file not found."
    echo "Please create a .env file with EXTERNAL_REPO_DIR variable."
    exit 1
fi

# Check authentication based on AUTH_PROVIDER
AUTH_PROVIDER="${AUTH_PROVIDER:-litellm}"

if [ "$AUTH_PROVIDER" = "github-copilot" ]; then
    # GitHub Copilot authentication
    if [ -z "$GITHUB_COPILOT_ACCESS_TOKEN" ]; then
        echo "Error: GITHUB_COPILOT_ACCESS_TOKEN not set in .env file"
        exit 1
    fi
    if [ -z "$GITHUB_COPILOT_REFRESH_TOKEN" ]; then
        echo "Error: GITHUB_COPILOT_REFRESH_TOKEN not set in .env file"
        exit 1
    fi
    GITHUB_COPILOT_EXPIRES="${GITHUB_COPILOT_EXPIRES:-0}"
    echo "✓ Using GitHub Copilot authentication"
else
    # LiteLLM or Bedrock authentication
    if [ -z "$MODEL_API_KEY" ]; then
        echo "Error: MODEL_API_KEY not set in .env file"
        exit 1
    fi
    echo "✓ Using $AUTH_PROVIDER authentication"
fi

if [ -z "$OUTPUT_DIR" ]; then
    echo "Error: OUTPUT_DIR not set in .env file"
    exit 1
fi

if [ -z "$EXTERNAL_REPO_DIR" ]; then
    echo "Error: EXTERNAL_REPO_DIR not set in .env file"
    echo "Please add: EXTERNAL_REPO_DIR=/path/to/external/repo"
    exit 1
fi

# Check if external repo directory exists
if [ ! -d "$EXTERNAL_REPO_DIR" ]; then
    echo "Error: External repository directory not found: $EXTERNAL_REPO_DIR"
    exit 1
fi

echo "✓ External repository found: $EXTERNAL_REPO_DIR"
echo ""

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
    MODEL_BASE_URL="${MODEL_BASE_URL:-}"
    MODEL_NAME="${MODEL_NAME:-anthropic.claude-opus-4-5-20251101-v1:0}"
fi

echo "=========================================="
echo "Phase 1: Extract Sentinel files"
echo "=========================================="
echo ""

# Create timestamped input directory
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
INPUT_DIR="input-${TIMESTAMP}"
mkdir -p "$INPUT_DIR"

echo "✓ Created input directory: $INPUT_DIR"
echo ""

# Copy .sentinel files from external repo, skipping those with existing .policy.hcl
# Exclude files in test/ directories (which contain mock files)
SENTINEL_COUNT=0
SKIPPED_COUNT=0
MOCK_COUNT=0

# Find all .sentinel files recursively, excluding test/ directories
while IFS= read -r -d '' sentinel_file; do
    # Get the directory containing the sentinel file
    sentinel_dir=$(dirname "$sentinel_file")
    sentinel_basename=$(basename "$sentinel_file" .sentinel)
    
    # Check if this is a mock file (in test/ directory)
    if [[ "$sentinel_file" == */test/* ]]; then
        echo "⊘ Skipped: $sentinel_file (mock file in test/ directory)"
        MOCK_COUNT=$((MOCK_COUNT + 1))
        continue
    fi
    
    # Check if policy.hcl already exists in tfpolicy subdirectory
    tfpolicy_dir="$sentinel_dir/tfpolicy/$sentinel_basename"
    policy_file="$tfpolicy_dir/$sentinel_basename.policy.hcl"
    
    if [ -f "$policy_file" ]; then
        echo "⊘ Skipped: $sentinel_file (policy already exists in tfpolicy/$sentinel_basename/)"
        SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    else
        # Copy to input directory, preserving relative path structure
        relative_path="${sentinel_file#$EXTERNAL_REPO_DIR/}"
        target_file="$INPUT_DIR/$relative_path"
        target_dir=$(dirname "$target_file")
        
        mkdir -p "$target_dir"
        cp "$sentinel_file" "$target_file"
        SENTINEL_COUNT=$((SENTINEL_COUNT + 1))
        echo "✓ Copied: $relative_path"
    fi
done < <(find "$EXTERNAL_REPO_DIR" -type f -name "*.sentinel" -print0)

if [ $SENTINEL_COUNT -eq 0 ]; then
    echo ""
    echo "No new Sentinel files to process."
    echo "  Total files found: $((SENTINEL_COUNT + SKIPPED_COUNT + MOCK_COUNT))"
    echo "  Mock files (in test/): $MOCK_COUNT"
    echo "  Already have policy.hcl: $SKIPPED_COUNT"
    echo "  New files to process: $SENTINEL_COUNT"
    exit 0
fi

echo ""
echo "✓ Copied $SENTINEL_COUNT Sentinel files to $INPUT_DIR/"
echo "  Skipped $SKIPPED_COUNT files (already have policy.hcl)"
echo "  Skipped $MOCK_COUNT mock files (in test/ directories)"
echo ""

# Copy and process sentinel.hcl if SENTINEL_HCL_PATH is defined
if [ -n "$SENTINEL_HCL_PATH" ]; then
    if [ -f "$SENTINEL_HCL_PATH" ]; then
        echo "Processing sentinel.hcl file..."
        
        # Copy sentinel.hcl to INPUT_DIR
        cp "$SENTINEL_HCL_PATH" "$INPUT_DIR/sentinel.hcl"
        
        # Process the file to replace full paths with just filenames
        # Example: source = "./policies/s3/s3-bucket-logging.sentinel" -> source = "s3-bucket-logging.sentinel"
        sed -i.bak 's|source = "[^"]*\/\([^/"]*\.sentinel\)"|source = "\1"|g' "$INPUT_DIR/sentinel.hcl"
        rm -f "$INPUT_DIR/sentinel.hcl.bak"
        
        echo "✓ Copied and processed sentinel.hcl to $INPUT_DIR/"
    else
        echo "⚠️  Warning: SENTINEL_HCL_PATH is set but file not found: $SENTINEL_HCL_PATH"
    fi
fi

# Generate policy_goal.txt
echo "Generating policy_goal.txt..."
echo "Generate TF Policy for" > policy_goal.txt

# Find all .sentinel files recursively in INPUT_DIR
while IFS= read -r -d '' sentinel_file; do
    echo "./$sentinel_file" >> policy_goal.txt
done < <(find "$INPUT_DIR" -type f -name "*.sentinel" -print0)

# If sentinel.hcl was copied, add reference to it in policy_goal.txt
if [ -n "$SENTINEL_HCL_PATH" ] && [ -f "$INPUT_DIR/sentinel.hcl" ]; then
    echo "" >> policy_goal.txt
    echo "Enforcement level configuration file:" >> policy_goal.txt
    echo "./$INPUT_DIR/sentinel.hcl" >> policy_goal.txt
fi

echo "✓ Generated policy_goal.txt"
echo ""

echo "=========================================="
echo "Phase 2: Run Pipeline"
echo "=========================================="
echo ""

# Start MCP Servers
echo "Starting MCP Servers..."

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
echo "Running pipeline with OpenCode..."
echo "  Policy file: policy_goal.txt"
echo "  Output: $OUTPUT_DIR"
echo "  Workers: $MAX_WORKERS"
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
    -e "MODEL_NAME=$MODEL_NAME"
    -e "API_PROVIDER=$API_PROVIDER"
    -e "AWS_REGION=$AWS_REGION"
    -e "AWS_USE_CROSS_REGION=$AWS_USE_CROSS_REGION"
    -e "AUTH_PROVIDER=$AUTH_PROVIDER"
    -e "HOST_WORKSPACE_PATH=$(pwd)"
    -e "PYTHONUNBUFFERED=1"
)

# Add authentication credentials based on provider
if [ "$AUTH_PROVIDER" = "github-copilot" ]; then
    DOCKER_CMD+=(
        -e "GITHUB_COPILOT_ACCESS_TOKEN=$GITHUB_COPILOT_ACCESS_TOKEN"
        -e "GITHUB_COPILOT_REFRESH_TOKEN=$GITHUB_COPILOT_REFRESH_TOKEN"
        -e "GITHUB_COPILOT_EXPIRES=$GITHUB_COPILOT_EXPIRES"
    )
else
    DOCKER_CMD+=(
        -e "MODEL_API_KEY=$MODEL_API_KEY"
    )
fi

DOCKER_CMD+=(
    icr.io/polaris-20251120/opencode-agent:latest
    python /usr/local/bin/run_pipeline-opencode.py
    --policy "policy_goal.txt"
    --output-dir "$OUTPUT_DIR"
    --max-workers "$MAX_WORKERS"
    --model-base-url "$MODEL_BASE_URL"
    --model-name "$MODEL_NAME"
    --api-provider "$API_PROVIDER"
    --aws-region "$AWS_REGION"
)

# Add API key only for non-GitHub Copilot providers
if [ "$AUTH_PROVIDER" != "github-copilot" ]; then
    DOCKER_CMD+=(--api-key "$MODEL_API_KEY")
fi

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
echo "Phase 3: Deploy to External Repository"
echo "=========================================="
echo ""

# Check if summary.md exists
summary_file="$OUTPUT_DIR/summary.md"
if [ ! -f "$summary_file" ]; then
    echo "Error: summary.md not found in $OUTPUT_DIR"
    echo "Pipeline may have failed. Please check the logs."
    exit 1
fi

# Arrays to track results
declare -a DEPLOYED_POLICIES
declare -a FAILED_POLICIES

# Parse summary.md to get policy status
# Skip header lines and extract policy information from the table
while IFS='|' read -r _ policy_name _ status _ _ _ _; do
    # Skip header and separator lines
    [[ "$policy_name" =~ ^[[:space:]]*Policy[[:space:]]*Name ]] && continue
    [[ "$policy_name" =~ ^[[:space:]]*-+[[:space:]]*$ ]] && continue
    [[ -z "$policy_name" ]] && continue
    
    # Trim whitespace
    policy_name=$(echo "$policy_name" | xargs)
    status=$(echo "$status" | xargs)
    
    # Extract policy name from parentheses if present
    # Example: "ACM RSA Certificate Key Length Policy (acm-rsa-certificate-key-length-atleast-2048)"
    if [[ "$policy_name" =~ \(([^\)]+)\) ]]; then
        policy_slug="${BASH_REMATCH[1]}"
    else
        policy_slug="$policy_name"
    fi
    
    # Normalize policy name for comparison: convert spaces to hyphens and lowercase
    # "CloudTrail S3 Bucket Access Logging Enabled" -> "cloudtrail-s3-bucket-access-logging-enabled"
    normalized_policy_name=$(echo "$policy_name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
    
    # Check status
    if [[ "$status" == *"Success"* ]] || [[ "$status" == "✅ Success" ]]; then
        # Find corresponding policy directory by matching policy title in report.md
        policy_found=false
        for policy_dir in "$OUTPUT_DIR"/*/; do
            if [ ! -d "$policy_dir" ]; then
                continue
            fi
            
            # Skip goals directory
            if [ "$(basename "$policy_dir")" = "goals" ]; then
                continue
            fi
            
            policy_dir_name=$(basename "$policy_dir")
            
            # Extract policy title from report.md
            report_file="$policy_dir/report.md"
            if [ ! -f "$report_file" ]; then
                continue
            fi
            
            # Extract policy title from report.md (first # heading or "Policy Name:" field)
            report_policy_name=$(grep -E "^# Policy Report:|^# [A-Z]|^\*\*Policy Name:\*\*" "$report_file" | head -1 | sed -E 's/^# Policy Report: //;s/^# //;s/^\*\*Policy Name:\*\* //')
            
            # Normalize report policy name for comparison
            normalized_report_name=$(echo "$report_policy_name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
            
            # Also try without trailing " Policy" for flexible matching
            normalized_report_name_no_policy=$(echo "$report_policy_name" | sed 's/ Policy$//' | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
            
            # Check if this matches the current policy name from summary (try both patterns)
            if [ "$normalized_report_name" != "$normalized_policy_name" ] && [ "$normalized_report_name_no_policy" != "$normalized_policy_name" ]; then
                # If no exact match, try LLM-based matching
                if command -v python3 &> /dev/null && [ -f "llm_match_policy.py" ]; then
                    llm_result=$(python3 llm_match_policy.py "$policy_name" "$report_policy_name" 2>/dev/null || echo "NO_MATCH")
                    if [ "$llm_result" != "MATCH" ]; then
                        continue
                    fi
                    echo "  ℹ️  Matched by LLM: '$policy_name' ≈ '$report_policy_name'"
                else
                    continue
                fi
            fi
            
            # Now we found the matching policy directory, extract sentinel path
            # Extract sentinel path from report.md by searching for "input-TIMESTAMP/xxx.sentinel" or "input/xxx.sentinel" pattern
            sentinel_path=$(grep -o "${INPUT_DIR}/[^[:space:]]*\.sentinel\|input/[^[:space:]]*\.sentinel" "$report_file" | head -n 1 | sed "s|${INPUT_DIR}/||" | sed 's|input/||')
            
            # If sentinel_path not found in report.md, try matching by Sentinel code from requirement.txt
            if [ -z "$sentinel_path" ]; then
                requirement_file="$policy_dir/requirement.txt"
                if [ -f "$requirement_file" ]; then
                    # Extract Sentinel code from requirement.txt (lines starting with import until # Rules)
                    sentinel_code=$(sed -n '/^import /,/^# Rules/p' "$requirement_file" | grep -v "^# Rules")
                    
                    if [ -n "$sentinel_code" ]; then
                        # Find matching .sentinel file in INPUT_DIR by comparing code similarity
                        best_match=""
                        best_similarity=0
                        
                        while IFS= read -r -d '' candidate_file; do
                            candidate_content=$(cat "$candidate_file")
                            
                            # Simple similarity check: count matching lines
                            matching_lines=$(echo "$sentinel_code" | grep -Fxf <(echo "$candidate_content") 2>/dev/null | wc -l)
                            total_lines=$(echo "$sentinel_code" | wc -l)
                            
                            if [ $total_lines -gt 0 ]; then
                                similarity=$((matching_lines * 100 / total_lines))
                                
                                if [ $similarity -gt $best_similarity ]; then
                                    best_similarity=$similarity
                                    best_match="$candidate_file"
                                fi
                            fi
                        done < <(find "$INPUT_DIR" -type f -name "*.sentinel" -print0)
                        
                        # Use best match if similarity is above threshold (e.g., 30%)
                        if [ $best_similarity -gt 30 ] && [ -n "$best_match" ]; then
                            sentinel_path="${best_match#$INPUT_DIR/}"
                            echo "  ℹ️  Matched by code similarity ($best_similarity%): $sentinel_path"
                        fi
                    fi
                fi
            fi
            
            if [ -z "$sentinel_path" ]; then
                echo "  ⚠️  Warning: Could not find sentinel path for '$policy_name' in $policy_dir_name"
                continue
            fi
            
            # Extract directory and basename
            sentinel_dir=$(dirname "$sentinel_path")
            sentinel_basename=$(basename "$sentinel_path" .sentinel)
            
            # Determine target directory in external repo (under tfpolicy subdirectory)
            if [ "$sentinel_dir" = "." ]; then
                target_dir="$EXTERNAL_REPO_DIR/tfpolicy/$sentinel_basename"
            else
                target_dir="$EXTERNAL_REPO_DIR/$sentinel_dir/tfpolicy/$sentinel_basename"
            fi
            
            # Create target directory if it doesn't exist
            mkdir -p "$target_dir"
            
            # Check if all required files exist (try both naming patterns for policytest file)
            policytest_file=""
            if [ -f "$policy_dir/policy.policytest.hcl" ]; then
                policytest_file="$policy_dir/policy.policytest.hcl"
            elif [ -f "$policy_dir/test.policytest.hcl" ]; then
                policytest_file="$policy_dir/test.policytest.hcl"
            fi
            
            if [ ! -f "$policy_dir/policy.policy.hcl" ] || [ -z "$policytest_file" ] || [ ! -f "$policy_dir/main.tf" ] || [ ! -f "$policy_dir/report.md" ]; then
                FAILED_POLICIES+=("$sentinel_path (missing files)")
                policy_found=true
                break
            fi
            
            echo "📦 Deploying: $policy_dir_name → tfpolicy/$sentinel_basename/"
            
            # Copy and rename files to target directory
            cp "$policy_dir/policy.policy.hcl" "$target_dir/$sentinel_basename.policy.hcl"
            echo "  ✓ $sentinel_basename.policy.hcl"
            
            cp "$policytest_file" "$target_dir/$sentinel_basename.policytest.hcl"
            echo "  ✓ $sentinel_basename.policytest.hcl"
            
            cp "$policy_dir/main.tf" "$target_dir/$sentinel_basename.tf"
            echo "  ✓ $sentinel_basename.tf"
            
            cp "$policy_dir/report.md" "$target_dir/$sentinel_basename.report.md"
            echo "  ✓ $sentinel_basename.report.md"
            
            DEPLOYED_POLICIES+=("$sentinel_path")
            policy_found=true
            echo ""
            break
        done
        
        if [ "$policy_found" = false ]; then
            echo "⚠️  Warning: Could not find policy directory for '$policy_name'"
        fi
    else
        # Policy failed or had error
        # Find corresponding sentinel name by matching sentinel file name
        for policy_dir in "$OUTPUT_DIR"/*/; do
            if [ ! -d "$policy_dir" ]; then
                continue
            fi
            
            if [ "$(basename "$policy_dir")" = "goals" ]; then
                continue
            fi
            
            report_file="$policy_dir/report.md"
            if [ ! -f "$report_file" ]; then
                continue
            fi
            
            # Extract sentinel path from report.md
            sentinel_path=$(grep -o "${INPUT_DIR}/[^[:space:]]*\.sentinel\|input/[^[:space:]]*\.sentinel" "$report_file" | head -n 1 | sed "s|${INPUT_DIR}/||" | sed 's|input/||')
            
            if [ -z "$sentinel_path" ]; then
                continue
            fi
            
            # Extract just the filename without extension
            sentinel_basename=$(basename "$sentinel_path" .sentinel)
            
            # Check if this matches the current policy name from summary
            if [ "$sentinel_basename" != "$policy_name" ]; then
                continue
            fi
            
            FAILED_POLICIES+=("$sentinel_path ($status)")
            break
        done
    fi
done < <(grep -A 1000 "^| Policy Name" "$summary_file" | grep "^|")

echo "=========================================="
echo "✓ Deployment Complete!"
echo "=========================================="
echo ""
echo "Summary:"
echo "  Deployed: ${#DEPLOYED_POLICIES[@]} policies"
echo "  Failed: ${#FAILED_POLICIES[@]} policies"
echo "  Target: $EXTERNAL_REPO_DIR"
echo ""

if [ ${#DEPLOYED_POLICIES[@]} -gt 0 ]; then
    echo "Successfully Deployed Policies:"
    for policy in "${DEPLOYED_POLICIES[@]}"; do
        echo "  ✓ $policy"
    done
    echo ""
fi

if [ ${#FAILED_POLICIES[@]} -gt 0 ]; then
    echo "Failed Policies (NOT deployed to external repo):"
    for policy in "${FAILED_POLICIES[@]}"; do
        echo "  ✗ $policy"
    done
    echo ""
fi

echo "MCP Servers are still running:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "To stop MCP servers:"
echo "  ./stop.sh"
echo ""
echo "Note: This script uses images from IBM Cloud Container Registry."
echo "Make sure you have pulled the latest images before running."
echo ""