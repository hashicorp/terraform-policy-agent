---
name: tfpac-run
description: Run policy conversion pipeline (run after setup). Operates the Terraform Policy Automation agent end to end. Use when checking prerequisites, preparing input guidance, running ./run.sh, reviewing DATA_DIR/OUTPUT_DIR logs, or answering questions about generated Terraform policy artifacts.
---

# Single-policy mode

If `/tfpac-run --policy <name>` is called, or the user passes `--policy <name>`:

Set `SINGLE_POLICY_MODE=true` and `POLICY_NAME=<name>`.

In Step 3 (Run Pipeline), instead of the normal one-shot command, execute step by step as described in run-pipeline.md under "Single-policy mode".

# Dryrun mode

If `/tfpac-run --dryrun` is called, or the user passes `--dryrun`:

1. Tell the user: "This is a dry run. Only pre-execution checks will be performed — the pipeline will not start."
2. Execute Step 1 (Workflow selection) and Step 2 (Prerequisite check) only.
3. After the prerequisite check completes, stop and do not proceed to pipeline execution.

# ⚠️ IMPORTANT NOTE

**The purpose of this skill is to execute ALL steps in the following order:**

1. **Workflow selection**
2. **Prerequisite check**
3. **Pipeline execution**
4. **Output verification**

**You MUST complete all four steps sequentially as described below. Do not skip any step.**

# Security Note: Handling Existing .env Files

**CRITICAL:** Never directly read or load existing `.env` files using standard file reading tools, as they may contain sensitive secrets (API keys, tokens) that should not be exposed to the LLM.

**Always use the dotenv_tool.py script to load existing .env files:**
```bash
python3 skills/tfpac-run/scripts/dotenv_tool.py .env
```

This script automatically masks sensitive values (API keys, tokens) before displaying them, preventing secrets from being exposed to the LLM. The tool identifies and masks the following secret variables:
- `MODEL_API_KEY`
- `GITHUB_COPILOT_ACCESS_TOKEN`
- `GITHUB_COPILOT_REFRESH_TOKEN`

When loading an existing .env file, use the dotenv_tool.py to safely retrieve non-secret configuration values.

**⚠️ YOU MUST DO — Before executing any step under `## Workflow`:**
You MUST read the `.env` file exactly once before starting the workflow using this command.
```bash
python3 skills/tfpac-run/scripts/dotenv_tool.py .env
```

After running this command, interpret every environment variable as its actual resolved value (do NOT rewrite the skill file itself). For example:
- `DATA_DIR` → actual path (e.g. `data`)
- `OUTPUT_DIR` → actual path (e.g. `output`)
- All other variables → their actual resolved values

You only need to interpret the instructions with substituted values — never modify the skill file itself.

# Operating Terraform PAC Pipeline

Use this skill when working with the Terraform Policy Automation pipeline in this repository.

Follow this workflow in order:

1. Workflow selection
2. Prerequisite check
3. Pipeline execution
4. Output verification

Keep the user informed about the current step and do not skip prerequisite validation.

## Workflow

### Step 1: Workflow Selection

**Ask the user: "Which workflow do you want to use?"**

**Options:**
1. **Convert from Sentinel - Manual Setup (conversion_local)**
   - Convert existing Sentinel policies to TF policies
   - Manual data directory setup

2. **Convert from Sentinel - External Repository (conversion_external)**
   - Convert Sentinel policies from an external repository
   - Automatic extraction and conversion

Store the user's choice as one of: `conversion_local` or `conversion_external`.

### Step 2: Prerequisite Check

Run the precheck script based on the selected workflow:

**For `conversion_local` workflow:**
```bash
./pre-check.sh docker env binaries image mcp input local api
```

**For `conversion_external` workflow:**
```bash
./pre-check.sh docker env binaries image mcp api
```

**Analyze the output:**

Look for the status line at the top of the report:
- `✅ Status: READY` → All checks passed, proceed to Step 3
- `❌ Status: NOT READY` → Issues found, must fix before proceeding

**If prerequisites are not satisfied (`❌ Status: NOT READY`):**

Review the error messages and provide concise guidance. Common issues and fixes:

- **Docker image not found** → Login to IBM Cloud Container Registry (`docker login icr.io -u iamapikey`) and pull the image
- **Environment variables missing** → Add required variables (MODEL_NAME, AUTH_PROVIDER, etc.) to `.env` file
- **Binary not found** → Obtain binaries from HashiCorp representative or update TERRAFORM_BINARY_PATH/TFPOLICY_BINARY_PATH in `.env`
- **Binary not executable** → Run `chmod +x <path>` to add execute permission
- **Binary arch mismatch** → Binary CPU architecture does not match the Docker image; obtain the correct architecture binary (e.g. `arm64` vs `amd64`) from your HashiCorp representative and update `TERRAFORM_BINARY_PATH`/`TFPOLICY_BINARY_PATH` in `.env`
- **Binary OS mismatch** → Binary OS does not match the Docker image (e.g. `macos` binary used with a `linux` image); obtain the correct OS binary (`linux`) from your HashiCorp representative and update `TERRAFORM_BINARY_PATH`/`TFPOLICY_BINARY_PATH` in `.env`
- **MCP server not available** → Start MCP server with: `docker run -d --name terraform-mcp-server -p 8500:8080 -e TRANSPORT_MODE=streamable-http -e TRANSPORT_HOST=0.0.0.0 -e MCP_SESSION_MODE=stateless --restart unless-stopped docker.io/hashicorp/terraform-mcp-server:0.3.3`
- **Database not found** → Run crawler workflow first or update POLICY_DB path in `.env`
- **OUTPUT_DIR not empty** → Delete its contents or set a new OUTPUT_DIR in `.env` before running the pipeline
- **API credentials invalid** → Re-enter correct API key, token, or model name in `.env`

**Only proceed to Step 3 if status shows `✅ Status: READY`.**

### Step 3: Run Pipeline

Only run the pipeline after prerequisites and input are confirmed.

Read [run-pipeline.md](run-pipeline.md) and execute the appropriate command based on the selected workflow.

### Step 4: Verify Output

Read [verify.md](verify.md).

Inspect generated files under `DATA_DIR/OUTPUT_DIR`, review stage logs, and present a report to the user.

## Notes

- Prefer stable binary paths in `.env`. On macOS, avoid `/tmp` for mounted binaries when possible.
- Prefer stage log files under `DATA_DIR/OUTPUT_DIR` over console-only output.
- If a file is large, inspect only the relevant sections.
- Do not claim success if any critical stage failed.

- Always provide default values in square brackets when asking questions
- Use emojis to make the wizard more user-friendly (📦, 🔐, ⚙️, 🐳, ⏱️, 📁, 📄, ✅, ❌, ⚠️)
- Validate user inputs (paths, positive integers, etc.)
- Allow users to press Enter to accept defaults
- Handle cancellation gracefully (Ctrl+C or explicit "no" answers)
- Group related questions into sections with clear headers
- Always include helpful notes and instructions with questions
- **NEVER ask for or store secret values (API keys, tokens) directly** - always use placeholders and instruct users to fill them manually
- **ALWAYS use `dotenv_tool.py` when reading existing .env files** to prevent exposing secrets to the LLM
- **When presenting multiple options to the user, provide clickable suggestions that allow selection by simply pressing Enter**