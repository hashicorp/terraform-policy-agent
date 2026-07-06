---
name: tfpac-setup
description: Guide users through an interactive wizard to create a `.env` file for the Terraform Policy Agent project by asking questions and generating a properly formatted `.env` file based on user responses. Supports the unified `run.sh` workflow, which automatically switches between local mode and external repository mode based on whether `EXTERNAL_REPO_DIR` is configured.
---

# Skill: Interactive Environment Setup Wizard


## Prerequisites
- Access to the project root directory (`terraform-policy-agent`)
- Ability to read `.env.example` file (if exists)
- Ability to write `.env` file to project root
- Access to `skills/tfpac-setup/dotenv_tool.py` for secure .env file handling

## Workflow Overview

This wizard supports the unified `run.sh` workflow with two execution modes:

1. **External Repository Mode (`run.sh external`)**
   - Automatically extracts Sentinel policies from an external repository
   - Converts them to TF policies
   - Deploys results back to the external repository
   - Requires: `EXTERNAL_REPO_DIR` in `.env`
   - `run.sh` may also auto-select this mode when `EXTERNAL_REPO_DIR` is set

2. **Local Mode (`run.sh local`)**
   - User manually prepares the data directory structure
   - User provides Sentinel policy files
   - User creates `policy_goal.txt` with file paths
   - More control over input files and structure
   - Used when `EXTERNAL_REPO_DIR` is not set

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

### 1. Introduction and System Check
Start by:
- Greeting the user and explaining the wizard's purpose
- Detecting the operating system and architecture
- Providing appropriate default values based on the system
- If `.env` file exists, use `dotenv_tool.py` to load existing non-secret values (secrets will be masked)

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
- Recommended image: `icr.io/polaris-20251120/terraform-pac-agent:0.0.27`
- Default: Yes

If **Yes** (use recommended version):
- Set `IMAGE_NAME`: "icr.io/polaris-20251120/terraform-pac-agent"
- Set `IMAGE_TAG`: "0.0.26"

If **No** (custom version):
- Ask for `IMAGE_NAME` (default: "icr.io/polaris-20251120/terraform-pac-agent")
- Ask for `IMAGE_TAG` (default: "0.0.26")

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

### 3. Workflow Selection

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

**Note:** If user selects option 1 (External Repository Mode), skip to step 3b. If option 2 (Local Mode), continue to step 3a.

### 3a. Local Mode - Data Directory Assistance (Only for `run.sh local`)

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

### 3b. External Repository Setup (Only for `run.sh external`)

**This step is reached only if user selected "External Repository Mode" in step 3.**

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

**System-specific defaults:**
- macOS (arm64): `/opt/homebrew/bin/terraform`, `/usr/local/bin/tfpolicy`
- macOS (x86_64): `/usr/local/bin/terraform`, `/usr/local/bin/tfpolicy`
- Linux: `/usr/local/bin/terraform`, `/usr/local/bin/tfpolicy`

### 4. Binary Paths Configuration
Ask the user for:

**TERRAFORM_BINARY_PATH:**
- Question: "What is the path to your Terraform binary?"
- Default: System-specific (see above)
- Validation: Must be a valid path
- Note: "Terraform CLI is currently in beta. Contact your HashiCorp representative to obtain the binary. This binary must be executable and match your container architecture."

**TFPOLICY_BINARY_PATH:**
- Question: "What is the path to your tfpolicy binary?"
- Default: System-specific (see above)
- Validation: Must be a valid path
- Note: "tfpolicy is currently in beta. Contact your HashiCorp representative to obtain the binary. This binary must be executable and match your container architecture."

### 5. Authentication Provider Configuration
Ask: "Which authentication provider do you want to use?"

**Options:**
1. **LiteLLM (Default)**
   - Set `AUTH_PROVIDER=litellm`
   - Ask for:
     - `MODEL_BASE_URL` (default: "https://your-litellm-endpoint.com")
     - `MODEL_NAME` (default: "aws/claude-sonnet-4-5")
     - `MODEL_API_KEY` - **IMPORTANT:** Tell user to manually fill this in the .env file after generation. Never ask for or store secret values directly.

2. **GitHub Copilot CLI**
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
     icr.io/polaris-20251120/terraform-pac-agent:0.0.27 \
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

3. **Skip (configure manually later)**
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

### 8. Timeout Configuration (Optional)
Ask: "Do you want to customize timeout settings?" (default: No, note: "Default values are usually sufficient")

If yes, ask for (all in seconds, must be positive integers):
- **STAGE0_TIMEOUT** (default: "600") - Policy Extraction timeout
- **STAGE1_TIMEOUT** (default: "300") - Requirement Generation timeout per goal
- **STAGE2_TIMEOUT** (default: "600") - Policy Generation timeout per policy (note: "For complex policies, consider 900+ seconds")
- **STAGE3_TIMEOUT_BASE** (default: "180") - Summary base timeout
- **STAGE3_TIMEOUT_PER_POLICY** (default: "60") - Summary additional timeout per policy

### 9. Review Configuration Summary

Show a summary of all configured values based on the selected workflow:

**For External Repository Mode (`run.sh external`):**
- Workflow: External Repository Mode
- External Repository: [EXTERNAL_REPO_DIR value]
- Sentinel HCL: [SENTINEL_HCL_PATH value or "Not configured"]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [DATA_DIR, INPUT_DIR, OUTPUT_DIR, etc.]

**For Local Mode (`run.sh local`):**
- Workflow: Local Mode
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

**For External Repository Mode (`run.sh external`):**
- MUST include: EXTERNAL_REPO_DIR
- MUST include: SENTINEL_HCL_PATH (if configured)
- Include all standard configuration

**For Local Mode (`run.sh local`):**
- Do NOT include: EXTERNAL_REPO_DIR or SENTINEL_HCL_PATH
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

# MCP Server Configuration (already set in Dockerfile, no need to change)
POLICY_DB=database/policy_spec_db.jsonl
POLICY_SUMMARY=database/POLICY_SUMMARY.md

# ============================================================================
# Execution Mode: OpenCode
# ============================================================================
AUTH_PROVIDER=<value>
MODEL_BASE_URL=<value>
MODEL_NAME=<value>
MODEL_API_KEY=<PLEASE_FILL_IN_MANUALLY>  # ⚠️ Fill in your API key manually

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

**For External Repository Mode:**
Run a configuration check (input files not needed yet):
```bash
# Check env and system (skip input check for external mode)
./pre-check.sh docker env binaries image mcp
```

This will verify:
- 🟢 **docker**: Docker daemon is running (already checked in step 2)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available (already checked in step 2)
- 🟢 **image**: Docker image is available (already checked in step 2)
- 🟢 **mcp**: MCP server is accessible (already checked in step 2)

**For Local Mode:**
Run a configuration check (input files may not be ready yet):
```bash
# Check env and system first
./pre-check.sh docker env binaries image mcp
```

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

**For External Repository Mode (`run.sh external`):**
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

**For Local Mode (`run.sh local`):**
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