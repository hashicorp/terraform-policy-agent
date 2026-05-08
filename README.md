# TF Policy Agent User Guide

## Prerequisites
- Docker installed and running
- LLM API key (Bedrock or LiteLLM)
- Access to IBM Cloud Container Registry (for pulling pre-built images)

## Setup

### 1. Pull Docker Images

First, authenticate with IBM Cloud Container Registry and pull the required images:

```bash
# Login to IBM Cloud Container Registry
docker login icr.io -u iamapikey
# Login with the API Key

# Pull required images
docker pull icr.io/polaris-20251120/opencode-agent:latest
docker pull icr.io/polaris-20251120/mcp-server:latest

# Logout from registry
docker logout icr.io
```

**Note:** Contact your administrator to obtain the IBM Cloud Container Registry API key.

### 2. Clone Repository

Clone this repository to obtain the required files:

```bash
git clone git@github.ibm.com:project-polaris/tfpolicy-agent.git
cd tfpolicy-agent
```

### 3. Create Configuration Files

Create a `.env` file in this directory:

**Example `.env` for Bedrock:**
```bash
API_PROVIDER=bedrock
MODEL_NAME=anthropic.claude-opus-4-5-20251101-v1:0 # change model
MODEL_API_KEY=your-bearer-token
AWS_REGION=us-east-1
OUTPUT_DIR=./output_20260409_run1
MAX_WORKERS=5
```

**Example `.env` for LiteLLM:**
```bash
API_PROVIDER=litellm
MODEL_BASE_URL=https://your-litellm-endpoint.com
MODEL_NAME=aws/claude-sonnet-4-5 # change model
MODEL_API_KEY=your-api-key
OUTPUT_DIR=./output_20260409_run1
MAX_WORKERS=5
```

**Example `.env` for openai-compatible model:**
```bash
API_PROVIDER=openai-compatible
MODEL_BASE_URL=https://your-endpoint.com
MODEL_NAME=aws/claude-sonnet-4-5 # change model
MODEL_API_KEY=your-api-key
OUTPUT_DIR=./output_20260409_run1
MAX_WORKERS=5
```

**Required variables:**
- `MODEL_API_KEY` - Your API key (Bearer token for Bedrock, or API key for LiteLLM)
- `OUTPUT_DIR` - Output directory for generated policies (must be unique for each run)
- `API_PROVIDER` - API provider (`bedrock` or `litellm`, default: `litellm`)
- `MODEL_NAME` - Model name (default depends on provider)
- `MODEL_BASE_URL` - Base URL for LiteLLM (not used for Bedrock)
- `AWS_REGION` - AWS region (default: `us-east-1`, not used for LiteLLM)
- `MAX_WORKERS` - Number of parallel workers (default: `5`)

### 4. Create policy_goal.txt (skip this when you use External Repository Integration Run)

Create a `policy_goal.txt` file in this directory to specify which policies to generate:

**Sentinel policy conversion:**
````
Generate TF Policy for
```
import "tfplan/v2" as tfplan
import "tfresources" as tf
import "report" as report
import "collection" as collection
import "collection/maps" as maps

const = {
	"policy_name":                "cloudtrail-log-file-validation-enabled",
	"message":                    "Attribute 'enable_log_file_validation' must be true for 'aws_cloudtrail' resources.",
	"resource_aws_cloudtrail":    "aws_cloudtrail",
	"enable_log_file_validation": "enable_log_file_validation",
}

resources = tf.plan(tfplan.planned_values.resources).type(const.resource_aws_cloudtrail).resources
violations = collection.reject(resources, func(res) {
	return maps.get(res, "values." + const.enable_log_file_validation, false)
})

summary = {
	"policy_name": const.policy_name,
	"violations": map violations as _, v {
		{
			"address":        v.address,
			"module_address": v.module_address,
			"message":        const.message,
		}
	},
}

print(report.generate_policy_report(summary))
main = rule {
	violations is empty
}
```
````

**Sentinel file paths (files must be in the same directory):**
```
Generate TF Policy for
./input/policy1.sentinel
./input/policy2.sentinel
```
Note: Files must be placed within the project directory.

**Policy IDs:**
```
Generate TF Policy for
SecurityHub: IAM.21,IAM.1
```

**Natural language queries:**
```
Generate TF Policy for
All S3-related policies from SecurityHub
```

## Run

### Option 1: Standard Run (Manual Input)

The [`image_run.sh`](image_run.sh) script will:
1. Check if required images are available locally
2. Start MCP servers
3. Execute the policy generation pipeline

**Run all stages:**
```bash
./image_run.sh
```

**Run specific stage only:**
```bash
# Stage 0: Policy Extraction
./image_run.sh --step 0

# Stage 1: Requirement Generation
./image_run.sh --step 1

# Stage 2: Policy Generation
./image_run.sh --step 2

# Stage 3: Summary Generation
./image_run.sh --step 3
```

**Pipeline Stages:**
- **Stage 0**: Extract and split policies into individual goal files
- **Stage 1**: Generate requirements for each policy (parallel execution)
- **Stage 2**: Generate policies and test cases (parallel execution)
- **Stage 3**: Generate summary report

**Important:**
- Make sure you have pulled the Docker images before running this script (see Setup step 1)
- When running individual stages, ensure previous stages have completed successfully
- The pipeline displays real-time progress including stage information and parallel execution status

### Option 2: External Repository Integration (Automated)

The [`run_with_external_repo.sh`](run_with_external_repo.sh) script automates the entire workflow for converting Sentinel policies from an external repository:

**Features:**
- Automatically extracts unconverted Sentinel files from external repository
- Preserves directory structure
- Skips already converted policies (checks for existing `.policy.hcl` files)
- Deploys generated policies back to `tfpolicy/` subdirectories in the external repo

**Setup:**

Add the external repository path to your [`.env`](.env) file:
```bash
EXTERNAL_REPO_DIR=/path/to/target-dir
```

**Run all stages:**
```bash
./run_with_external_repo.sh
```

**Run specific pipeline stage only (Phase 2):**
```bash
# Stage 0: Policy Extraction
./run_with_external_repo.sh --step 0

# Stage 1: Requirement Generation
./run_with_external_repo.sh --step 1

# Stage 2: Policy Generation
./run_with_external_repo.sh --step 2

# Stage 3: Summary Generation
./run_with_external_repo.sh --step 3
```

**Note:** The `--step` option only affects Phase 2 (pipeline execution). Phase 1 (Sentinel extraction) and Phase 3 (deployment) always run when using this script.

### Stop Services
```bash
./stop.sh
```

## View Results

Generated policies are saved in the directory specified by `OUTPUT_DIR` in `.env`:

```bash
# View summary (replace OUTPUT_DIR with your actual directory)
cat <OUTPUT_DIR>/summary.md

# List generated policies
ls <OUTPUT_DIR>/

# View individual policy
cat <OUTPUT_DIR>/<POLICY_NAME>/report.md
cat <OUTPUT_DIR>/<POLICY_NAME>/policy.policy.hcl
```

Each policy directory contains:
- `requirement.txt` - Policy requirements
- `policy.policy.hcl` - Generated TF Policy
- `main.tf` - Test configuration
- `test.policytest.hcl` - Test cases
- `report.md` - Validation results and test outcomes