---
name: tfpac-run
description: Operates the Terraform Policy Automation agent end to end. Use when checking prerequisites, preparing input guidance, running ./run.sh, reviewing data/output logs, or answering questions about generated Terraform policy artifacts.
---

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
python3 skills/tfpac-run/dotenv_tool.py .env
```

This script automatically masks sensitive values (API keys, tokens) before displaying them, preventing secrets from being exposed to the LLM. The tool identifies and masks the following secret variables:
- `MODEL_API_KEY`
- `GITHUB_COPILOT_ACCESS_TOKEN`
- `GITHUB_COPILOT_REFRESH_TOKEN`

When loading an existing .env file, use the dotenv_tool.py to safely retrieve non-secret configuration values.


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

Run the precheck tool with the selected workflow:

```bash
python3 skills/tfpac-run/scripts/precheck_tool.py --workflow {workflow}
```

Where `{workflow}` is one of: `conversion_local` or `conversion_external`.

**Analyze the JSON output:**

1. Check if `"ok": true` or `"ok": false`
2. If `"ok": false`, examine the `"errors"` array and `"checks"` object

**If prerequisites are not satisfied (`"ok": false`), stop and tell the user exactly what must be fixed:**

- **Missing environment variables** (`"missing_keys"`):
  - List each missing variable
  - Explain what each variable is for
  - Guide user to update `.env` file

- **Binary files not found or not executable** (`"binaries"`):
  - `terraform_exists: false` → Terraform binary not found at specified path
  - `terraform_executable: false` → Terraform binary exists but lacks execute permission (run `chmod +x <path>`)
  - `tfpolicy_exists: false` → tfpolicy binary not found at specified path
  - `tfpolicy_executable: false` → tfpolicy binary exists but lacks execute permission (run `chmod +x <path>`)

- **Input file not found** (`"input_file_exists": false`):
  - The policy_goal.txt file is missing
  - Guide user to create the file at the specified path

- **Docker image not found** (`"docker_image_exists": false`):
  - The required Docker image is not available locally
  - Guide user to pull the image: `docker pull <image_name>:<tag>`

**Example error analysis:**

```json
{
  "ok": false,
  "checks": {
    "missing_keys": ["MODEL_NAME", "TFPOLICY_BINARY_PATH"],
    "binaries": {
      "terraform_exists": true,
      "terraform_executable": false,
      "tfpolicy_exists": false,
      "tfpolicy_executable": false
    },
    "input_file": "data/input/policy_goal.txt",
    "input_file_exists": false,
    "docker_image": "icr.io/polaris-20251120/terraform-pac-agent:0.0.24",
    "docker_image_exists": false
  },
  "errors": [
    "missing env keys: MODEL_NAME, TFPOLICY_BINARY_PATH",
    "terraform binary not executable: /usr/local/bin/terraform",
    "tfpolicy binary not found: /usr/local/bin/tfpolicy",
    "input file not found: data/input/policy_goal.txt",
    "docker image not found: icr.io/polaris-20251120/terraform-pac-agent:0.0.24"
  ]
}
```

**Tell the user:**
```
❌ Prerequisites check failed. Please fix the following issues:

1. Missing environment variables in .env:
   - MODEL_NAME: The LLM model name to use (e.g., "claude-sonnet-4.6")
   - TFPOLICY_BINARY_PATH: Path to the tfpolicy binary

2. Terraform binary is not executable:
   - Path: /usr/local/bin/terraform
   - Fix: Run `chmod +x /usr/local/bin/terraform`

3. tfpolicy binary not found:
   - Expected path: /usr/local/bin/tfpolicy
   - Fix: Install tfpolicy binary or update TFPOLICY_BINARY_PATH in .env

4. Input file not found:
   - Expected path: data/input/policy_goal.txt
   - Fix: Create the file with your policy generation goals

5. Docker image not available:
   - Image: icr.io/polaris-20251120/terraform-pac-agent:0.0.24
   - Fix options:
     a) Pull the image: `docker pull icr.io/polaris-20251120/terraform-pac-agent:0.0.24`
     b) Update IMAGE_NAME and IMAGE_TAG in .env to use a different available image
```

**Only proceed to Step 3 if `"ok": true`.**

### Step 3: Run Pipeline

Only run the pipeline after prerequisites and input are confirmed.

Read [run-pipeline.md](run-pipeline.md) and execute the appropriate command based on the selected workflow.

### Step 4: Verify Output

Read [verify.md](verify.md).

Inspect generated files under `data/output`, review stage logs, and answer the user using the actual output files.

## Notes

- Prefer stable binary paths in `.env`. On macOS, avoid `/tmp` for mounted binaries when possible.
- Prefer stage log files under `data/output` over console-only output.
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