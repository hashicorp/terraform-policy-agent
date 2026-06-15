---
name: tfpac-setup
description: Guide users through an interactive wizard to create a `.env` file for the Terraform Policy Agent project by asking questions and generating a properly formatted `.env` file based on user responses. Supports two workflows - run.sh (manual data directory setup) and run_with_external_repo.sh (external repository integration).
---

# Skill: Interactive Environment Setup Wizard


## Prerequisites
- Access to the project root directory (`terraform-policy-agent`)
- Ability to read `.env.example` file (if exists)
- Ability to write `.env` file to project root
- Access to `skills/tfpac-setup/dotenv_tool.py` for secure .env file handling

## Workflow Overview

This wizard supports two different workflows:

1. **run_with_external_repo.sh** - External Repository Integration
   - Automatically extracts Sentinel policies from an external repository
   - Converts them to TF policies
   - Deploys results back to the external repository
   - Requires: `EXTERNAL_REPO_DIR` in .env
   - Simple setup: Just specify the external repo directory

2. **run.sh** - Manual Data Directory Setup
   - User manually creates data directory structure
   - User provides Sentinel policy files
   - User creates policy_goal.txt with file paths
   - More control over input files and structure
   - Requires: Manual setup of `data/input/sentinels/` and `policy_goal.txt`

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
- Detecting the operating system and architecture
- Providing appropriate default values based on the system
- If `.env` file exists, use `dotenv_tool.py` to load existing non-secret values (secrets will be masked)

**Ask: "Which workflow do you want to use?"**

**Options:**
1. **External Repository Integration (run_with_external_repo.sh)** - Recommended for existing Sentinel repositories
   - Automatically extracts Sentinel policies from your external repository
   - Converts them to TF policies
   - Deploys results back to the repository
   - Simple setup: Just specify `EXTERNAL_REPO_DIR`
   
2. **Manual Data Directory Setup (run.sh)** - For custom policy conversion
   - You manually create data directory structure
   - You provide Sentinel policy files in `data/input/sentinels/`
   - You create `policy_goal.txt` with file paths to convert
   - More control over which files to convert

**Note:** If user selects option 1 (External Repository), skip to step 1b. If option 2 (Manual Setup), continue to step 1a.

### 1a. Manual Setup - Data Directory Assistance (Only for run.sh workflow)

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

### 1b. External Repository Setup (Only for run_with_external_repo.sh workflow)

**This step is reached only if user selected "External Repository Integration" in step 1.**

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

### 2. Binary Paths Configuration
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

### 3. Authentication Provider Configuration
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
     icr.io/polaris-20251120/terraform-pac-agent:0.0.24 \
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

### 4. Pipeline Configuration (Optional)
Ask: "Do you want to customize pipeline settings?" (default: No, note: "Default values work for most cases. You can change output directory or other settings if needed.")

If yes, ask for:
- **DATA_DIR** (default: "./data", note: "Relative paths are resolved from current working directory")
- **INPUT_DIR** (default: "input", note: "Within DATA_DIR (e.g., data/input/)")
- **OUTPUT_DIR** (default: "output", note: "Within DATA_DIR (e.g., data/output/)")
- **INPUT_FILE** (default: "policy_goal.txt", note: "Relative to DATA_DIR/INPUT_DIR/")
- **MAX_WORKERS** (default: "5", validation: Must be a positive integer)

### 5. Docker Configuration (Optional)
Ask: "Do you want to customize Docker settings?" (default: No)

If yes, ask for:
- **IMAGE_NAME** (default: "icr.io/polaris-20251120/terraform-pac-agent")
- **IMAGE_TAG** (default: "0.0.24")
- **CONTAINER_PREFIX** (default: "terraform-pac-agent-skills", note: "Useful for multi-environment or multi-user setups")

### 6. Timeout Configuration (Optional)
Ask: "Do you want to customize timeout settings?" (default: No, note: "Default values are usually sufficient")

If yes, ask for (all in seconds, must be positive integers):
- **STAGE0_TIMEOUT** (default: "600") - Policy Extraction timeout
- **STAGE1_TIMEOUT** (default: "300") - Requirement Generation timeout per goal
- **STAGE2_TIMEOUT** (default: "600") - Policy Generation timeout per policy (note: "For complex policies, consider 900+ seconds")
- **STAGE3_TIMEOUT_BASE** (default: "180") - Summary base timeout
- **STAGE3_TIMEOUT_PER_POLICY** (default: "60") - Summary additional timeout per policy

### 7. Review Configuration Summary

Show a summary of all configured values based on the selected workflow:

**For External Repository Integration (run_with_external_repo.sh):**
- Workflow: External Repository Integration
- External Repository: [EXTERNAL_REPO_DIR value]
- Sentinel HCL: [SENTINEL_HCL_PATH value or "Not configured"]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [DATA_DIR, INPUT_DIR, OUTPUT_DIR, etc.]

**For Manual Data Directory Setup (run.sh):**
- Workflow: Manual Data Directory Setup
- Data Directory: [DATA_DIR value]
- Input Directory: [INPUT_DIR value]
- Binary Paths: [TERRAFORM_BINARY_PATH, TFPOLICY_BINARY_PATH]
- Authentication: [AUTH_PROVIDER details]
- Pipeline Settings: [OUTPUT_DIR, INPUT_FILE, etc.]

Ask: "Does this configuration look correct?" (default: Yes)
- If No: Allow user to go back and modify settings
- If Yes: Proceed to generate .env file

### 8. Generate and Preview .env File

**Generate .env file content based on selected workflow.**

**For External Repository Integration (run_with_external_repo.sh):**
- MUST include: EXTERNAL_REPO_DIR
- MUST include: SENTINEL_HCL_PATH (if configured)
- Include all standard configuration

**For Manual Data Directory Setup (run.sh):**
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

### 9. Save Configuration and Next Steps

Ask: "Save this configuration to .env file?" (default: Yes)

If yes:
- Check if `.env` already exists at project root (use `dotenv_tool.py` to safely check)
- If exists, ask: ".env file already exists. Overwrite?" (default: No)
- If user confirms or file doesn't exist, write the file
- Show success message: "✅ Successfully created .env file at: <path>"
- **Important reminder:** "⚠️ Don't forget to manually fill in secret values (API keys, tokens) marked with <PLEASE_FILL_IN_MANUALLY> in the .env file"

**Suggest next steps based on selected workflow:**

**For External Repository Integration (run_with_external_repo.sh):**
```
📋 Next Steps:
1. Fill in secret values (API keys, tokens) in .env file
2. Run the pipeline with: ./run_with_external_repo.sh

The script will automatically:
- Extract Sentinel policies from: [EXTERNAL_REPO_DIR]
- Convert them to TF policies
- Deploy results back to the repository
```

**For Manual Data Directory Setup (run.sh):**
```
📋 Next Steps:
1. Fill in secret values (API keys, tokens) in .env file
2. Set up your data directory:
   - Create: data/input/sentinels/
   - Copy your .sentinel files to: data/input/sentinels/
   - Create: data/input/policy_goal.txt with file paths
3. Run the pipeline with: ./run.sh
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