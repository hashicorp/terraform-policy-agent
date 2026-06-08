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

The agent runs in a container, so you'll need `docker` available on your system.

**Docker Image**:

Pull the pre-built Docker image from the registry:

```bash
# Login to IBM Cloud Container Registry
docker login icr.io -u iamapikey
# When prompted, enter your API key
docker pull icr.io/polaris-20251120/terraform-pac-agent:0.0.23-footer-1
```

**Required Binaries**:

Download the following **Linux** binaries (used inside the container). The architecture must match your host machine:

- **Terraform CLI**: Currently in beta. Contact your HashiCorp representative to obtain the binary.
  - Required architecture: Linux ARM64 (for M1/M2 Mac) or Linux AMD64 (for Intel Mac/Linux)

- **TFPolicy CLI**: Currently in beta. Contact your HashiCorp representative to obtain the binary.
  - Required architecture: Linux ARM64 (for M1/M2 Mac) or Linux AMD64 (for Intel Mac/Linux)

**Required MCP Server**:

- **terraform-mcp-server**: HashiCorp's MCP server for Terraform operations
  - Must be running on `localhost:8500`
  - For detailed setup instructions, see: [terraform-mcp-server repository](https://github.com/hashicorp/terraform-mcp-server)
  
  **Recommended Setup:**
  
  Pull and run the MCP server:
  
  ```bash
  # Pull the Docker image
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
  
  **Verify connectivity from the terraform-pac-agent container:**
  
  ```bash
  docker run --rm -it --entrypoint "" \
    icr.io/polaris-20251120/terraform-pac-agent:0.0.23-footer-1 \
    curl http://host.docker.internal:8500/health
  ```
  
  Expected response:
  ```json
  {"status":"ok","service":"terraform-mcp-server","transport":"streamable-http","endpoint":"/mcp"}
  ```

### 3. Configure Environment

Create `.env` file from the example:

```bash
cp .env.example .env
# Edit .env with your configuration
```

#### Authentication Configuration

Choose one of the following authentication providers:

**Option A: LiteLLM (Default)**

```bash
AUTH_PROVIDER=litellm
MODEL_BASE_URL=https://your-litellm-endpoint.com
MODEL_NAME=aws/claude-sonnet-4-5
MODEL_API_KEY=sk-your-litellm-api-key
```

- `AUTH_PROVIDER`: Set to `litellm`
- `MODEL_BASE_URL`: Your LiteLLM endpoint URL
- `MODEL_NAME`: Model identifier (e.g., `aws/claude-sonnet-4-5`)
- `MODEL_API_KEY`: Your LiteLLM API key

**Option B: GitHub Copilot**

```bash
AUTH_PROVIDER=github-copilot
MODEL_NAME=claude-sonnet-4.6
GITHUB_COPILOT_ACCESS_TOKEN=gho_your_access_token
GITHUB_COPILOT_REFRESH_TOKEN=gho_your_refresh_token  # Optional, defaults to access token
GITHUB_COPILOT_EXPIRES=0  # Optional, defaults to 0
```

- `AUTH_PROVIDER`: Set to `github-copilot`
- `MODEL_NAME`: Select a GitHub Copilot supported model (e.g., `claude-sonnet-4.6`, `gpt-5.2`)
  - Supported models (verified as of June 2026): `claude-sonnet-4.6`, `gpt-5.2`
  - Note: `claude-sonnet-4.5` is NOT supported by GitHub Copilot (verified as of June 2026)
  - You can switch between supported models without changing the access token
- `GITHUB_COPILOT_ACCESS_TOKEN`: Your GitHub Copilot access token
- `GITHUB_COPILOT_REFRESH_TOKEN`: (Optional) Refresh token, defaults to access token if not set
- `GITHUB_COPILOT_EXPIRES`: (Optional) Token expiration timestamp, defaults to 0

**How to get GitHub Copilot tokens:**

**Recommended: Using Docker container (no local installation required)**

Run the following command to obtain tokens in an isolated container environment:

```bash
docker run --rm -it --entrypoint "" \
  icr.io/polaris-20251120/terraform-pac-agent:0.0.23-footer-1 \
  sh -c 'opencode auth login && cat $HOME/.local/share/opencode/auth.json'
```

This will:
1. Launch the OpenCode authentication flow in an isolated container
2. Prompt you to select GitHub Copilot as the provider
3. Choose deployment type (usually GitHub.com)
4. Display a login URL (e.g., `https://github.com/login/device`) and code
5. After you authorize in your browser, display the tokens from `auth.json`

![GitHub Copilot Access Setup](github-copilot-access-setup.png)

**Alternative: Using local OpenCode installation**

If you prefer to install OpenCode locally, you can run:

```bash
opencode auth login
cat ~/.local/share/opencode/auth.json
```

Note: This requires OpenCode to be installed on your system. The container method is recommended as it keeps your system clean and isolated.

#### Complete `.env` Example

```bash
# Authentication (choose one option above)
AUTH_PROVIDER=litellm
MODEL_BASE_URL=https://your-litellm-endpoint.com
MODEL_NAME=aws/claude-sonnet-4-5
MODEL_API_KEY=sk-your-litellm-api-key

# Data directories
DATA_DIR=./data  # Create this from sample-data/ or your own structure
INPUT_DIR=input
INPUT_FILE=policy_goal.txt
OUTPUT_DIR=output

# Execution
MAX_WORKERS=5
IMAGE_NAME=icr.io/polaris-20251120/terraform-pac-agent
IMAGE_TAG=0.0.23-footer-1

# Binaries (required - must match container architecture)
# M1/M2 Mac: use linux-arm64 binaries
# Intel Mac/Linux: use linux-amd64 binaries
TERRAFORM_BINARY_PATH=/path/to/terraform
TFPOLICY_BINARY_PATH=/path/to/tfpolicy

# Stage 0: Extraction timeout
STAGE0_TIMEOUT=600  # Optional, defaults to 600 (10 minutes)

# Stage 1: Requirement Generation timeout (per goal)
STAGE1_TIMEOUT=300  # Optional, defaults to 300 (5 minutes)

# Stage 2: Policy Generation timeout (per policy)
STAGE2_TIMEOUT=900  # Optional, defaults to 600 (10 minutes)
# Note: For complex policies, consider increasing to 900 or more (15 minutes)

# Stage 3: Summary Generation timeout
# Total timeout = STAGE3_TIMEOUT_BASE + (policy_count * STAGE3_TIMEOUT_PER_POLICY)
STAGE3_TIMEOUT_BASE=180  # Optional, defaults to 180 (3 minutes base)
STAGE3_TIMEOUT_PER_POLICY=60  # Optional, defaults to 60 (1 minute per policy)
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

**Output:**

When using `run.sh`, output files are generated in the directory specified by `OUTPUT_DIR` in your `.env` file (default: `data/output`):

```sh
$ ls ./data/output
CloudFront_Associated_WAF   goals                   summary.json
stage0_extraction.log       stage3_summary.log      summary.md
```

**Important:** The `OUTPUT_DIR` must be empty before running the full pipeline to prevent accidental overwrites. If you need to run multiple conversions, set a different `OUTPUT_DIR` in `.env` for each run (e.g., `OUTPUT_DIR=output-v2`, `OUTPUT_DIR=results-20260603`).

### 7. Run with External Repository (Alternative)

If you want to convert Sentinel libraries from an external repository (e.g., HashiCorp's CIS Policy Set for AWS Terraform):

Example repository: https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform/tree/main/policies/cloudtrail

**Step 1: Download the external repository**

```bash
curl -L https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform/archive/refs/heads/main.zip | tar xz -C /tmp
```

**Step 2: Verify the repository structure**

```bash
$ ls /tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main
CONTRIBUTING.md LICENSE         modules         README.md
docs            Makefile        policies        sentinel.hcl
```

**Step 3: Set the external repository path in `.env`**

For example, if you want to convert `policies/cloudtrail`:

```bash
EXTERNAL_REPO_DIR=/tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main/policies/cloudtrail
```

**Step 4: Run the pipeline with the external repository**

```bash
./run_with_external_repo.sh
```

**Output:**

When using `run_with_external_repo.sh`, the script automatically creates timestamped directories for each run:
- Input: `data/input-YYYYMMDD_HHMMSS/`
- Output: `data/output-YYYYMMDD_HHMMSS/`

**Note:** The `OUTPUT_DIR` setting in `.env` is **ignored** when using `run_with_external_repo.sh`. This automatic timestamping prevents conflicts when processing multiple batches and allows you to keep historical results.

The final converted policies will be created under `EXTERNAL_REPO_DIR/tfpolicy`, with each Sentinel policy having a corresponding Terraform policy directory.

Example output structure:

```
/tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main/policies/cloudtrail/tfpolicy
├── cloudtrail-bucket-access-logging-enabled
│   ├── cloudtrail-bucket-access-logging-enabled.policy.hcl
│   ├── cloudtrail-bucket-access-logging-enabled.policytest.hcl
│   ├── cloudtrail-bucket-access-logging-enabled.report.md
│   └── cloudtrail-bucket-access-logging-enabled.tf
├── cloudtrail-cloudwatch-logs-group-arn-present
│   ├── cloudtrail-cloudwatch-logs-group-arn-present.policy.hcl
│   ├── cloudtrail-cloudwatch-logs-group-arn-present.policytest.hcl
│   ├── cloudtrail-cloudwatch-logs-group-arn-present.report.md
│   └── cloudtrail-cloudwatch-logs-group-arn-present.tf
├── cloudtrail-log-file-validation-enabled
│   ├── cloudtrail-log-file-validation-enabled.policy.hcl
│   ├── cloudtrail-log-file-validation-enabled.policytest.hcl
│   ├── cloudtrail-log-file-validation-enabled.report.md
│   └── cloudtrail-log-file-validation-enabled.tf
├── cloudtrail-logs-bucket-not-public
│   ├── cloudtrail-logs-bucket-not-public.policy.hcl
│   ├── cloudtrail-logs-bucket-not-public.policytest.hcl
│   ├── cloudtrail-logs-bucket-not-public.report.md
│   └── cloudtrail-logs-bucket-not-public.tf
└── cloudtrail-server-side-encryption-enabled
    ├── cloudtrail-server-side-encryption-enabled.policy.hcl
    ├── cloudtrail-server-side-encryption-enabled.policytest.hcl
    ├── cloudtrail-server-side-encryption-enabled.report.md
    └── cloudtrail-server-side-encryption-enabled.tf
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
    │   ├── <policy_name>.policy.hcl
    │   ├── <policy_name>.policytest.hcl
    │   ├── main.tf
    │   ├── gwt.json
    │   └── report.md
    ├── summary.md
    └── summary.json
```

## Using the Skill with a Coding Agent

You can also use the packaged skill with a coding agent instead of running commands manually.

### 1. Place the skill in your agent's skill directory

Place the skill in the appropriate directory for your coding agent:

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

### 2. Start your coding agent with your preferred provider and model

Configure your coding agent (OpenCode or GitHub Copilot CLI) to use your LLM provider and model as usual.

### 3. Open the skills menu and select the skill

In your coding agent:

- type `/skills`
- select `tfpac-setup`

The skill will then guide the workflow in this order:

1. **Input setup assistance**
   - Help create `.env` file from `.env.example`
   - Guide creation of `data/input/policy_goal.txt`
   - Assist with placing Sentinel files in `data/input/sentinels/` if needed
2. **Prerequisite check**
   - Verify Docker image availability
   - Check required binaries (terraform, tfpolicy)
   - Validate MCP server connection
3. **Pipeline run**
   - Show how to execute the conversion pipeline with `./run.sh` or `./run_with_external_repo.sh`


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