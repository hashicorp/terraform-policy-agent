---
name: tfpac-setup
description: Set up the environment (run this first). Guide users through an interactive wizard to create a `.env` file for the Terraform Policy Agent project by asking questions and generating a properly formatted `.env` file based on user responses. Supports the unified `run.sh` workflow, which automatically switches between local mode and external repository mode based on whether `EXTERNAL_REPO_DIR` is configured.
license: MPL-2.0
---

# Skill: Interactive Environment Setup Wizard


## Prerequisites
- Access to the project root directory (`terraform-policy-agent`)
- Ability to read `.env.example` file (if exists)
- Ability to write `.env` file to project root
- Access to `skills/tfpac-setup/dotenv_tool.py` for secure .env file handling

## Workflow Overview

This wizard supports the unified `run.sh` workflow with two execution modes, and guides users through the following steps to build the required environment for each mode:

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

When loading an existing .env file, use the dotenv_tool.py to safely retrieve non-secret configuration values. There is no need to mention this script to the user.

## Workflow

### GREETING (Always execute before entering the workflow below)

Show the following message to the user:

"""
👋 Hello! Welcome to the Terraform Policy Agent setup wizard.

This wizard will guide you through the configuration of the Terraform Policy Agent project.

Setup Overview:
   1. Environment checks      — verify Docker, images, and MCP server readiness
   2. Select workflow         — choose local or external repository mode
   3. Configure binary paths  — set up Terraform and TFPolicy binaries
   4. Configure AI provider   — select GitHub Copilot, LiteLLM, or Amazon Bedrock
   5. Configure pipeline      — set workers and output paths
   6. Docker configuration    — review image name and container settings
   7. Timeout configuration   — set stage timeouts
   8. Review settings         — confirm all configuration values
   9. Preview .env             — generate and review the configuration file
  10. Save .env               — write the validated configuration file
  11. Verify configuration    — run pre-flight checks to confirm readiness

When setup is complete, a validated `.env` configuration will be created and verified.
You will then be ready to run the Terraform Policy Agent workflow.
"""

> **`.env.tmp` — progress memo:** This wizard uses `.env.tmp` as a running memo. Each environment variable is noted here as it is confirmed. If a session is interrupted, check for `.env.tmp` and resume from where it left off.

**Session resume check:** Before anything else, check whether `.env.tmp` exists:
```bash
ls -la .env.tmp
```
- If **`.env.tmp` does not exist**: Proceed with a fresh setup.
- If **`.env.tmp` exists**: Assess how far the setup has progressed based on its contents. Tell the user (e.g., "Docker image and binary paths are configured, but authentication is not yet set."). Then ask: "Would you like to continue from where you left off, or start fresh by deleting `.env.tmp`?"
  - **Continue**: Skip already-completed steps and resume from the first incomplete step.
  - **Start fresh**: Delete `.env.tmp` and begin from Step 1a.

> **After each step completes, immediately update `.env.tmp` with any newly confirmed values before proceeding.**
> Also update the top of `.env.tmp` with a comment indicating the last completed step, e.g.:
> ```
> # LAST_COMPLETED_STEP=2b
> ```
> Update this comment every time a step finishes so that progress can be resumed accurately.

### 1. Pre-flight System Check
Display: `[1/11] Pre-flight System Check`

**Before configuring the environment, verify system readiness:**

**Step 1a: Determine the container CLI (docker or podman)**

The agent supports both Docker (default) and Podman. The CLI is configured with `DOCKER_CLI` in `.env`. Determine which one to use in this order:

1. **If `.env.tmp` already exists**, read it and check `DOCKER_CLI`.
   If it is set, use that value and skip detection.
2. **Otherwise, detect what is available:**
   ```bash
   docker --version 2>/dev/null; podman --version 2>/dev/null
   ```
3. **Decide based on the result:**
   - Only one is available → use it without asking.
   - Both are available → **Ask: "Which container CLI do you want to use?"** (options: `docker` (default), `podman`)
   - Neither is available → Show error: "No container CLI found. Please install Docker or Podman and ensure it is running." and stop here.

Store the result as `[DOCKER_CLI]` and use it for **every** container command in the rest of
this workflow. It is written to `.env.tmp` in Step 1b along with the image configuration.

**Note for Podman users:** No `docker` alias is needed. Setting `DOCKER_CLI=podman` in `.env` is
sufficient — all agent scripts (`run.sh`, `stop.sh`, `pre-check.sh`) read it from there.

**Step 1b: Container Image Configuration and Setup**

**Ask: "Do you want to use the latest recommended container image version?"**
- Recommended image: `docker.io/hashicorp/terraform-policy-agent:0.0.33`
- Default: Yes

If **Yes** (use recommended version):
- Set `IMAGE_NAME`: "docker.io/hashicorp/terraform-policy-agent"
- Set `IMAGE_TAG`: "0.0.33"

If **No** (custom version):
- Ask for `IMAGE_NAME` (default: "docker.io/hashicorp/terraform-policy-agent")
- Ask for `IMAGE_TAG` (default: "0.0.33")

**Check if image exists locally:**
```bash
[DOCKER_CLI] images --format "{{.Repository}}:{{.Tag}}" | grep "[IMAGE_NAME]:[IMAGE_TAG]" || echo "Image not found locally"
```

**Important:** If the output shows "Image not found locally", the image does not exist. Do not proceed until the image is pulled.

**Note for Podman:** Podman prefixes locally built images with `localhost/`, and pulled images with
their full registry name. Matching on `[IMAGE_NAME]:[IMAGE_TAG]` with `grep` works in both cases
because the registry-qualified name is used here.

**If image does not exist locally:**
- Show message: "📦 Container image not found locally. You need to pull it first. The image is approximately 1.1 GB. So let me check your available disk space first."
- Check available disk space and display the result to the user:
  ```bash
  df -h .
  ```
  If available space is less than 3 GB, warn: "⚠️ Low disk space detected. Please free up at least 3 GB before pulling." Then stop until the user confirms they have freed up space.

- The image is public on Docker Hub (https://hub.docker.com/r/hashicorp/terraform-policy-agent); **no login is required**. Do not ask the user to log in to any registry.
- Ask: "Ready to pull the container image. This will take several minutes on broadband. Continue? [Yes/No]"
  - If **No**: Stop and inform the user — "Pull skipped. Re-run setup when you are ready to pull the image."
  - If **Yes**: Display to the user: "Pulling the image now. You will see multiple download progress lines — this is normal. Please wait until it stops."
    Then run:
```bash
[DOCKER_CLI] pull [IMAGE_NAME]:[IMAGE_TAG]
```

**If image pull fails:**
- Show the exact error output
- Display the following recovery instructions:
  ```
  ❌ Pull failed. To retry manually, run:

     [DOCKER_CLI] pull [IMAGE_NAME]:[IMAGE_TAG]

  Once the pull succeeds, re-run tfpac-setup — it will resume from this step automatically via .env.tmp.
  ```
- **STOP HERE** - Do not proceed to Step 1c until the image is successfully pulled

**If image pull succeeds:**
- Run and display the pulled digest to the user:
  ```bash
  [DOCKER_CLI] images --digests [IMAGE_NAME] | grep [IMAGE_TAG]
  ```
- Show: "✅ Pulled: [IMAGE_NAME]:[IMAGE_TAG] (digest confirmed above)"
- Proceed to Step 1c

**If image already exists:**
- Show message: "✅ Container image already available locally"
- Proceed to Step 1c

**Note:** Image name, tag and container CLI are stored immediately to `.env.tmp` to ensure consistency. They will be included in the final `.env` file generation in Step 9.

**Step 1c: Check MCP server (Only after image is confirmed available)**

**Prerequisites for this step:**
- Container image must be pulled and available locally
- `.env.tmp` must contain `IMAGE_NAME`, `IMAGE_TAG` and `DOCKER_CLI` (set in Step 1b)

**Run MCP check:**
```bash
./pre-check.sh --tmp mcp
```

This check uses the container image and `DOCKER_CLI` specified in `.env.tmp` to verify MCP server connectivity.

- 🟢 **mcp**: MCP server is accessible at localhost:8500 via container

**If MCP check fails (🔴):**
- Show the exact error from the check output
- Display the following instructions:
  ```
  ❌ MCP server is not reachable. Start it with:

  [DOCKER_CLI] run -d --name terraform-mcp-server \
    -p 127.0.0.1:8500:8080 \
    -e TRANSPORT_MODE=streamable-http \
    -e TRANSPORT_HOST=0.0.0.0 \
    -e MCP_SESSION_MODE=stateless \
    docker.io/hashicorp/terraform-mcp-server:1.1.0

  Then re-run this check: ./pre-check.sh --tmp mcp

  If the check still fails after starting the MCP server, consider the following:

  - MCP server not started or port 8500 not accessible
  - The container cannot reach `host.docker.internal`
    - Rootless Podman on Linux only: `host.docker.internal` is not resolvable by default.
      Add to .env.tmp:  DOCKER_RUN_EXTRA_ARGS=--add-host=host.docker.internal:host-gateway
      Do NOT set this on macOS (Podman Desktop) — the VM already defines the host entry
      and Podman fails with `unable to replace "host-gateway"`.
  - Podman on an SELinux-enforcing host (RHEL / Fedora / CentOS Stream): bind mounts are denied.
    Add to .env.tmp:  DOCKER_RUN_EXTRA_ARGS="--security-opt label=disable"
  ```
- Do not proceed until the MCP check passes 🟢

**If all checks pass (🟢):**
- Proceed to workflow selection

**Note:** Binary paths and input file checks will be performed later after configuration is complete.

### 2. Workflow Selection
Display: `[2/11] Workflow Selection`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 1b
(If user chooses Back: restart from Step 1b.)

**Ask: "Which execution mode do you want to configure for `run.sh`?"**

Display the options below to the user exactly as-is.
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

After the user selects an option, confirm: "You selected: [selected mode]. Continue? [Yes/No]"
- If **No**: Re-display the options and ask again.

**Note:** If user selects option 1 (External Repository Mode), skip to step 2b. If option 2 (Local Mode), continue to step 2a.

### 2a. Local Mode - Data Directory Assistance (Only for `run.sh local`)

**Immediately set the following defaults in `.env.tmp`:**
```
DATA_DIR=./data
INPUT_DIR=input
INPUT_FILE=policy_goal.txt
```

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
- Check whether `./sample-data` exists:
  ```bash
  ls ./sample-data
  ```
  - If **`./sample-data` exists**, ask: "Would you like to try with the sample data first?"
    - If **Yes**:
      1. Run: `cp -r sample-data data`
      2. Write to `.env.tmp`:
         ```
         DATA_DIR=./data
         INPUT_DIR=input
         INPUT_FILE=policy_goal.txt
         ```
      3. Show confirmation: "✅ Sample data copied to data/. You can run the pipeline with the sample policies."
    - If **No**: Show instructions below.
  - If **`./sample-data` does not exist**: Show instructions below.
- Instructions:
  ```
  📋 Manual Setup Instructions:
  1. Create directory: data/input/sentinels/
  2. Copy your Sentinel (.sentinel) or OPA (.rego) policy files to data/input/sentinels/
  3. Create data/input/policy_goal.txt with content:
     Convert following Sentinel Policies to TF Policies:
     - ./data/input/sentinels/your-policy-1.sentinel
     - ./data/input/sentinels/your-policy-2.rego
  ```

### 2b. External Repository Setup (Only for `run.sh external`)

**This step is reached only if user selected "External Repository Mode" in step 2.**

**Ask: "What is the path to your external policy repository (Sentinel or OPA)?"**
- Parameter: `EXTERNAL_REPO_DIR`
- Default: "./workdir/workspaces/external_repo"
- Validation: Directory must exist
- Note: "This directory should contain your Sentinel (.sentinel) or OPA (.rego) policy files"

**Immediately write `EXTERNAL_REPO_DIR` to `.env.tmp` with the confirmed value.**

**Ask: "Do you have a sentinel.hcl file to configure?"**
- If **Yes**: Ask for `SENTINEL_HCL_PATH` (default: "./external_repo/sentinel.hcl")
- If **No**: Write `EXTERNAL_REPO_DIR=<SENTINEL_DIR>` to `.env.tmp` as a placeholder, and show:
  ```
  📋 Note: EXTERNAL_REPO_DIR has been set to the placeholder <SENTINEL_DIR> in `.env`.
  Replace it with the actual path to your Sentinel repository before running the pipeline.
  ```

**Note:** The script will automatically:
- Extract all .sentinel and .rego files from EXTERNAL_REPO_DIR (*_test.rego files are skipped)
- Skip files that already have tfpolicy/ conversions
- Generate policy_goal.txt automatically
- Deploy results back to the repository

### 3. Binary Paths Configuration
Display: `[3/11] Binary Paths Configuration`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 2
(If user chooses Back: restart from Step 2.)

**Step 3a-1: Set binary install path defaults**

Binary install paths are fixed regardless of host OS/architecture. Set the following defaults:
- `_TF_DEFAULT` = `./bin/terraform`
- `_TFP_DEFAULT` = `./bin/tfpolicy`

**Step 3b-1: Detect image OS and architecture**

Run the following command using `DOCKER_CLI`, `IMAGE_NAME` and `IMAGE_TAG` set in Step 1a/1b:
```bash
[DOCKER_CLI] image inspect [IMAGE_NAME]:[IMAGE_TAG] --format "{{.Architecture}}|{{.Os}}"
```
Store the results as `IMAGE_ARCH` (e.g. `arm64`, `amd64`) and `IMAGE_OS` (e.g. `linux`, `darwin`).

**Step 3b-2: Look up download URLs from the table below**

The binaries are mounted into and executed **inside** the container, so they must match the **image's** OS and architecture — not the host machine.

Use `IMAGE_OS`/`IMAGE_ARCH` to determine the correct download URLs for the binaries.

| Image OS | Image Arch | Terraform download URL | TFPolicy download URL |
|----------|------------|------------------------|-----------------------|
| linux | arm64 | `https://releases.hashicorp.com/terraform/1.17.0/terraform_1.17.0_linux_arm64.zip` | `https://releases.hashicorp.com/tfpolicy/0.5.0/tfpolicy_0.5.0_linux_arm64.zip` |
| linux | amd64 | `https://releases.hashicorp.com/terraform/1.17.0/terraform_1.17.0_linux_amd64.zip` | `https://releases.hashicorp.com/tfpolicy/0.5.0/tfpolicy_0.5.0_linux_amd64.zip` |
| darwin | arm64 | `https://releases.hashicorp.com/terraform/1.17.0/terraform_1.17.0_darwin_arm64.zip` | `https://releases.hashicorp.com/tfpolicy/0.5.0/tfpolicy_0.5.0_darwin_arm64.zip` |
| darwin | amd64 | `https://releases.hashicorp.com/terraform/1.17.0/terraform_1.17.0_darwin_amd64.zip` | `https://releases.hashicorp.com/tfpolicy/0.5.0/tfpolicy_0.5.0_darwin_amd64.zip` |

**If `IMAGE_OS`/`IMAGE_ARCH` matches one of the four rows above:**

Resolve the following **temporary variables**:
- `_TF_URL` — Terraform download URL
- `_TFP_URL` — TFPolicy download URL

If matched, proceed to **Step 3c: Configure Terraform binary**.

**If `IMAGE_OS`/`IMAGE_ARCH` does NOT match any row (unknown combination) → Proceed this fallback**

---

**Fallback 3-1: Configure Terraform binary**

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

  Terraform : https://releases.hashicorp.com/terraform/1.17.0/
  ```
- Ask: "Where did you download the Terraform binary?"
  - Store as `TERRAFORM_BINARY_PATH`.

**Fallback 3-2: Configure tfpolicy binary**

Ask: "Do you already have the tfpolicy binary? [Y/n]"

**If YES:**
- Ask: "What is the path to your tfpolicy binary?"
  - Store as `TFPOLICY_BINARY_PATH`.
- Proceed to **### Binary Paths Verification**.

**If NO:**
- Inform the user:
  ```
  ⚠️ Your image OS/arch combination is not in the known list.
  Please download the correct binaries manually from the following pages
  and select the package that matches your container (IMAGE_OS/IMAGE_ARCH):

  TFPolicy  : https://releases.hashicorp.com/tfpolicy/0.5.0/
  ```
- Ask: "Where did you download the tfpolicy binary?"
  - Store as `TFPOLICY_BINARY_PATH`.
- Proceed to **### Binary Paths Verification**.

---

**Step 3c: Configure Terraform binary**

Ask: "Do you already have the latest Terraform binary from https://releases.hashicorp.com/terraform ? [Y/n]"

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
  - If it fails, show the error and ask the user to obtain the binary manually at https://releases.hashicorp.com/terraform

---

**Step 3d: Configure tfpolicy binary**

Ask: "Do you already have the latest tfpolicy binary from https://releases.hashicorp.com/tfpolicy ? [Y/n]"

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
  - If it fails, show the error and ask the user to obtain the binary manually at https://releases.hashicorp.com/tfpolicy/0.5.0

### Binary Paths Verification

After both binary paths are confirmed, display a summary of the configured paths:

```
Binary Path Summary:
  terraform : <TERRAFORM_BINARY_PATH>
  tfpolicy  : <TFPOLICY_BINARY_PATH>
```

Then run the binary check against `.env.tmp`:

```bash
./pre-check.sh --tmp binaries
```

- 🟢 **binaries** → Proceed to **### 4. Authentication Provider Configuration**
- 🔴 **binaries** → Show the exact error output, then restart from the appropriate step in **### 3. Binary Paths Configuration**

### 4. Authentication Provider Configuration
Display: `[4/11] Authentication Provider Configuration`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 3
(If user chooses Back: restart from Step 3.)
Display the following trade-off summary before asking:
```
In this step, you will select one authentication provider that the pipeline uses to call the LLM. Choose from the 3 options below.

Authentication options:
  1. GitHub Copilot  — Easiest to set up. Requires a paid GitHub Copilot subscription ($10/mo+). Tokens expire and need periodic renewal.
  2. LiteLLM        — For enterprise/team environments with an existing LiteLLM endpoint. More control, but requires an endpoint URL and API key.
  3. Amazon Bedrock — For AWS environments. Requires a base64-encoded Bearer Token.

Recommended for first-time users: GitHub Copilot (option 1).
```

Ask: "Which authentication provider do you want to use?"

**Options:**

1. **GitHub Copilot CLI (Default)**
   - Set `AUTH_PROVIDER=github-copilot`
   - Ask for:
     - `MODEL_NAME` (default: "claude-sonnet-4.6"; any recent, capable model offered by the user's Copilot plan works, such as Claude Sonnet 4.6 or newer, Claude Opus or a current GPT model)
   
   **Then show GitHub Copilot CLI token acquisition guide:**
   
   ```
   🔐 How to Obtain GitHub Copilot Tokens
   
   To run this project, you need GitHub Copilot authentication tokens.
   
   ### Recommended Method: Safe Token Acquisition Using a Container ✨
   
   No need to install anything on your host machine - everything is self-contained in the project's container.
   
   **Step 1: Run the following command** (replace `[DOCKER_CLI]` with the CLI chosen in Step 1a)
   ```bash
   [DOCKER_CLI] run --rm -it --entrypoint "" \
     docker.io/hashicorp/terraform-policy-agent:0.0.33 \
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
     "access_token": "gho_xxxxxxxxxxxx",
     "refresh_token": "gho_xxxxxxxxxxxx",
     "expires": 1234567890
   }
   ```
   
   **Step 4: Paste into .env file**
   Later, you'll paste these values into the generated `.env` file:
   ```
   GITHUB_COPILOT_ACCESS_TOKEN=gho_xxxxxxxxxxxx
   GITHUB_COPILOT_REFRESH_TOKEN=gho_xxxxxxxxxxxx
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
   
   **💡 Why Use the Container?**
   - No need to install additional software on your host machine
   - Completely isolated from your project environment
   - Used only for obtaining credentials, then immediately removed (`--rm` flag)
   - Authenticates in the same environment as the container used by this project
   ```
   
   - `GITHUB_COPILOT_ACCESS_TOKEN` - Tell user to manually fill this in the .env file after generation
   - Optional: `GITHUB_COPILOT_REFRESH_TOKEN` - Tell user to manually fill this in the .env file
   - Optional: `GITHUB_COPILOT_EXPIRES` - Tell user to manually fill this in the .env file (default: "0")

2. **Amazon Bedrock (Bearer Token) (Default)**
   - Set `AUTH_PROVIDER=amazon-bedrock`
   - Ask for:
     - `MODEL_NAME` (default: "anthropic.claude-opus-4-5-20251101-v1:0")
     - `MODEL_API_KEY` - **IMPORTANT:** Tell user to manually fill this in the .env file after generation. Never ask for or store secret values directly. (Generate at: https://us-east-1.console.aws.amazon.com/bedrock/home)

3. **LiteLLM**
   - Set `AUTH_PROVIDER=litellm`
   - Ask for:
     - `MODEL_BASE_URL` (default: "https://your-litellm-endpoint.com")
     - `MODEL_NAME` (the model name as configured in the LiteLLM endpoint; no default)
     - `MODEL_API_KEY` - **IMPORTANT:** Tell user to manually fill this in the .env file after generation. Never ask for or store secret values directly. (Obtain from your LiteLLM endpoint administrator)

4. **Skip (configure manually later)**
   - Don't set authentication variables

### 5. Pipeline Configuration (Optional)
Display: `[5/11] Pipeline Configuration`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 4
(If user chooses Back: restart from Step 4.)

Always ask:
- **OUTPUT_DIR**: "Where would you like to save the output? [default: output] (within DATA_DIR, e.g., data/output/)"

Ask: "Do you want to customize other pipeline settings?" (default: No, note: "Default values work for most cases.")
If yes, ask for:
- **DATA_DIR** (default: "./data", note: "Relative paths are resolved from current working directory")
- **INPUT_DIR** (default: "input", note: "Within DATA_DIR (e.g., data/input/)")
- **INPUT_FILE** (default: "policy_goal.txt", note: "Relative to DATA_DIR/INPUT_DIR/")
- **MAX_WORKERS** (default: "5", validation: Must be a positive integer)

### 6. Container Configuration (Optional)
Display: `[6/11] Container Configuration`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 5
(If user chooses Back: restart from Step 5.)

Ask: "Do you want to customize additional container settings?" (default: No, note: "Image name, tag and container CLI were already configured in step 1a/1b")

If yes, ask for:
- **IMAGE_NAME** (default: value from step 1b, note: "Already configured")
- **IMAGE_TAG** (default: value from step 1b, note: "Already configured")
- **DOCKER_CLI** (default: value from step 1a, note: "Already configured. docker or podman")
- **CONTAINER_PREFIX** (default: "terraform-policy-agent-skills", note: "Useful for multi-environment or multi-user setups")
- **DOCKER_RUN_EXTRA_ARGS** (default: empty, note: "Host-specific flags appended to the container run command. Only needed for Podman on SELinux-enforcing hosts or rootless Podman on Linux — see below")

**DOCKER_RUN_EXTRA_ARGS guidance** (only offer this when `DOCKER_CLI` is `podman`):

| Host | Value |
|------|-------|
| macOS (Podman Desktop) | leave empty |
| Linux, SELinux enforcing | `"--security-opt label=disable"` |
| Linux, rootless, `host.docker.internal` unreachable | `--add-host=host.docker.internal:host-gateway` |
| Linux, both of the above | `"--security-opt label=disable --add-host=host.docker.internal:host-gateway"` |

**Important:** Wrap the value in double quotes whenever it contains a space, otherwise the shell reads only the first word.

### 7. Timeout Configuration (Optional)
Display: `[7/11] Timeout Configuration`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 6
(If user chooses Back: restart from Step 6.)

Ask: "Do you want to customize timeout settings?" (default: No, note: "Default values are usually sufficient")

If yes, ask for (all in seconds, must be positive integers):
- **STAGE0_TIMEOUT** (default: "600") - Policy Extraction timeout
- **STAGE1_TIMEOUT** (default: "300") - Requirement Generation timeout per goal
- **STAGE2_TIMEOUT** (default: "600") - Policy Generation timeout per policy (note: "For complex policies, consider 900+ seconds")
- **STAGE3_TIMEOUT_BASE** (default: "180") - Summary base timeout
- **STAGE3_TIMEOUT_PER_POLICY** (default: "60") - Summary additional timeout per policy

### 8. Review Configuration Summary
Display: `[8/11] Review Configuration Summary`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 7
(If user chooses Back: restart from Step 7.)

Show a summary of all configured values, grouped by category:

**For External Repository Mode (`run.sh external`):**

| Category | Item | Value |
|---|---|---|
| **Workflow** | Mode | External Repository |
| | External Repo | [EXTERNAL_REPO_DIR] |
| | Sentinel HCL | [SENTINEL_HCL_PATH or "N/A"] |
| **Authentication** | Provider | [AUTH_PROVIDER] |
| | Model | [MODEL_NAME] |
| | API Key / Token | ⚠️ Fill in manually after setup |
| **Binary Paths** | Terraform | [TERRAFORM_BINARY_PATH] |
| | TFPolicy | [TFPOLICY_BINARY_PATH] |
| **Pipeline Paths** | Data Dir | [DATA_DIR] |
| | Input Dir | [INPUT_DIR] |
| | Output Dir | [OUTPUT_DIR] |
| | Input File | [INPUT_FILE] |
| | Workers | [MAX_WORKERS] |

**For Local Mode (`run.sh local`):**

| Category | Item | Value |
|---|---|---|
| **Workflow** | Mode | Local |
| **Authentication** | Provider | [AUTH_PROVIDER] |
| | Model | [MODEL_NAME] |
| | API Key / Token | ⚠️ Fill in manually after setup |
| **Binary Paths** | Terraform | [TERRAFORM_BINARY_PATH] |
| | TFPolicy | [TFPOLICY_BINARY_PATH] |
| **Pipeline Paths** | Data Dir | [DATA_DIR] |
| | Input Dir | [INPUT_DIR] |
| | Output Dir | [OUTPUT_DIR] |
| | Input File | [INPUT_FILE] |
| | Workers | [MAX_WORKERS] |

Ask: "Does this configuration look correct?" (default: Yes)
- If No: Allow user to go back and modify settings
- If Yes: Proceed to generate .env file

### 9. Generate and Preview .env File
Display: `[9/11] Generate and Preview .env File`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 8
(If user chooses Back: restart from Step 8.)

**Generate .env file content based on selected workflow.**

**For External Repository Mode (`run.sh external`):**
- MUST include: EXTERNAL_REPO_DIR
- MUST include: SENTINEL_HCL_PATH (if configured)
- Include all standard configuration

**For Local Mode (`run.sh local`):**
- Do NOT include: EXTERNAL_REPO_DIR or SENTINEL_HCL_PATH
- Include all standard configuration

Based on the contents of `.env.tmp`, generate the `.env` file content with this structure:

```
# ============================================================================
# Generated by AI Agent Environment Setup Wizard
# ============================================================================

# ============================================================================
# Container CLI Configuration
# ============================================================================
# docker or podman. Podman users do not need a docker alias.
DOCKER_CLI=<value>

# ============================================================================
# Binary Paths (Required for the container runtime)
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

[... optional Container configuration section: IMAGE_NAME, IMAGE_TAG, CONTAINER_PREFIX, DOCKER_RUN_EXTRA_ARGS ...]

[... optional Timeout configuration section ...]

[... optional External Repository section ...]
```

**Important:** For secret variables (API keys, tokens), use placeholder text like `<PLEASE_FILL_IN_MANUALLY>` with a warning comment. Never include actual secret values in the generated file.

Show the preview to the user and ask for confirmation.

### 10. Save Configuration and Next Steps
Display: `[10/11] Save Configuration`

Ask: "Save this configuration to .env file? [Yes/No]"
- If **No**: Ask "Which value would you like to change? Enter the variable name and new value (e.g. OUTPUT_DIR=my-output):"
  - Accept input in `VARIABLE_NAME=value` format
  - Update `.env.tmp` with the new value
  - Restart from Step 9 to regenerate and preview the updated `.env` content

If yes:
- Check if `.env` already exists at project root (use `dotenv_tool.py` to safely check)
- If exists, ask: ".env file already exists. Overwrite?" (default: No)
- If user confirms or file doesn't exist, write the file
- Show success message: "✅ Successfully created .env file at: <path>"
- **Important reminder:** "⚠️ Don't forget to manually fill in secret values (API keys, tokens) marked with <PLEASE_FILL_IN_MANUALLY> in the .env file"

### 11. Final Configuration Check and Next Steps
Display: `[11/11] Final Configuration Check`
Ask the user to choose: **"Would you like to proceed or go back?"** — present exactly these two options in this order:
1. **Proceed** — continue to this step
2. **Back** — return to Step 10
(If user chooses Back: restart from Step 10.)

After saving the `.env` file, verify the configuration based on the selected workflow:

**For External Repository Mode:**
Run a configuration check (input files not needed yet):
```bash
# Check env and system (skip input check for external mode)
./pre-check.sh docker env binaries image mcp external
```

This will verify:
- 🟢 **docker**: Container engine (`DOCKER_CLI`) is running (already checked in step 1)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available (already checked in step 3)
- 🟢 **image**: Container image is available (already checked in step 1)
- 🟢 **mcp**: MCP server is accessible (already checked in step 1)

**For Local Mode:**
Run a configuration check (input files may not be ready yet):
```bash
# Check env and system first
./pre-check.sh docker env binaries image mcp local output
```

This will verify:
- 🟢 **docker**: Container engine (`DOCKER_CLI`) is running (already checked in step 1)
- 🟢 **env**: Environment variables are properly configured
- 🟢 **binaries**: terraform and tfpolicy binaries are available (already checked in step 3)
- 🟢 **image**: Container image is available (already checked in step 1)
- 🟢 **mcp**: MCP server is accessible (already checked in step 1)
- 🟢 **output**: OUTPUT_DIR is empty
- 🟢 **local**: EXTERNAL_REPO_DIR is not set

**Note:** Input file check is intentionally skipped here because users often prepare the data directory after creating `.env`. You can run `./pre-check.sh input` later after setting up your data directory.

**Note:** `docker` in the commands above is the name of the container-engine check, not the CLI itself. Keep it as `docker` even when `DOCKER_CLI=podman` — `pre-check.sh` reads `DOCKER_CLI` from `.env` and reports the engine it actually probed.

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
2. Validate API credentials: ./pre-check.sh api
3. Ensure your external repository contains Sentinel policy files
4. Run the pipeline with: ./run.sh external

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
2. Validate API credentials: ./pre-check.sh api
3. Set up your data directory:
   - Create: DATA_DIR/INPUT_DIR/sentinels/
   - Copy your .sentinel or .rego files there
   - Create: DATA_DIR/INPUT_DIR/policy_goal.txt with file paths
4. Verify input files are ready: ./pre-check.sh input
5. Run the pipeline with: ./run.sh local

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