# Terraform Policy Agent - User Guide

## Table of Contents
1. [Overview](#overview)
2. [Quick Start - Using with Coding Agents](#quick-start---using-with-coding-agents)
3. [What You'll Need](#what-youll-need)
4. [Step-by-Step Setup](#step-by-step-setup)
5. [Running Your First Conversion](#running-your-first-conversion)
6. [Understanding the Output](#understanding-the-output)
7. [Advanced Usage](#advanced-usage)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The Terraform Policy Agent is a tool that automatically converts Sentinel policies to Terraform Policy (TFPolicy) format. This guide will walk you through the complete setup and usage process.

**What this tool does:**
- Converts Sentinel policy code to TFPolicy format
- Generates test cases automatically
- Creates comprehensive documentation
- Validates the converted policies

**Time to complete:** Approximately 30 minutes for first-time setup

---

## Quick Start - Using with Coding Agents

**Simplify configuration setup!** If you have a coding agent like OpenCode or GitHub Copilot CLI, you can use the packaged skill for an interactive `.env` file creation.

### Prerequisites

**Before using the skill, you must complete [Step 1](#step-1-clone-the-repository) through [Step 4](#step-4-prepare-required-binaries) manually:**
- Step 1: Clone the Repository
- Step 2: Pull the Docker Image
- Step 3: Setup MCP Server
- Step 4: Prepare Required Binaries

**The skill will help you with:**
- Step 5: Configure Authentication (interactive)
- Step 6: Create Configuration File (automated)
- Step 7: Prepare Your Data Directory (guided)

### Setup

**For OpenCode:**

```bash
mkdir -p .opencode/skills
cp -R skills/tfpac-setup .opencode/skills/
```

**For GitHub Copilot CLI:**

```bash
mkdir -p .github/skills
cp -R skills/tfpac-setup .github/skills/
```

### Usage

1. Start your coding agent
2. Type `/skills`
3. Select `tfpac-setup`
4. Follow the interactive workflow

📸 **Screenshot needed:** Coding agent skill selection screen. After entering `/skills` command, showing `tfpac-setup` skill displayed. Highlight selectable skills with blue boxes.

**Note:** If you prefer complete manual setup, continue to the [Step-by-Step Setup](#step-by-step-setup) section below.

---

## What You'll Need

Before starting, make sure you have:

### Required Software
- For example: **Docker Desktop**, **Rancher Desktop**
  - Docker Desktop: https://www.docker.com/products/docker-desktop
  - Rancher Desktop: https://rancherdesktop.io/
  - Verify installation: `docker --version`

### Required Access
- **IBM Cloud Container Registry access** (for Docker image)
- **HashiCorp beta binaries** (contact your HashiCorp representative)
  - Terraform CLI (beta version)
  - TFPolicy CLI (beta version)

### Authentication (Choose One)
- **Option A:** LiteLLM endpoint with API key
- **Option B:** GitHub Copilot access

---

## Step-by-Step Setup

### Step 1: Clone the Repository

Open your terminal and run:

```bash
git clone https://github.com/hashicorp/terraform-policy-agent.git
cd terraform-policy-agent
```

**Expected result:**
```
$ ls
README.md           run.sh              stop.sh
sample-data/        run_pipeline.py     skills/
.env.example        run_with_external_repo.sh
```

📸 **Screenshot needed:** Terminal output of `ls` command. Verify that the above file list is displayed.

---

### Step 2: Pull the Docker Image

Login to IBM Cloud Container Registry and pull the agent image:

```bash
# Login to registry
docker login icr.io -u iamapikey
# Enter your API key when prompted

# Pull the image
docker pull icr.io/polaris-20251120/terraform-pac-agent:0.0.24
```

**Expected output:**
```
Status: Downloaded newer image for icr.io/polaris-20251120/terraform-pac-agent:0.0.24
```

📸 **Screenshot needed:** Docker pull command execution result. Screen showing "Status: Downloaded newer image" message.

---

### Step 3: Setup MCP Server

The agent requires a running MCP (Model Context Protocol) server for Terraform operations.

**Pull and run the MCP server:**

```bash
# Pull the MCP server image
docker pull docker.io/hashicorp/terraform-mcp-server:0.3.3

# Run the MCP server
docker run -d \
  --name terraform-mcp-server \
  -p 8500:8080 \
  -e TRANSPORT_MODE=streamable-http \
  -e TRANSPORT_HOST=0.0.0.0 \
  -e MCP_SESSION_MODE=stateless \
  --restart unless-stopped \
  docker.io/hashicorp/terraform-mcp-server:0.3.3
```

**Verify the server is running:**

```bash
docker run --rm -it --entrypoint "" \
  icr.io/polaris-20251120/terraform-pac-agent:0.0.24 \
  curl http://host.docker.internal:8500/health
```

**Expected response:**
```json
{"status":"ok","service":"terraform-mcp-server","transport":"streamable-http","endpoint":"/mcp"}
```

📸 **Screenshot needed:** MCP server health check result. Screen showing JSON response with `"status":"ok"`. Highlight with green box.

---

### Step 4: Prepare Required Binaries

Download the Linux binaries for Terraform and TFPolicy from your HashiCorp representative.

**Important:** The binaries must match your host architecture:
- **M1/M2 Mac:** Use `linux-arm64` binaries
- **Intel Mac/Linux:** Use `linux-amd64` binaries

Place the binaries in a known location, for example:
```bash
mkdir -p ~/terraform-binaries
# Copy your downloaded binaries here
```

📸 **Screenshot needed:** Output of `ls -la` command in the directory where binary files are placed. Verify that terraform and tfpolicy have execute permissions (`-rwxr-xr-x`). Point to execute permissions with red arrows.

---

### Step 5: Configure Authentication

Choose your authentication method and obtain credentials.

#### Option A: LiteLLM (Recommended for Enterprise)

If you have a LiteLLM endpoint, you'll need:
- Endpoint URL
- API Key
- Model name

📸 **Screenshot needed:** LiteLLM admin screen or documentation page. Highlight the section showing API key and endpoint URL in yellow.

#### Option B: GitHub Copilot

Run this command to get your GitHub Copilot tokens:

```bash
docker run --rm -it --entrypoint "" \
  icr.io/polaris-20251120/terraform-pac-agent:0.0.24 \
  sh -c 'opencode auth login && cat $HOME/.local/share/opencode/auth.json'
```

**Follow the prompts:**
1. Select "GitHub Copilot" as provider
2. Choose deployment type (usually "GitHub.com")
3. Open the displayed URL in your browser
4. Enter the device code shown
5. Authorize the application

📸 **Screenshot needed (3 images):**
1. Authentication URL and device code displayed in terminal. Surround URL and code with red boxes.
2. GitHub authentication screen in browser. Point to "Authorize" button with green arrow.
3. Contents of `auth.json` displayed in terminal. Highlight `access_token` and `refresh_token` lines in yellow.

---

### Step 6: Create Configuration File

Create your `.env` file from the example:

```bash
cp .env.example .env
```

Open `.env` in your editor and configure it:

**For LiteLLM:**
```bash
# Binary Paths
TERRAFORM_BINARY_PATH=/path/to/terraform
TFPOLICY_BINARY_PATH=/path/to/tfpolicy

# Authentication
AUTH_PROVIDER=litellm
MODEL_BASE_URL=https://your-litellm-endpoint.com
MODEL_API_KEY=sk-your-litellm-api-key
MODEL_NAME=aws/claude-sonnet-4-5

# Data directories
DATA_DIR=./data
INPUT_DIR=input
OUTPUT_DIR=output
INPUT_FILE=policy_goal.txt
MAX_WORKERS=5

# Docker
IMAGE_NAME=icr.io/polaris-20251120/terraform-pac-agent
IMAGE_TAG=0.0.24
```

**For GitHub Copilot:**
```bash
# Binary Paths
TERRAFORM_BINARY_PATH=/path/to/terraform
TFPOLICY_BINARY_PATH=/path/to/tfpolicy

# Authentication
AUTH_PROVIDER=github-copilot
MODEL_NAME=claude-sonnet-4.6
GITHUB_COPILOT_ACCESS_TOKEN=gho_your_access_token
GITHUB_COPILOT_REFRESH_TOKEN=gho_your_refresh_token

# Data directories
DATA_DIR=./data
INPUT_DIR=input
OUTPUT_DIR=output
INPUT_FILE=policy_goal.txt
MAX_WORKERS=5

# Docker
IMAGE_NAME=icr.io/polaris-20251120/terraform-pac-agent
IMAGE_TAG=0.0.24
```

📸 **Screenshot needed:** Screen showing `.env` file open in VS Code or any editor. Point to important configuration items (`AUTH_PROVIDER`, `MODEL_NAME`, `TERRAFORM_BINARY_PATH`, `TFPOLICY_BINARY_PATH`) with colored arrows.

---

### Step 7: Prepare Your Data Directory

Create the data directory structure:

```bash
cp -r sample-data data
```

This creates:
```
data/
├── input/
│   ├── policy_goal.txt
│   └── sentinels/
│       └── cloudfront-6.sentinel
└── output/  (will be created during execution)
```

📸 **Screenshot needed:** Output of `tree data` or `ls -R data` command. Verify that directory structure is correctly created.

---

## Running Your First Conversion

### Method 1: Convert Inline Sentinel Code

Edit `data/input/policy_goal.txt` with your Sentinel policy:

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

📸 **Screenshot needed:** Screen showing `policy_goal.txt` file open in editor. Verify that Sentinel code block is correctly formatted. Surround code block start (```sentinel) and end (```) with green boxes.

**Run the pipeline:**

```bash
./run.sh
```

📸 **Screenshot needed:** Terminal screen during `./run.sh` execution. Showing progress of each stage (Stage 0, 1, 2, 3). Highlight messages like "Stage X completed successfully" in green.

---

### Method 2: Convert from Sentinel Files

If you have existing Sentinel files:

1. Place your `.sentinel` files in `data/input/sentinels/`
2. Edit `data/input/policy_goal.txt`:

```
Generate TF Policy for
./data/input/sentinels/policy1.sentinel
./data/input/sentinels/policy2.sentinel
```

3. Run the pipeline:

```bash
./run.sh
```

---

### Method 3: Convert External Repository

To convert policies from an external repository (e.g., HashiCorp's CIS Policy Set):

**Step 1:** Download the repository:

```bash
curl -L https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform/archive/refs/heads/main.zip | tar xz -C /tmp
```

**Step 2:** Configure the external repository path in `.env`:

```bash
EXTERNAL_REPO_DIR=/tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main/policies/cloudtrail
```

**Step 3:** Run the pipeline:

```bash
./run_with_external_repo.sh
```

📸 **Screenshot needed:** Screen during conversion execution from external repository. Show timestamped directories (`input-YYYYMMDD_HHMMSS`, `output-YYYYMMDD_HHMMSS`) being created.

---

## Understanding the Output

After successful execution, your output directory will contain:

```
data/output/
├── goals/
│   ├── goal-001.txt
│   └── goal-002.txt
├── PolicyName/
│   ├── requirement.txt
│   ├── <policy_name>.policy.hcl
│   ├── <policy_name>.policytest.hcl
│   ├── main.tf
│   ├── gwt.json
│   └── report.md
├── summary.md
└── summary.json
```

### Key Output Files

| File | Description |
|------|-------------|
| `goals/goal-*.txt` | Extracted policy goals from input |
| `requirement.txt` | Detailed requirements for the policy |
| `*.policy.hcl` | Generated TFPolicy code |
| `*.policytest.hcl` | Generated test cases |
| `main.tf` | Terraform configuration for testing |
| `report.md` | Detailed conversion report |
| `summary.md` | Overall summary of all conversions |

📸 **Screenshot needed (2 images):**
1. Display `data/output` directory structure. Show overview using `tree` command or file explorer.
2. Screen showing generated `.policy.hcl` file open in editor. Display TFPolicy code structure. Surround important parts (rule block, condition block) with colored boxes.

---

### Reviewing Conversion Results

#### Step 1: Check the Summary Report

Open `data/output/summary.md` to get an overview of all conversions:

- **Conversion Statistics:** Success rate, total policies processed
- **Policy List:** Each policy's name, status, and key metrics
- **Quick Status:** See which policies succeeded or failed at a glance

📸 **Screenshot needed:** Screen showing `summary.md` in markdown preview. Display statistics section and policy details table. Color-code successful policies in green and failed policies in red.

#### Step 2: Review Individual Policy Reports

For detailed information about each policy, check the `report.md` file in each policy directory:

```bash
# Example: Review a specific policy's report
cat data/output/PolicyName/report.md
```

Each `report.md` contains:
- **Policy Overview:** What the policy checks
- **Conversion Details:** How Sentinel was translated to TFPolicy
- **Test Results:** Validation status
- **Implementation Notes:** Important considerations

📸 **Screenshot needed:** Screen showing individual policy `report.md` file open in editor or markdown preview. Highlight key sections like policy overview and test results.

---

## Advanced Usage

### Running Individual Stages

You can run specific stages of the pipeline:

```bash
# Stage 0: Extract goals
./run.sh step0-extraction

# Stage 1: Generate requirements for a specific goal
./run.sh step1-requirement --goal-file goal-001.txt

# Stage 2: Generate policy for a specific directory
./run.sh step2-generation --policy-dir CloudFront_Associated_WAF

# Stage 3: Generate summary
./run.sh step3-summary
```

📸 **Screenshot needed:** Terminal screen of individual stage execution. Show example of `./run.sh step1-requirement --goal-file goal-001.txt` execution.

---

### Using Custom Prompts

Customize the extraction prompt:

```bash
./run.sh step0-extraction --prompt "Extract security policy goals from the input file"
```

---

### Adjusting Timeouts

For complex policies, you may need to increase timeouts in `.env`:

```bash
# For complex policy generation (Stage 2)
STAGE2_TIMEOUT=1200  # 20 minutes

# For large batch summaries (Stage 3)
STAGE3_TIMEOUT_BASE=300  # 5 minutes base
STAGE3_TIMEOUT_PER_POLICY=120  # 2 minutes per policy
```
---

### Getting Help

If you encounter issues not covered here:

1. **Check logs:** Review stage logs in `data/output/stage*.log`
2. **Verify configuration:** Double-check all settings in `.env`

📸 **Screenshot needed:** Screen showing log file (`stage2_generation.log`) open in editor. Highlight error message lines in red.

---

**Document Version:** 1.0  
**Last Updated:** June 2026  