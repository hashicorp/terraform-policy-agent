---
name: tfpac-setup
description: Guide users through an interactive wizard to create a `.env` file for the Terraform Policy Agent project by asking questions and generating a properly formatted `.env` file based on user responses. Supports multiple workflows including policy generation from existing database, policy generation with crawler, and Sentinel policy conversion (local or external repository).
---

# Skill: Interactive Environment Setup Wizard


## Prerequisites
- Access to the project root directory (`terraform-policy-agent`)
- Ability to read `.env.example` file (if exists)
- Ability to write `.env` file to project root
- Access to `skills/tfpac-setup/dotenv_tool.py` for secure .env file handling

## Workflow Overview

This wizard supports multiple workflows for the Terraform Policy Agent:

1. **Generate TF Policies from Existing Database (generation)**
   - Use existing policy database (POLICY_DB)
   - Generate TF policies based on specifications already in the database
   - No crawler execution needed

2. **Generate TF Policies with Crawler (generation_with_crawler)**
   - Extract policy specifications from URLs, PDFs, or other documents using crawler
   - Create or update policy database
   - Generate TF policies from newly extracted specifications
   - Requires crawler configuration

3. **Convert from Sentinel (conversion)**
   - Convert existing Sentinel policies to TF policies
   - Can use Manual Setup (local mode) or External Repository as the sentinel source
   - Specific mode will be configured in Step 3

## Security Note: Handling Existing .env Files

**CRITICAL:** Never directly read or load existing `.env` files using standard file reading tools, as they may contain sensitive secrets (API keys, tokens) that should not be exposed to the LLM.

**Always use the dotenv_tool.py script to load existing .env files:**
```bash
python3 skills/tfpac-setup/dotenv_tool.py .env
```

This script automatically masks sensitive values (API keys, tokens) before displaying them, preventing secrets from being exposed to the LLM. The tool identifies and masks the following secret variables:
- `MODEL_API_KEY`
- `GITHUB_COPILOT_ACCESS_TOKEN`
- `GITHUB_COPILOT_REFRESH_TOKEN`

When loading an existing .env file, use the dotenv_tool.py to safely retrieve non-secret configuration values.

## Workflow

### 1. Introduction and Workflow Selection

Start by:
- Greeting the user and explaining the wizard's purpose
**Ask the user: "Which workflow do you want to use?"**
**Options:**
1. **Generate TF Policies from Existing Database (generation)**
   - Use existing policy database (POLICY_DB)
   - Generate TF policies based on specifications already in the database
   - No crawler execution needed

2. **Generate TF Policies with Crawler (generation_with_crawler)**
   - Extract policy specifications from URLs, PDFs, or other documents using crawler
   - Create policy database
   - Generate TF policies from newly extracted specifications
   - Requires crawler configuration

3. **Convert from Sentinel (conversion)**
   - Convert existing Sentinel policies to TF policies
   - Can use Manual Setup (local mode) or External Repository as sentinel source

Store the user's choice as `userSelectedMode` with one of: `generation`, `generation_with_crawler`, or `conversion`.

### 2. Pre-flight System Check

**Before configuring the environment, verify system readiness:**

**Step 2a: Check Docker availability**
Run a simple Docker command to verify Docker is available:
```bash
docker --version
```

**If Docker is not available:**
- Show error: "Docker is not available. Please install Docker and ensure it's running."
- Ask user to install/start Docker before proceeding

**Step 2b: Docker Image Configuration and Setup**

**Ask: "Do you want to use the latest recommended Docker image version?"**
- Recommended image: `icr.io/polaris-20251120/terraform-pac-agent:0.0.27.full.0.0.1`
- Default: Yes

If **Yes** (use recommended version):
- Set `IMAGE_NAME`: "icr.io/polaris-20251120/terraform-pac-agent"
- Set `IMAGE_TAG`: "0.0.27.full.0.0.1"

If **No** (custom version):
- Ask for `IMAGE_NAME` (default: "icr.io/polaris-20251120/terraform-pac-agent")
- Ask for `IMAGE_TAG` (default: "0.0.27.full.0.0.1")

**Check if image exists locally:**
```bash
docker images --format "{{.Repository}}:{{.Tag}}" | grep "[IMAGE_NAME]:[IMAGE_TAG]" || echo "Image not found locally"
```

**Important:** If the output shows "Image not found locally", the image does not exist. Do not proceed until the image is pulled.

**If image does not exist locally:**
- Show message: "📦 Docker image not found locally. You need to pull it first."
- **Important:** Image pull requires authentication. Show ONLY the following instructions (do not provide alternative methods):
  ```
  🔐 Authentication Required
  
  Before pulling the image, please login to IBM Cloud Container Registry in your terminal:
  
  docker login icr.io -u iamapikey
  
  When prompted, enter your IBM Cloud API key.
  (If you don't have an API key, please contact your HashiCorp representative to obtain access.)
  
  After successful login, please confirm and I will pull the image for you.
  ```

- **IMPORTANT:** Do NOT suggest creating API keys or provide alternative authentication methods. Users must obtain API keys from their HashiCorp representative.
- **Wait for user confirmation** that they have logged in successfully
- After confirmation, pull the image:
```bash
docker pull [IMAGE_NAME]:[IMAGE_TAG]
```

**If image pull fails:**
- Show error details
- Likely cause: Authentication not completed or expired
- Ask user to verify login and try again
- **STOP HERE** - Do not proceed to Step 2c until the image is successfully pulled

**If image pull succeeds:**
- Show success: "✅ Docker image pulled successfully"
- **Update .env file immediately** with the image configuration:
  - If `.env` exists, use `dotenv_tool.py` to check current values
  - If `IMAGE_NAME` or `IMAGE_TAG` are missing or different, update them:
    ```bash
    # Use apply_diff or write_to_file to update .env
    IMAGE_NAME=[IMAGE_NAME]
    IMAGE_TAG=[IMAGE_TAG]
    ```
  - Show confirmation: "✅ Updated .env with image configuration"
- Proceed to Step 2c

**If image already exists:**
- Show message: "✅ Docker image already available locally"
- **Check and update .env file if needed**:
  - If `.env` exists, use `dotenv_tool.py` to check current values
  - If `IMAGE_NAME` or `IMAGE_TAG` are missing or different from the selected version, update them
  - Show confirmation if updated: "✅ Updated .env with image configuration"
- Proceed to Step 2c

**Note:** Image name and tag are stored immediately to ensure consistency. They will be included in the final `.env` file generation in Step 10.

**Step 2c: Check MCP server (Only after image is confirmed available and .env is updated)**

**Prerequisites for this step:**
- Docker image must be pulled and available locally
- `.env` file must contain `IMAGE_NAME` and `IMAGE_TAG` (set in Step 2b)

**Run MCP check:**
```bash
./pre-check.sh mcp
```

This check uses the Docker image specified in `.env` to verify MCP server connectivity.

- 🟢 **mcp**: MCP server is accessible at localhost:8500 via container

**If MCP check fails (🔴):**
- Show error and provide guidance on starting MCP server
- Note: "MCP server must be running on localhost:8500 before proceeding"
- Common issues:
  - MCP server not started
  - Port 8500 not accessible
  - Docker image cannot reach host.docker.internal

**If all checks pass (🟢):**
- Proceed to workflow selection

**Note:** Binary paths and input file checks will be performed later after configuration is complete.

### 3. Input Setup

**Branch based on `userSelectedMode`:**

- If `userSelectedMode` is `generation`: Skip to Step 3a
- If `userSelectedMode` is `generation_with_crawler`: Skip to Step 3b
- If `userSelectedMode` is `conversion`: Continue below

**For `conversion` workflow only:**

**Ask: "Which execution mode do you want to configure for `run.sh`?"**

**Options:**
1. **External Repository Mode (`run.sh external`)** - Recommended for existing Sentinel repositories
   - Automatically extracts Sentinel policies from your external repository
   - Converts them to TF policies
   - Deploys results back to the repository
   - Simple setup: specify `EXTERNAL_REPO_DIR`
   
2. **Local Mode (`run.sh local`)** - For custom policy conversion
   - You manually create data directory structure
   - You provide Sentinel policy files in `data/input/sentinels/`
   - You create `policy_goal.txt` with file paths to convert
   - More control over which files to convert

**Important:** `run.sh` is the single entry point. In practice, if `EXTERNAL_REPO_DIR` is set, the script may automatically use external mode; if it is not set, it uses local mode.

**Note:** If user selects option 1 (External Repository Mode), continue to step 3d. If option 2 (Local Mode), continue to step 3c.

### 3a. Input Setup for `generation` workflow

**Ask: "What is the path to your policy specifications database?"**
- Parameter: `POLICY_DB`
- Default: "database/policy_spec_db.jsonl"
- Validation: File must exist
- Note: "This file contains policy specifications"

**Ask: "Have you already created a `data/input/policy_goal.txt` file with the policies you want to generate?"**
- Default: No
- Note: "The policy_goal.txt file should list the specific policies you want to generate from the database"
Provide examples:
```
1. Using Control IDs:
   Generate TF Policy for
   DocumentDB.4, DMS.12, DMS.11, DMS.6, CloudFront.12, CloudFront.13,
   CloudFront.6, Autoscaling.5, Backup.1, PCA.1

2. Using natural language descriptions:
   Generate TF Policy for
   - verify whether groups associated with a load balancer are using health checks
   - ensure S3 buckets have versioning enabled
   - check if RDS instances have encryption at rest enabled
```

If **Yes**:
- Skip to Step 4 (Binary Paths Configuration)

If **No**:
- **Ask: "Would you like me to help create the policy_goal.txt file?"**
  - Default: Yes
  
  If **Yes**:
    - Ask user to describe the policies they want to generate
    - Create `data/input/policy_goal.txt` with the user's input
    - Show confirmation: "✅ Created policy_goal.txt at: [path]"
  
  If **No**:
    - Show instructions:
      ```
      📋 Manual Setup Instructions:
      1. Create file: `data/input/policy_goal.txt`
      2. List the policies you want to generate, for examples:
      Generate TF Policy for
      [Control IDs] or [natural language descriptions]
      ```


### 3b. Input Setup for `generation_with_crawler` workflow

**Ask: "What policy specifications do you want to generate?"**

Provide guidance:
```
📋 Specify your policy generation sources in crawler/crawler_goal.txt

Examples:
1. URL to compliance documentation:
   https://docs.aws.amazon.com/securityhub/latest/userguide/autoscaling-controls.html#autoscaling-1

2. Local file path:
   crawler/data/policy.pdf

3. Natural language description:
   Generate specifications for AWS Security Hub controls...
```

**Ask: "Would you like me to help create the crawler_goal.txt file?"**

If **Yes**:
- Ask: "Please provide the policy generation source (URL, file path, or description):"
- Create `crawler/crawler_goal.txt` with the provided content
- Show confirmation: "✅ Created crawler/crawler_goal.txt"

If **No**:
- Show instructions:
  ```
  📋 Manual Setup:
  Create crawler/crawler_goal.txt with your policy generation sources
  ```

**Ask: "Have you already created a `data/input/policy_goal.txt` file with the policies you want to generate?"**
- Default: No
- Note: "The policy_goal.txt file should list the specific policies you want to generate from the database"
Provide examples:
```
1. Using Control IDs:
   Generate TF Policy for
   DocumentDB.4, DMS.12, DMS.11, DMS.6, CloudFront.12, CloudFront.13,
   CloudFront.6, Autoscaling.5, Backup.1, PCA.1

2. Using natural language descriptions:
   Generate TF Policy for
   - verify whether groups associated with a load balancer are using health checks
   - ensure S3 buckets have versioning enabled
   - check if RDS instances have encryption at rest enabled
```

If **Yes**:
- Skip to Step 4 (Binary Paths Configuration)

If **No**:
- **Ask: "Would you like me to help create the policy_goal.txt file?"**
  - Default: Yes
  
  If **Yes**:
    - Ask user to describe the policies they want to generate
    - Create `data/input/policy_goal.txt` with the user's input
    - Show confirmation: "✅ Created policy_goal.txt at: [path]"
  
  If **No**:
    - Show instructions:
      ```
      📋 Manual Setup Instructions:
      1. Create file: `data/input/policy_goal.txt`
      2. List the policies you want to generate, for examples:
      Generate TF Policy for
      [Control IDs] or [natural language descriptions]
      ```

### 3c. Local Mode - Data Directory Assistance (Only for `conversion` with local mode)

**Update `userSelectedMode` to `conversion_local`.**

**Ask: "Do you have Sentinel policy files ready to convert?"**

If **Yes**, ask:
- "Where are your Sentinel policy files located?"
- "Would you like me to help set up the data directory structure and copy the files?"

If user wants help:
1. Create `data/input/sentinels/` directory
2. Copy Sentinel files from the specified location
3. Generate `policy_goal.txt` with the list of copied files
4. Show confirmation: "✅ Data directory setup complete. Files copied to data/input/sentinels/"

If **No** or user declines help:
- Show instructions:
  ```
  📋 Manual Setup Instructions:
  1. Create directory: data/input/sentinels/
  2. Copy your Sentinel policy files (.sentinel) to data/input/sentinels/
  3. Create data/input/policy_goal.txt with content:
     Convert following Sentinel Policies to TF Policies:
     - ./data/input/sentinels/your-policy-1.sentinel
     - ./data/input/sentinels/your-policy-2.sentinel
  ```

### 3d. External Repository Setup (Only for `conversion` with external mode)

**Update `userSelectedMode` to `conversion_external`.**

**Ask: "What is the path to your external Sentinel repository?"**
- Parameter: `EXTERNAL_REPO_DIR`
- Default: "./workdir/workspaces/external_repo"
- Validation: Directory must exist
- Note: "This directory should contain your Sentinel policy files (.sentinel)"

**Ask: "Do you have a sentinel.hcl file to configure?"**
- If **Yes**: Ask for `SENTINEL_HCL_PATH` (default: "./external_repo/sentinel.hcl")
- If **No**: Skip this configuration

**Note:** The script will automatically:
- Extract all .sentinel files from EXTERNAL_REPO_DIR
- Skip files that already have tfpolicy/ conversions
- Generate policy_goal.txt automatically
- Deploy results back to the repository

### 4. Binary Paths Configuration

**Step 4a: Detect image OS and architecture**

Run the following command using `IMAGE_NAME` and `IMAGE_TAG` set in Step 2b:
```bash
docker image inspect [IMAGE_NAME]:[IMAGE_TAG] --format "{{.Architecture}}|{{.Os}}"
```
Store the results as `IMAGE_ARCH` (e.g. `arm64`, `amd64`) and `IMAGE_OS` (e.g. `linux`, `darwin`).

**Step 4b: Look up defaults and download URLs from the table below**

The binaries are mounted into and executed **inside** the Docker container, so they must match the **image's** OS and architecture — not the host machine.

| Image OS | Image Arch | Terraform download URL | TFPolicy download URL | TERRAFORM_BINARY_PATH default | TFPOLICY_BINARY_PATH default |
|----------|------------|------------------------|-----------------------|-------------------------------|------------------------------|
| linux | arm64 | `https://releases.hashicorp.com/terraform/1.16.0-alpha20260715/terraform_1.16.0-alpha20260715_linux_arm64.zip` | `https://releases.hashicorp.com/tfpolicy/0.1.0/tfpolicy_0.1.0_linux_arm64.zip` | `/usr/local/bin/terraform` | `/usr/local/bin/tfpolicy` |
| linux | amd64 | `https://releases.hashicorp.com/terraform/1.16.0-alpha20260715/terraform_1.16.0-alpha20260715_linux_amd64.zip` | `https://releases.hashicorp.com/tfpolicy/0.1.0/tfpolicy_0.1.0_linux_amd64.zip` | `/usr/local/bin/terraform` | `/usr/local/bin/tfpolicy` |
| darwin | arm64 | `https://releases.hashicorp.com/terraform/1.16.0-alpha20260715/terraform_1.16.0-alpha20260715_darwin_arm64.zip` | `https://releases.hashicorp.com/tfpolicy/0.1.0/tfpolicy_0.1.0_darwin_arm64.zip` | `/opt/homebrew/bin/terraform` | `/usr/local/bin/tfpolicy` |
| darwin | amd64 | `https://releases.hashicorp.com/terraform/1.16.0-alpha20260715/terraform_1.16.0-alpha20260715_darwin_amd64.zip` | `https://releases.hashicorp.com/tfpolicy/0.1.0/tfpolicy_0.1.0_darwin_amd64.zip` | `/usr/local/bin/terraform` | `/usr/local/bin/tfpolicy` |

**If `IMAGE_OS`/`IMAGE_ARCH` matches one of the four rows above:**

Resolve the following **temporary variables**:
- `_TF_URL` — Terraform download URL
- `_TFP_URL` — TFPolicy download URL
- `_TF_DEFAULT` — TERRAFORM_BINARY_PATH default
- `_TFP_DEFAULT` — TFPOLICY_BINARY_PATH default

Proceed to **Step 4c: Configure Terraform binary**.

---

**If `IMAGE_OS`/`IMAGE_ARCH` does NOT match any row (unknown combination) → Proceed this fallback**

**Fallback 4-1: Configure Terraform binary**

Ask: "Do you already have the Terraform binary? [Y/n]"

**If YES:**
- Ask: "What is the path to your Terraform binary?"
  - Store as `TERRAFORM_BINARY_PATH`.

**If NO:**
- Inform the user:
  ```
  ⚠️ Your image OS/arch combination is not in the known list.
  Please download the correct binaries manually from the following pages
  and select the package that matches your container (IMAGE_OS/IMAGE_ARCH):

  Terraform : https://releases.hashicorp.com/terraform/1.16.0-alpha20260715/
  ```
- Ask: "Where did you download the Terraform binary?"
  - Store as `TERRAFORM_BINARY_PATH`.

**Fallback 4-2: Configure tfpolicy binary**

Ask: "Do you already have the tfpolicy binary? [Y/n]"

**If YES:**
- Ask: "What is the path to your tfpolicy binary?"
  - Store as `TFPOLICY_BINARY_PATH`.
- Proceed to **### 4. Authentication Provider Configuration**.

**If NO:**
- Inform the user:
  ```
  ⚠️ Your image OS/arch combination is not in the known list.
  Please download the correct binaries manually from the following pages
  and select the package that matches your container (IMAGE_OS/IMAGE_ARCH):

  TFPolicy  : https://releases.hashicorp.com/tfpolicy/0.1.0/
  ```
- Ask: "Where did you download the tfpolicy binary?"
  - Store as `TFPOLICY_BINARY_PATH`.
- Proceed to **### 4. Authentication Provider Configuration**.

---

**Step 4c: Configure Terraform binary**

Ask: "Do you already have the Terraform binary? [Y/n]"

**If YES:**
- Ask: "What is the path to your Terraform binary? [default: `_TF_DEFAULT`]"
- Store the answer as `TERRAFORM_BINARY_PATH`.

**If NO:**
- Ask: "Where would you like to place the Terraform binary? [default: `_TF_DEFAULT`]"
- Store the answer as `TERRAFORM_BINARY_PATH`.
- Download, extract, and place:
  ```bash
  # Download
  wget -O /tmp/terraform-pac.zip "_TF_URL"

  # Extract
  unzip -o /tmp/terraform-pac.zip -d /tmp/terraform-pac-tf/

  # Place
  cp /tmp/terraform-pac-tf/terraform [TERRAFORM_BINARY_PATH]
  chmod +x [TERRAFORM_BINARY_PATH]

  # Clean up
  rm -rf /tmp/terraform-pac.zip /tmp/terraform-pac-tf/
  ```
  - Show success: "✅ Terraform binary placed at `TERRAFORM_BINARY_PATH`."
  - If it fails, show the error and ask the user to obtain the binary manually from their HashiCorp representative.

---

**Step 4d: Configure tfpolicy binary**

Ask: "Do you already have the tfpolicy binary? [Y/n]"

**If YES:**
- Ask: "What is the path to your tfpolicy binary? [default: `_TFP_DEFAULT`]"
- Store the answer as `TFPOLICY_BINARY_PATH`.

**If NO:**
- Ask: "Where would you like to place the tfpolicy binary? [default: `_TFP_DEFAULT`]"
- Store the answer as `TFPOLICY_BINARY_PATH`.
- Download, extract, and place:
  ```bash
  # Download
  wget -O /tmp/tfpolicy-pac.zip "_TFP_URL"

  # Extract
  unzip -o /tmp/tfpolicy-pac.zip -d /tmp/terraform-pac-tfp/

  # Place
  cp /tmp/terraform-pac-tfp/tfpolicy [TFPOLICY_BINARY_PATH]
  chmod +x [TFPOLICY_BINARY_PATH]

  # Clean up
  rm -rf /tmp/tfpolicy-pac.zip /tmp/terraform-pac-tfp/
  ```
  - Show success: "✅ tfpolicy binary placed at `TFPOLICY_BINARY_PATH`."
  - If it fails, show the error and ask the user to obtain the binary manually from their HashiCorp representative.

### 5. Authentication Provider Configuration
Ask: "Which authentication provider do you want to use?"

**Options:**
1. **LiteLLM (Default)**
   - Set `AUTH_PROVIDER=litellm`
   - Ask for:
     - `MODEL_BASE_URL` (default: "https://your-litellm-endpoint.com")
     - `MODEL_NAME` (default: "aws/claude-sonnet-4-5")
     - `MODEL_API_KEY` - **IMPORTANT:** Tell user to manually fill this in the .env file after generation. Never ask for or store secret values directly.

2. **Amazon Bedrock (Bearer Token)**
   - Set `AUTH_PROVIDER=amazon-bedrock`
   - Ask for:
     - `MODEL_NAME` (default: "anthropic.claude-opus-4-5-20251101-v1:0")
     - `MODEL_API_KEY` - **IMPORTANT:** Tell user to manually fill this in the .env file after generation. Never ask for or store secret values directly.

3. **GitHub Copilot CLI**
   - Set `AUTH_PROVIDER=github-copilot`
   - Ask for:
     - `MODEL_NAME` (default: "claude-sonnet-4.6")
   
   **Then show GitHub Copilot CLI token acquisition guide:**
   
   ```
   🔐 How to Obtain GitHub Copilot Tokens
   
   To run this project, you need GitHub Copilot authentication tokens.
   
   ### Recommended Method: Safe Token Acquisition Using Docker Container ✨
   
   No need to install anything on your host machine - everything is self-contained in the project's container.
   
   **Step 1: Run the following command**
   ```bash
   docker run --rm -it --entrypoint "" \
     icr.io/polaris-20251120/terraform-pac-agent:0.0.27.full.0.0.1 \
     sh -c 'opencode auth login && cat $HOME/.local/share/opencode/auth.json'
   ```
   
   **Step 2: Follow the on-screen instructions**
   - A URL and code will be displayed (e.g., `https://github.com/login/device` and `XXXX-XXXX`)
   - Open the URL in your browser and enter the code
   - Authorize GitHub Copilot access
   
   **Step 3: Copy the tokens**
   After authentication completes, tokens will be displayed in JSON format:
   ```json
   {
     "access_token": "ghu_xxxxxxxxxxxx",
     "refresh_token": "ghu_xxxxxxxxxxxx",
     "expires": 1234567890
   }
   ```
   
   **Step 4: Paste into .env file**
   Later, you'll paste these values into the generated `.env` file:
   ```
   GITHUB_COPILOT_ACCESS_TOKEN=ghu_xxxxxxxxxxxx
   GITHUB_COPILOT_REFRESH_TOKEN=ghu_xxxxxxxxxxxx
   GITHUB_COPILOT_EXPIRES=1234567890
   ```
   
   ---
   
   ### Alternative Method: Using OpenCode on Host Machine
   
   If you already have OpenCode installed:
   ```bash
   opencode auth login
   cat ~/.local/share/opencode/auth.json
   ```
   
   ---
   
   **💡 Why Use the Docker Container?**
   - No need to install additional software on your host machine
   - Completely isolated from your project environment
   - Used only for obtaining credentials, then immediately removed (`--rm` flag)
   - Authenticates in the same environment as the container used by this project
   ```
   
   - `GITHUB_COPILOT_ACCESS_TOKEN` - Tell user to manually fill this in the .env file after generation
   - Optional: `GITHUB_COPILOT_REFRESH_TOKEN` - Tell user to manually fill this in the .env file
   - Optional: `GITHUB_COPILOT_EXPIRES` - Tell user to manually fill this in the .env file (default: "0")

4. **Skip (configure manually later)**
   - Don't set authentication variables

### 6. Pipeline Configuration (Optional)
Ask: "Do you want to customize pipeline settings?" (default: No, note: "Default values work for most cases. You can change output directory or other settings if needed.")

If yes, ask for:
- **DATA_DIR** (default: "./data", note: "Relative paths are resolved from current working directory")
- **INPUT_DIR** (default: "input", note: "Within DATA_DIR (e.g., data/input/)")
- **OUTPUT_DIR** (default: "output", note: "Within DATA_DIR (e.g., data/output/)")
- **INPUT_FILE** (default: "policy_goal.txt", note: "Relative to DATA_DIR/INPUT_DIR/")
- **MAX_WORKERS** (default: "5", validation: Must be a positive integer)

### 7. Docker Configuration (Optional)
Ask: "Do you want to customize additional Docker settings?" (default: No, note: "Image name and tag were already configured in step 2b")

If yes, ask for:
- **IMAGE_NAME** (default: value from step 2b, note: "Already configured")
- **IMAGE_TAG** (default: value from step 2b, note: "Already configured")
- **CONTAINER_PREFIX** (default: "terraform-pac-agent-skills", note: "Useful for multi-environment or multi-user setups")

**If `userSelectedMode` is `generation_with_crawler`, also ask for:**
- **CRAWLER_CONTAINER_PREFIX** (default: "crawler-agent", note: "Prefix for crawler containers")

### 8. Timeout Configuration (Optional)
Ask: "Do you want to customize timeout settings?" (default: No, note: "Default values are usually sufficient")

If yes, ask for (all in seconds, must be positive integers):
- **STAGE0_TIMEOUT** (default: "600") - Policy Extraction timeout
- **STAGE1_TIMEOUT** (default: "300") - Requirement Generation timeout per goal
- **STAGE2_TIMEOUT** (default: "600") - Policy Generation timeout per policy (note: "For complex policies, consider 900+ seconds")
- **STAGE3_TIMEOUT_BASE** (default: "180") - Summary base timeout
- **STAGE3_TIMEOUT_PER_POLICY** (default: "60") - Summary additional timeout per policy

**If `userSelectedMode` is `generation_with_crawler`, also ask for:**
- **CRAWLER_TIMEOUT** (default: "3600") - Crawler execution timeout (note: "60 minutes default, adjust based on the number of documents to crawl")

### 9. Review Configuration Summary

Show a summary of all configured values based on the selected workflow:

**For `generation` workflow:**
- Workflow: Generate TF Policies from Existing Database
- Policy Database: [POLICY_DB value]
- Input File: [policy_goal.txt path]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [DATA_DIR, INPUT_DIR, OUTPUT_DIR, etc.]

**For `generation_with_crawler` workflow:**
- Workflow: Generate TF Policies with Crawler
- Input File: [policy_goal.txt path]
- Crawler Configuration: [crawler settings if configured]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [DATA_DIR, INPUT_DIR, OUTPUT_DIR, etc.]

**For `conversion_external` workflow:**
- Workflow: Convert from Sentinel - External Repository Mode
- External Repository: [EXTERNAL_REPO_DIR value]
- Sentinel HCL: [SENTINEL_HCL_PATH value or "Not configured"]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [DATA_DIR, INPUT_DIR, OUTPUT_DIR, etc.]

**For `conversion_local` workflow:**
- Workflow: Convert from Sentinel - Local Mode
- Data Directory: [DATA_DIR value]
- Input Directory: [INPUT_DIR value]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [OUTPUT_DIR, INPUT_FILE, etc.]

Ask: "Does this configuration look correct?" (default: Yes)
- If No: Allow user to go back and modify settings
- If Yes: Proceed to generate .env file

### 10. Generate and Preview .env File

**Generate .env file content based on selected workflow.**

**For `generation` workflow:**
- Include: POLICY_DB
- Include all standard configuration
- Do NOT include: EXTERNAL_REPO_DIR, SENTINEL_HCL_PATH, or crawler-specific settings

**For `generation_with_crawler` workflow:**
- Include: CRAWLER_CONTAINER_PREFIX (if configured)
- Include: CRAWLER_TIMEOUT (if configured)
- Include: POLICY_DB — force set to `database/policy_spec_db.jsonl` (this is where the crawler creates the database)
- Include all standard configuration
- Do NOT include: EXTERNAL_REPO_DIR or SENTINEL_HCL_PATH

**For `conversion_external` workflow:**
- MUST include: EXTERNAL_REPO_DIR
- MUST include: SENTINEL_HCL_PATH (if configured)
- Include all standard configuration
- Do NOT include: crawler-specific settings

**For `conversion_local` workflow:**
- Do NOT include: EXTERNAL_REPO_DIR, SENTINEL_HCL_PATH, or crawler-specific settings
- Include all standard configuration

Generate the `.env` file content with this structure:

```
# ============================================================================
# Generated by AI Agent Environment Setup Wizard
# ============================================================================

# ============================================================================
# Binary Paths (Required for Docker Runtime)
# ============================================================================
TERRAFORM_BINARY_PATH=<value>
TFPOLICY_BINARY_PATH=<value>

# ============================================================================
# Execution Mode: OpenCode
# ============================================================================
AUTH_PROVIDER=<value>
MODEL_BASE_URL=<value>
MODEL_NAME=<value>
MODEL_API_KEY=<PLEASE_FILL_IN_MANUALLY>  # ⚠️ Fill in your API key manually

# For Amazon Bedrock:
# AUTH_PROVIDER=amazon-bedrock
# MODEL_NAME=anthropic.claude-opus-4-5-20251101-v1:0
# MODEL_API_KEY=<PLEASE_FILL_IN_MANUALLY>  # ⚠️ Fill in your base64-encoded Bearer Token manually

# For GitHub Copilot:
# GITHUB_COPILOT_ACCESS_TOKEN=<PLEASE_FILL_IN_MANUALLY>  # ⚠️ Fill in manually
# GITHUB_COPILOT_REFRESH_TOKEN=<PLEASE_FILL_IN_MANUALLY>  # ⚠️ Optional, fill in manually
# GITHUB_COPILOT_EXPIRES=0

# ============================================================================
# Pipeline Configuration
# ============================================================================
DATA_DIR=<value>
INPUT_DIR=<value>
OUTPUT_DIR=<value>
INPUT_FILE=<value>
MAX_WORKERS=<value>

[... optional Docker configuration section ...]

[... optional Timeout configuration section ...]

[... optional External Repository section ...]

[... optional Crawler and Policy database section ...]
```

**Important:** For secret variables (API keys, tokens), use placeholder text like `<PLEASE_FILL_IN_MANUALLY>` with a warning comment. Never include actual secret values in the generated file.

Show the preview to the user and ask for confirmation.

### 11. Save Configuration and Next Steps

Ask: "Save this configuration to .env file?" (default: Yes)

If yes:
- Check if `.env` already exists at project root (use `dotenv_tool.py` to safely check)
- If exists, ask: ".env file already exists. Overwrite?" (default: No)
- If user confirms or file doesn't exist, write the file
- Show success message: "✅ Successfully created .env file at: <path>"
- **Important reminder:** "⚠️ Don't forget to manually fill in secret values (API keys, tokens) marked with <PLEASE_FILL_IN_MANUALLY> in the .env file"

### 12. Final Configuration Check and Next Steps

After saving the `.env` file, verify the configuration based on the selected workflow:

**For `generation` workflow:**
Run a configuration check:
```bash
# Check env, system, and database first
./pre-check.sh docker env binaries image mcp database local output
```

This will verify:
- 🟢 **docker**: Docker daemon is running (already checked in step 2)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available
- 🟢 **image**: Docker image is available (already checked in step 2)
- 🟢 **mcp**: MCP server is accessible (already checked in step 2)
- 🟢 **database**: Policy database is configured and exists
- 🟢 **output**: OUTPUT_DIR is empty (ready for pipeline execution)
- 🟢 **local**: EXTERNAL_REPO_DIR is not set

**For `generation_with_crawler` workflow:**
Run a configuration check:
```bash
# Check env and system first
./pre-check.sh docker env binaries image mcp local output
```

This will verify:
- 🟢 **docker**: Docker daemon is running (already checked in step 2)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available
- 🟢 **image**: Docker image is available (already checked in step 2)
- 🟢 **mcp**: MCP server is accessible (already checked in step 2)
- 🟢 **output**: OUTPUT_DIR is empty (ready for pipeline execution)
- 🟢 **local**: EXTERNAL_REPO_DIR is not set

**For `conversion_external` workflow:**
Run a configuration check (input files not needed yet):
```bash
# Check env and system (skip input check for external mode)
./pre-check.sh docker env binaries image mcp
```

This will verify:
- 🟢 **docker**: Docker daemon is running (already checked in step 2)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available
- 🟢 **image**: Docker image is available (already checked in step 2)
- 🟢 **mcp**: MCP server is accessible (already checked in step 2)

**For `conversion_local` workflow:**
Run a configuration check (input files may not be ready yet):
```bash
# Check env and system first
./pre-check.sh docker env binaries image mcp local output
```

This will verify:
- 🟢 **docker**: Docker daemon is running (already checked in step 2)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available
- 🟢 **image**: Docker image is available (already checked in step 2)
- 🟢 **mcp**: MCP server is accessible (already checked in step 2)
- 🟢 **output**: OUTPUT_DIR is empty (ready for pipeline execution)
- 🟢 **local**: EXTERNAL_REPO_DIR is not set

**Note:** Input file check is intentionally skipped here because users often prepare the data directory after creating `.env`. You can run `./pre-check.sh input` later after setting up your data directory.

**If any checks fail (🔴):**
- Show the error details from the pre-flight check output
- Provide guidance on how to fix the issues
- Common issues:
  - Missing secret values in `.env` (API keys, tokens)
  - Incorrect binary paths
  - MCP server not running

**If all checks pass (🟢):**
- Configuration is complete
- Proceed to next steps based on workflow

**Show next steps based on selected workflow:**

**For `generation` workflow:**
```
📋 Next Steps:
1. Fill in secret values (API keys, tokens) in .env file
2. Verify input files are ready: ./pre-check.sh input
3. Run the pipeline with: ./run.sh local

The script will:
- Read policy specifications from the database
- Generate TF policies based on policy_goal.txt
- Output results to DATA_DIR/OUTPUT_DIR/
```

**For `generation_with_crawler` workflow:**
```
📋 Next Steps:
1. Fill in secret values (API keys, tokens) in .env file
2. Execute crawler workflow:
   2.1. Run the crawler first (for crawling): ./run-crawler.sh add
   2.2. Modify crawler/crawler_goal.txt to specify the path to the generated delta file
        (See the generated crawler/guide/guide_{timestamp}.md for details)
   2.3. Run the crawler second (for applying): ./run-crawler.sh apply
3. Verify input files are ready: ./pre-check.sh input
4. Ensure your policy_goal.txt is ready at: DATA_DIR/INPUT_DIR/policy_goal.txt
5. Run the pipeline with: ./run.sh local

The script will:
- First, crawler extracts policy specifications from sources
- Then, generate TF policies based on policy_goal.txt using the extracted policy specifications
- Output results to DATA_DIR/OUTPUT_DIR/
```

**For `conversion_external` workflow:**
```
📋 Next Steps:
1. Fill in secret values (API keys, tokens) in .env file
2. Ensure your external repository contains Sentinel policy files
3. Run the pipeline with: ./run.sh external

The script will automatically:
- Extract Sentinel policies from: [EXTERNAL_REPO_DIR]
- Convert them to TF policies
- Deploy results back to the repository

Note: Input directory setup is not needed for external mode.
```

**For `conversion_local` workflow:**
```
📋 Next Steps:
1. Fill in secret values (API keys, tokens) in .env file
2. Set up your data directory:
   - Create: DATA_DIR/INPUT_DIR/sentinels/
   - Copy your .sentinel files there
   - Create: DATA_DIR/INPUT_DIR/policy_goal.txt with file paths
3. Verify input files are ready: ./pre-check.sh input
4. Run the pipeline with: ./run.sh local

Note: You can prepare the data directory at any time before running the pipeline.
```

If no:
- Show cancellation message: "❌ Setup cancelled. No .env file was created."

## Important Notes
- Always provide default values in square brackets when asking questions
- Use emojis to make the wizard more user-friendly (📦, 🔐, ⚙️, 🐳, ⏱️, 📁, 📄, ✅, ❌, ⚠️)
- Validate user inputs (paths, positive integers, etc.)
- Allow users to press Enter to accept defaults
- Handle cancellation gracefully (Ctrl+C or explicit "no" answers)
- Group related questions into sections with clear headers
- Always include helpful notes and instructions with questions
- **NEVER ask for or store secret values (API keys, tokens) directly** - always use placeholders and instruct users to fill them manually
- **ALWAYS use `dotenv_tool.py` when reading existing .env files** to prevent exposing secrets to the LLM

## Error Handling
- If user cancels at any point, show: "❌ Setup cancelled by user."
- If any error occurs, show: "❌ Error: <error message>"
- Don't proceed to save if validation fails

## Success Criteria
- `.env` file is created at project root with all required variables
- File format matches the expected structure
- User receives clear confirmation and next steps