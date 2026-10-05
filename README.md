# terraform-policy-agent Quick Start Guide

> **New here?** Follow **[USER_GUIDE.md](USER_GUIDE.md)** for a step-by-step walkthrough. This README is the technical quick-start reference.

## Getting Started

### 1. Setup Workspace

> **NOTE:** Use the `main` branch of this repository.

Prepare this folder.
Your workspace should contain:
```sh
$ ls
README.md           run.sh              stop.sh
sample-data/        run_pipeline.py     skills/
.env.example
```

### 2. Prerequisites

**Python**:

Python 3.10 or later is required.

```bash
python3 --version  # Must be 3.10 or later
```

If Python is missing or outdated, install or update it.

**Container CLI Runtime**:

The agent runs in a container, so you'll need either `docker` or `podman` available on
your system.

**Container CLI**:

`docker` is used by default. To use Podman, set this in your `.env` (see
[Container CLI](#container-cli) below):

```bash
DOCKER_CLI=podman
```

That single setting is all that is required — `run.sh`, `stop.sh`, `pre-check.sh` and the
build scripts all read it. **You do not need to alias `docker` to `podman`.**

In the commands throughout this guide, replace `docker` with `podman` if that is what you
configured.

**Container Image**:

Pull the pre-built container image from the registry:

```bash
# Login to IBM Cloud Container Registry
docker login icr.io -u iamapikey
# When prompted, enter your API key
# Nothing will appear as you type — this is normal security behaviour. Do not paste twice.
docker pull icr.io/terraform-policy-agent-2026/terraform-pac-agent:0.0.32
```

**Required Binaries**:

Download the following **Linux** binaries (used inside the container). The architecture must match your host machine:

- **Terraform CLI**: Currently in beta, https://releases.hashicorp.com/terraform
  - Required architecture: Linux ARM64 (for M1/M2 Mac) or Linux AMD64 (for Intel Mac/Linux)

- **TFPolicy CLI**: Currently in beta, https://releases.hashicorp.com/tfpolicy
  - Required architecture: Linux ARM64 (for M1/M2 Mac) or Linux AMD64 (for Intel Mac/Linux)

**Required MCP Server**:

- **terraform-mcp-server**: HashiCorp's MCP server for Terraform operations
  - Must be running on `localhost:8500`
  - For detailed setup instructions, see: [terraform-mcp-server repository](https://github.com/hashicorp/terraform-mcp-server)
  
  **Recommended Setup:**
  
  Pull and run the MCP server:
  
  ```bash
  # Pull the MCP server image
  docker pull docker.io/hashicorp/terraform-mcp-server:1.1.0
  
  # Run the MCP server
  docker run -d \
    --name terraform-mcp-server \
    -p 8500:8080 \
    -e TRANSPORT_MODE=streamable-http \
    -e TRANSPORT_HOST=0.0.0.0 \
    -e MCP_SESSION_MODE=stateless \
    --restart unless-stopped \
    docker.io/hashicorp/terraform-mcp-server:1.1.0
  ```
  
  **Verify connectivity:**
  
  Using pre-flight check:
  ```bash
  # Check MCP server only
  ./pre-check.sh mcp
  ```
  
  Or using curl from terraform-pac-agent container:
  ```bash
  docker run --rm -it --entrypoint "" \
    icr.io/terraform-policy-agent-2026/terraform-pac-agent:0.0.32 \
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

**Option A: GitHub Copilot (Default)**

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

**Option B: LiteLLM**

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

**Option C: Amazon Bedrock (Bearer Token)**

```bash
AUTH_PROVIDER=amazon-bedrock
MODEL_NAME=anthropic.claude-opus-4-5-20251101-v1:0
MODEL_API_KEY=your-base64-encoded-bearer-token
```

- `AUTH_PROVIDER`: Set to `amazon-bedrock`
- `MODEL_NAME`: Bedrock model ID (e.g., `anthropic.claude-opus-4-5-20251101-v1:0`)
- `MODEL_API_KEY`: Your Bedrock Bearer Token (Base64 encoded API key)

**How to get GitHub Copilot tokens:**

**Recommended: Using a container (no local installation required)**

Run the following command to obtain tokens in an isolated container environment:

```bash
docker run --rm -it --entrypoint "" \
  icr.io/terraform-policy-agent-2026/terraform-pac-agent:0.0.32 \
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

#### Container CLI

```bash
# docker (default) or podman
DOCKER_CLI=docker
```

Priority: this `.env` file > environment variable > default (`docker`).

Podman users only need this one line; no `docker` alias is required.

**Podman on Linux**

Two host-specific flags may be needed. Pass them through with
`DOCKER_RUN_EXTRA_ARGS`, which is appended verbatim to the container run command:

| Host | Value |
|---|---|
| macOS (Podman Desktop / `podman machine`) | leave unset |
| SELinux-enforcing Linux (RHEL / Fedora / CentOS Stream) | `DOCKER_RUN_EXTRA_ARGS="--security-opt label=disable"` |
| Rootless Podman on Linux | `DOCKER_RUN_EXTRA_ARGS=--add-host=host.docker.internal:host-gateway` |
| Both of the above | `DOCKER_RUN_EXTRA_ARGS="--security-opt label=disable --add-host=host.docker.internal:host-gateway"` |

- **Wrap the value in double quotes whenever it contains a space.** Without quotes the shell
  reads only the first word and the rest is silently dropped.
- `--security-opt label=disable` is preferred over adding `,z` to the mounts: `,z` relabels
  the files on the host, which would change the SELinux labels of shared binaries such as
  `/usr/local/bin/terraform`.
- **Do not set `--add-host` on macOS.** The `podman machine` VM already defines
  `host.docker.internal`, and Podman fails with
  `unable to replace "host-gateway" of host entry "host.docker.internal"`.
- On macOS, only paths shared into the `podman machine` VM can be mounted. `/tmp` is not
  shared by default, so keep `DATA_DIR` and the binary paths under your home directory.

#### Complete `.env` Example

```bash
# Authentication (choose one option above)
AUTH_PROVIDER=litellm
MODEL_BASE_URL=https://your-litellm-endpoint.com
MODEL_NAME=aws/claude-sonnet-4-5
MODEL_API_KEY=sk-your-litellm-api-key

# Binaries (required - must match container architecture)
# M1/M2 Mac: use linux-arm64 binaries
# Intel Mac/Linux: use linux-amd64 binaries
TERRAFORM_BINARY_PATH=/path/to/terraform
TFPOLICY_BINARY_PATH=/path/to/tfpolicy

# External Repository Path (Primary use case)
# Set this to convert Sentinel policies from an external repository
EXTERNAL_REPO_DIR=/path/to/your/sentinel-repository

# Data directories (used when EXTERNAL_REPO_DIR is not set)
DATA_DIR=./data
INPUT_DIR=input
INPUT_FILE=policy_goal.txt
OUTPUT_DIR=output

# Execution
MAX_WORKERS=5
IMAGE_NAME=icr.io/terraform-policy-agent-2026/terraform-pac-agent
IMAGE_TAG=0.0.32

# Container CLI: docker (default) or podman
DOCKER_CLI=docker
# Extra flags for the container run command (see "Container CLI" above).
# Quote the value if it contains a space.
# DOCKER_RUN_EXTRA_ARGS="--security-opt label=disable"

# Stage 0: Extraction timeout
STAGE0_TIMEOUT=600  # Optional, defaults to 600 (10 minutes)

# Stage 1: Requirement Generation timeout (per goal)
STAGE1_TIMEOUT=300  # Optional, defaults to 300 (5 minutes)

# Stage 2: Policy Generation timeout (per policy)
STAGE2_TIMEOUT=900  # Optional, defaults to 900 (15 minutes)

# Stage 3: Summary Generation timeout
STAGE3_TIMEOUT_BASE=180  # Optional, defaults to 180 (3 minutes base)
STAGE3_TIMEOUT_PER_POLICY=60  # Optional, defaults to 60 (1 minute per policy)
```

## Usage

### Pre-flight Check (Recommended)

Before running the pipeline, verify all prerequisites are met:

```bash
# Check all prerequisites
./pre-check.sh

# Or check specific components
# ("docker" here is the name of the container-engine check, not the CLI:
#  keep it as "docker" even when DOCKER_CLI=podman)
./pre-check.sh workdir   # Working directory path only
./pre-check.sh docker    # Container engine only
./pre-check.sh env       # Environment variables only
./pre-check.sh binaries  # terraform/tfpolicy binaries only
./pre-check.sh input     # Input file only
./pre-check.sh image     # Container image only
./pre-check.sh mcp       # MCP server only
./pre-check.sh output    # Output directory only
./pre-check.sh local     # Local mode config only
./pre-check.sh external  # External mode config only
./pre-check.sh api       # API credentials only

# JSON output for automation
./pre-check.sh --json
./pre-check.sh mcp --json
```

Note: `pre-check.sh` automatically detects and uses the available Python interpreter (`python3` or `python`).

The pre-flight check will verify:
- 🟢 **docker**: The container engine set by `DOCKER_CLI` is running
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available and executable
- 🟢 **input**: Input files exist
- 🟢 **image**: Container image is available
- 🟢 **mcp**: MCP server is accessible at localhost:8500
- 🟢 **output**: Output directory is empty (ready for pipeline)
- 🟢 **local**: Local mode — `EXTERNAL_REPO_DIR` is not set, `INPUT_DIR`/`INPUT_FILE`/`OUTPUT_DIR` are present
- 🟢 **external**: External mode — `EXTERNAL_REPO_DIR` is set and the directory exists
- 🟢 **workdir**: Working directory path has no unsafe characters
- 🟢 **api**: API credentials are valid (tested via lightweight ping)

If any issues are found, the tool will provide clear error messages with 🔴 status and suggestions for fixing them.

**Mode-based check behaviour** — When running `./pre-check.sh` (all checks), the fully ready state looks different depending on your mode. `local` and `external` are mutually exclusive: one will always show 🔴, which is **expected and should be ignored**:

| Check    | Local mode           | External mode        |
|----------|----------------------|----------------------|
| docker   | ✅ pass              | ✅ pass              |
| env      | ✅ pass              | ✅ pass              |
| binaries | ✅ pass              | ✅ pass              |
| input    | ✅ pass              | ✅ pass (or ⚠️ warn) |
| image    | ✅ pass              | ✅ pass              |
| mcp      | ✅ pass              | ✅ pass              |
| output   | ✅ pass              | ✅ pass              |
| local    | ✅ pass              | 🔴 expected — ignore |
| external | 🔴 expected — ignore | ✅ pass              |
| workdir  | ✅ pass              | ✅ pass              |
| api      | ✅ pass              | ✅ pass              |

> **Local mode** (`EXTERNAL_REPO_DIR` not set): `external` shows 🔴 — this is expected, ignore it.

> **External mode** (`EXTERNAL_REPO_DIR` set): `local` shows 🔴 — this is expected, ignore it.

### Primary Use Case: External Repository Integration

To convert Sentinel libraries from an external repository (e.g., HashiCorp's CIS Policy Set for AWS Terraform):

Example repository: https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform/tree/main/policies/cloudtrail

**Step 1: Download or clone the external repository**

```bash
# Option A: Download and extract
curl -L https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform/archive/refs/heads/main.zip -o repo.zip
unzip repo.zip -d /tmp

# Option B: Clone the repository
git clone https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform.git /tmp/sentinel-repo
```

**Step 2: Set the external repository path in `.env`**

```bash
EXTERNAL_REPO_DIR=/tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main/policies/cloudtrail
```

**Step 3: Run the pipeline**

```bash
./run.sh  # Auto-detects external mode when EXTERNAL_REPO_DIR is set
```

Or explicitly specify external mode:
```bash
./run.sh external  # Force external mode
```

The script automatically:
- Detects `EXTERNAL_REPO_DIR` is set and runs in external mode
- Extracts Sentinel files from the repository
- Creates timestamped directories (`data/input-YYYYMMDD_HHMMSS/`, `data/output-YYYYMMDD_HHMMSS/`)
- Generates policies
- Deploys results to `EXTERNAL_REPO_DIR/tfpolicy/`

Example output structure:

```
/tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main/policies/cloudtrail/tfpolicy
├── cloudtrail-bucket-access-logging-enabled/
│   ├── cloudtrail-bucket-access-logging-enabled.policy.hcl
│   ├── cloudtrail-bucket-access-logging-enabled.policytest.hcl
│   ├── cloudtrail-bucket-access-logging-enabled.report.md
│   └── cloudtrail-bucket-access-logging-enabled.tf
└── ...
```

### Alternative: Local Mode (Manual Preparation)

If you don't have an external repository or want to manually prepare input files:

**Step 1: Prepare Data Directory**

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

**Step 2: Create Input File**

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

**Step 3: Ensure EXTERNAL_REPO_DIR is NOT set in `.env`**

Comment out or remove the `EXTERNAL_REPO_DIR` line in your `.env` file:

```bash
# EXTERNAL_REPO_DIR=/path/to/your/sentinel-repository
```

**Step 4: Run the pipeline**

```bash
./run.sh  # Auto-detects local mode when EXTERNAL_REPO_DIR is not set
```

Or explicitly specify local mode:
```bash
./run.sh local  # Force local mode (ignores EXTERNAL_REPO_DIR even if set)
```

The script will automatically detect that `EXTERNAL_REPO_DIR` is not set and run in local mode.

**Output:**

Output files are generated in the directory specified by `OUTPUT_DIR` in your `.env` file (default: `data/output`):

```sh
$ ls ./data/output
CloudFront_Associated_WAF   goals                   summary.json
stage0_extraction.log       stage3_summary.log      summary.md
```

**Important:** The `OUTPUT_DIR` must be empty before running the full pipeline to prevent accidental overwrites. If you need to run multiple conversions, set a different `OUTPUT_DIR` in `.env` for each run (e.g., `OUTPUT_DIR=output-v2`, `OUTPUT_DIR=results-20260603`).

## Pipeline Stages

The pipeline runs 4 stages automatically. Each stage must complete before the next begins.

| Stage | What it does | Output |
|---|---|---|
| **Stage 0** | Authenticates with the LLM provider and extracts policy goals from `policy_goal.txt` | `data/output/goals/` |
| **Stage 1** | Generates detailed requirements for each policy goal (runs in parallel) | `data/output/PolicyName/requirement.txt` |
| **Stage 2** | Generates policy files and tests for each requirement (runs in parallel) | `data/output/PolicyName/*.hcl`, `*.tf` |
| **Stage 3** | Creates a consolidated summary report | `data/output/summary.md` |

> **If the pipeline fails at Stage 0**, the most likely cause is an invalid or expired API key / token. First, run `./pre-check.sh api` to confirm whether your credentials are valid. If the check fails, re-acquire your tokens and update `.env`. See [Troubleshooting](./TROUBLESHOOTING.md) for fixes.

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
   - Verify container image availability
   - Check required binaries (terraform, tfpolicy)
   - Validate MCP server connection
3. **Pipeline run**
   - Show how to execute the conversion pipeline with `./run.sh`


## Advanced Usage

### Run Specific Steps (Local Mode)

```bash
./run.sh local --step 0
./run.sh local --step 1 --goal-file goal-001.txt
./run.sh local --step 2 --policy-dir CloudFront_Associated_WAF
./run.sh local --step 3
```

### Run Specific Phases (External Mode)

```bash
./run.sh external --phase preprocess    # Extract only
./run.sh external --phase generate      # Generate only
./run.sh external --phase postprocess   # Deploy only
```

### Resume from Checkpoint

Interrupted runs save progress to `.checkpoint` in `DATA_DIR`. Use `--resume` to pick up from the last completed stage without re-running earlier steps:

```bash
./run.sh --resume local      # local mode
./run.sh --resume external   # external mode
```

### Skip Confirmation Prompts (No-Confirm Mode)

Pass `--no-confirm` to suppress all interactive yes/no prompts and let the pipeline run unattended:

```bash
./run.sh --no-confirm local
./run.sh --no-confirm external
```

Both flags can be combined:

```bash
./run.sh --no-confirm --resume local
./run.sh --no-confirm --resume external
```

### Help

```bash
./run.sh --help
./run.sh local --help
./run.sh external --help
```

### Pipeline Fails
- Check `data/input/policy_goal.txt` exists and is properly formatted
- Verify binary paths in `.env` are correct
- Check logs in `data/output/stage*.log`