# terraform-pac-agent Quick Start Guide

## Getting Started

### 1. Setup Workspace

Clone the repository:

```bash
git clone https://github.com/hashicorp/terraform-policy-agent.git
cd terraform-policy-agent
```

Your workspace should contain:
```sh
$ ls
README.md           run.sh              stop.sh
sample-data/        run_pipeline.py     skills/
.env.example        run_with_external_repo.sh
```

### 2. Prerequisites

**Docker Image**:

Pull the pre-built Docker image from the registry:

```bash
# Login to IBM Cloud Container Registry
docker login icr.io -u iamapikey
# When prompted, enter your API key

# Pull the image
docker pull icr.io/polaris-20251120/terraform-pac-agent:0.0.11
```

**Required Binaries**:

Download the following **Linux** binaries (used inside the container). The architecture must match your host machine:

- **Terraform CLI**: Download from [HashiCorp Terraform Releases](https://releases.hashicorp.com/terraform/)
  - For M1/M2 Mac (ARM64): `terraform_<version>_linux_arm64.zip`
  - For Intel Mac/Linux (AMD64): `terraform_<version>_linux_amd64.zip`

- **TFPolicy CLI**: Download from [HashiCorp Terraform Policy Releases](https://github.com/hashicorp/terraform-policy/releases)
  - For M1/M2 Mac (ARM64): `tfpolicy_<version>_linux_arm64.zip`
  - For Intel Mac/Linux (AMD64): `tfpolicy_<version>_linux_amd64.zip`

**Required MCP Server**:

- **terraform-mcp-server**: HashiCorp's MCP server for Terraform operations
  - Must be running on `localhost:8500`
  - Download and setup instructions: [terraform-mcp-server repository](https://github.com/hashicorp/terraform-mcp-server)

### 3. Configure Environment

Create `.env` file from the example:

```bash
cp .env.example .env
# Edit .env with your configuration
```

Example `.env`:
```bash
# Authentication (choose one)
AUTH_PROVIDER=litellm
MODEL_BASE_URL=https://your-litellm-endpoint.com
MODEL_NAME=aws/claude-sonnet-4-5
MODEL_API_KEY=sk-your-litellm-api-key

# AUTH_PROVIDER=github-copilot
# MODEL_NAME=claude-sonnet-4.6
# GITHUB_COPILOT_ACCESS_TOKEN=gho_your_access_token
# GITHUB_COPILOT_REFRESH_TOKEN=gho_your_refresh_token  # Optional
# GITHUB_COPILOT_EXPIRES=0  # Optional

# Data directories
DATA_DIR=./data  # Create this from sample-data/ or your own structure
INPUT_DIR=input
INPUT_FILE=policy_goal.txt
OUTPUT_DIR=output

# Execution
MAX_WORKERS=5
IMAGE_NAME=terraform-pac-agent
IMAGE_TAG=0.0.11

# Binaries (required - must match container architecture)
# M1/M2 Mac: use linux-arm64 binaries
# Intel Mac/Linux: use linux-amd64 binaries
TERRAFORM_BINARY_PATH=/path/to/terraform
TFPOLICY_BINARY_PATH=/path/to/tfpolicy
```

### 4. Prepare Data Directory

Create your `data/` directory structure. You can either:

**Option A: Copy from sample-data**
```bash
cp -r sample-data data
```

**Option B: Create your own structure**
```bash
mkdir -p data/input
# Then create your input files
```

### 5. Create Input File

Create `data/input/policy_goal.txt` with your Sentinel policy:

**Option A: Inline Sentinel Code**
````
Generate TF Policy for
```sentinel
import "tfplan/v2" as tfplan
import "tfresources" as tf

resources = tf.plan(tfplan.planned_values.resources).type("aws_s3_bucket").resources
violations = collection.reject(resources, func(res) {
    return maps.get(res, "values.versioning.0.enabled", false)
})

main = rule {
    violations is empty
}
```
````

**Option B: Sentinel File Paths**
```
Generate TF Policy for
./data/input/sentinels/policy1.sentinel
./data/input/sentinels/policy2.sentinel
```

### 6. Run Pipeline

```bash
./run.sh
```

Output files will be generated under `data/output`:

```sh
$ ls ./workspace/data/output 
CloudFront_Associated_WAF   goals                   summary.json
stage0_extraction.log       stage3_summary.log      summary.md
```

## Pipeline Stages

The pipeline runs 4 stages automatically:

- **Stage 0**: Extract policy goals → `data/output/goals/`
- **Stage 1**: Generate requirements → `data/output/PolicyName/requirement.txt`
- **Stage 2**: Generate policies and tests → `data/output/PolicyName/*.hcl`, `*.tf`
- **Stage 3**: Create summary → `data/output/summary.md`

## Output Structure

```
data/
├── input/
│   └── policy_goal.txt
└── output/
    ├── goals/
    │   ├── goal-001.txt
    │   └── goal-002.txt
    ├── PolicyName/
    │   ├── requirement.txt
    │   ├── policy.policy.hcl
    │   ├── test.policytest.hcl
    │   ├── main.tf
    │   ├── gwt.json
    │   └── report.md
    ├── summary.md
    └── summary.json
```

## Using the Skill with a Coding Agent

You can also use the packaged skill with a coding agent instead of running commands manually.

### 1. Place the skill in your agent's skill directory

For example, with OpenCode, place the skill under `.opencode/skills/`.

Example:

```bash
mkdir -p .opencode/skills
cp -R skills/operating-terraform-pac-agent .opencode/skills/
```

### 2. Start OpenCode with your preferred provider and model

Configure OpenCode to use your LLM provider and model as usual.

### 3. Open the skills menu and select the skill

In OpenCode:

- type `/skills`
- select `operating-terraform-pac-agent`

The skill will then guide the workflow in this order:

1. prerequisite check
2. pipeline run
3. output verification

It will also:
- ask whether to run in foreground or background
- ask how to handle existing `data/input` or `data/output` contents before running
- help you inspect generated artifacts after the pipeline completes
- help present results in a readable table
- help answer follow-up questions about the generated policies and outputs

## Advanced Usage

### Run Individual Stages

```bash
./run.sh step0-extraction
./run.sh step1-requirement --goal-file goal-001.txt
./run.sh step2-generation --policy-dir CloudFront_Associated_WAF
./run.sh step3-summary
```

### Custom Prompts

```bash
./run.sh step0-extraction --prompt "Extract goals from input file"
```

### Pipeline Fails
- Check `data/input/policy_goal.txt` exists and is properly formatted
- Verify binary paths in `.env` are correct
- Check logs in `data/output/stage*.log`