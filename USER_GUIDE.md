# Terraform Policy Agent - User Guide

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites (Manual Setup)](#prerequisites-mannualy)
3. [Setup (Using tfpac-setup Skill)](#setup-using-tfpac-setup-skill)
4. [Run (Using tfpac-run Skill)](#run-using-tfpac-run-skill)
5. [Understanding the Output](#understanding-the-output)
6. [Advanced Usage](#advanced-usage)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The Terraform Policy Agent is a tool that automatically converts Sentinel policies to Terraform Policy (TFPolicy) format. This guide will walk you through the complete setup and usage process, by using a coding agent like OpenCode or GitHub Copilot CLI.

**What Terraform Policy Agent does:**
- Converts Sentinel policy code to TFPolicy format
- Generates test cases automatically
- Creates comprehensive documentation
- Validates the converted policies

**Workflow Overview:**
1. First, complete the [Prerequisites (Manual Setup)](#prerequisites-mannualy) to prepare your environment
2. Next, use the [Setup (Using tfpac-setup Skill)](#setup-using-tfpac-setup-skill) to create the `.env` configuration file
3. Finally, use the [Run (Using tfpac-run Skill)](#run-using-tfpac-run-skill) to execute the Terraform Policy Agent

**Time to complete:** Approximately 30 minutes for first-time setup

---

## Prerequisites (Manual Setup)

**Before using the skills, you must complete the following steps manually:**
- Step 0: Clone the Repository
- Step 1: Prepare Coding Agent
- Step 2: Install Docker
- Step 3: Setup MCP Server
- Step 4: Prepare Required Binaries
- Step 5: Prepare Conversion Data
- Step 6: Copy Skills to Designated Location

### Step 0: Clone the Repository

**Note:** You may have already completed this step. If so, you can skip it.

Open your terminal and run:

```bash
git clone git@github.com:hashicorp/terraform-policy-agent.git
cd terraform-policy-agent
```

**Expected result:**
```
$ ls
README.md                       pre-check.sh                    run_with_local_preparation.sh
USER_GUIDE.md                   pre_check.py                    sample-data
append_footer.py                run.sh                          skills
file_footer.hcl.template        run_pipeline.py                 stop.sh
github-copilot-access-setup.png run_with_external_repo.sh
```


### Step 1: Prepare Coding Agent

Install and set up your coding agent:

**Option A: OpenCode**

Download: https://opencode.ai/download

Launch:
```bash
opencode
```

**Option B: GitHub Copilot CLI**

Installation guide: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli

Launch:
```bash
copilot
```

### Step 2: Install Docker

Install Docker on your system:

**Option A: Docker Desktop**
- Download: https://www.docker.com/products/docker-desktop

**Option B: Rancher Desktop**
- Download: https://rancherdesktop.io/

**Verify installation:**
```bash
docker --version
```


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

**Note:** Remember this location, as you will need to specify these paths in [Step 6: Configure Terraform binary path](#step-6-configure-terraform-binary-path) and [Step 7: Configure TFPolicy binary path](#step-7-configure-tfpolicy-binary-path) during the [Setup (Using tfpac-setup Skill)](#setup-using-tfpac-setup-skill).

### Step 5: Prepare Conversion Data

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

### Step 6: Copy Skills to Designated Location

You need to copy the skills used by these two executions to their designated locations. Refer to the following instructions for OpenCode and GitHub Copilot CLI:

**For OpenCode:**

```bash
mkdir -p .opencode/skills
cp -R skills/tfpac-setup .opencode/skills/
cp -R skills/tfpac-run .opencode/skills/
```

**For GitHub Copilot CLI:**

```bash
mkdir -p .github/skills
cp -R skills/tfpac-setup .github/skills/
cp -R skills/tfpac-run .github/skills/
```



## Setup (Using tfpac-setup Skill)

This section demonstrates the actual tfpac-setup Skill execution using OpenCode. Since this is an AI Agent, you may notice minor differences between the screenshots and your execution results, but the overall flow is expected to be the same.

### Step 1: Execute the /skills command

![Skills Command](photo/setup/(1):skills.png)

Type `/skills` in your coding agent to view available skills.

### Step 2: Select the tfpac-setup skill

![Select tfpac-setup](photo/setup/(2):tfpac-setup_selection.png)

Choose `tfpac-setup` from the list of available skills to start the interactive environment setup wizard.

### Step 3: Confirm tfpac-setup execution

![Confirm tfpac-setup](photo/setup/(3):tfpac-setup_execution.png)

Press Enter in this state to execute the skill and begin the configuration wizard.

### Step 4: Docker image selection

![Docker Image Selection](photo/setup/(4)docker_image_selection.png)

Here, select the recommended Docker image (1. Yes). If the Docker image is not available locally, the system will help you pull it. In that case, follow the instructions to pull the image.

### Step 5: Select execution mode

![Local or External](photo/setup/(5)local_or_external.png)

Here, select "2. Local Mode" to use the `data/input` directory that you copied in [Prerequisites (Manual Setup)](#prerequisites-mannualy).

### Step 6: Configure Terraform binary path

![Terraform Binary](photo/setup/(6)terraform_binary.png)

Here, select "2. Type your own answer" and enter the path to your Terraform binary that you saved in [Step 4: Prepare Required Binaries](#step-4-prepare-required-binaries) of [Prerequisites (Manual Setup)](#prerequisites-mannualy).

Example: `/Users/<your-username>/terraform-binaries/terraform`

### Step 7: Configure TFPolicy binary path

![TFPolicy Binary](photo/setup/(7)tfpolicy_binary.png)

Here, select "2. Type your own answer" and enter the path to your TFPolicy binary that you saved in [Step 4: Prepare Required Binaries](#step-4-prepare-required-binaries) of [Prerequisites (Manual Setup)](#prerequisites-mannualy).

Example: `/Users/<your-username>/terraform-binaries/tfpolicy`

### Step 8: Select authentication provider

![Authentication Provider](photo/setup/(8)provider.png)

Choose your authentication method: LiteLLM (for enterprise endpoints) or GitHub Copilot. If you choose GitHub Copilot, the wizard will guide you through obtaining the required GitHub Copilot CLI credentials, as this setup is slightly more complex.

### Step 9: Pipeline configuration

![Pipeline Config](photo/setup/(9)pipeline_config.png)

For this guide, select the default (1. No). You can optionally customize pipeline settings such as data directories, input/output paths, and maximum workers for parallel processing.

### Step 10: Additional Docker settings

![Additional Docker](photo/setup/(10)additinal_docker.png)

For this guide, select the default (1. No). You can optionally configure additional Docker settings like container prefix.

### Step 11: Timeout configuration

![Timeout Settings](photo/setup/(11)timeout.png)

For this guide, select the default (1. No). You can optionally adjust timeout values for each pipeline stage based on your policy complexity and processing requirements. Try with default values first - they should work for most cases.

### Step 12: Configuration validation

![Configuration Check](photo/setup/(12)check.png)

Confirm that all required components (Docker, MCP server, binaries, and so on) are properly configured and accessible, before creating the `.env` file.

### Step 13: Preview generated .env file

![Preview Environment](photo/setup/(13)preview_env.png)

Review the generated `.env` file content before saving. Verify all settings are correct and note placeholders for secret values that need manual input.

### Step 14: Confirm save operation

![Save Confirmation](photo/setup/(14)save_or_not.png)

Confirm whether to save the configuration to the `.env` file. If the file already exists, you'll be asked whether to overwrite it. If there are no issues with the configuration, select "yes".

### Step 15: Setup completion and next steps

![Final Report](photo/setup/(15)final_report.png)

Review the setup completion report showing configuration summary and next steps.

**Important:** Remember to manually fill in secret values (API keys, tokens) marked as `<PLEASE_FILL_IN_MANUALLY>` in the `.env` file after this setup.


## Run (Using tfpac-run Skill)

### Step 1: Execute the /skills command

![Skills Command](photo/run/(1):skills.png)

Type `/skills` in your coding agent to view available skills.

### Step 2: Select the tfpac-run skill

![Select tfpac-run](photo/run/(2):skills_execution.png)

Choose `tfpac-run` from the list of available skills to start the policy conversion process.

### Step 3: Confirm tfpac-run execution

![Confirm tfpac-run](photo/run/(3):tfpac-run.png)

Press Enter in this state to execute the skill.

### Step 4: Choose data source location

![Local or External](photo/run/(4)local_or_external.png)

Here, select "1. Manual setup".

### Step 5: Pre-execution checks

![Pre-check](photo/run/(5)precheck.png)

The system performs pre-execution checks to verify all requirements are met before starting the conversion.

### Step 6: Output directory cleanup

![Output Cleanup](photo/run/(6)output_cleanup.png)

If an output directory exists, you will be asked what to do with it. Choose to create a backup or cleanup to avoid conflicts.

### Step 7: Pipeline execution starts

![Run Script](photo/run/(7)run.sh.png)

The `run.sh` script begins executing the policy conversion pipeline.

### Step 8: Select reporting time interval

![Time Selection](photo/run/(8)time_selection.png)

Select the time interval for reporting the process status.

### Step 9: Interim progress report

![Interim Report](photo/run/(9)interim_report.png)

The system provides interim reports to inform you of the current execution status, showing completed stages and progress.

### Step 10: Final conversion report

![Final Report](photo/run/(10)final_report.png)

Review the final report showing all converted policies, success rates, and any issues encountered.


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

---

### Reviewing Conversion Results

#### Step 1: Check the Summary Report

Open `data/output/summary.md` to get an overview of all conversions:

- **Conversion Statistics:** Success rate, total policies processed
- **Policy List:** Each policy's name, status, and key metrics
- **Quick Status:** See which policies succeeded or failed at a glance

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

---

## Advanced Usage

### Various Conversion Sources

In addition to sample data, you can convert various data sources using Method 1 through Method 3 as described below. For complex policies, you may need to increase timeouts in `.env`:


```bash
# For complex policy generation (Stage 2)
STAGE2_TIMEOUT=1200  # 20 minutes

# For large batch summaries (Stage 3)
STAGE3_TIMEOUT_BASE=300  # 5 minutes base
STAGE3_TIMEOUT_PER_POLICY=120  # 2 minutes per policy
```

#### Method 1: Convert Inline Sentinel Code (local)

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


---

#### Method 2: Convert from Sentinel Files (local)

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

#### Method 3: Convert External Repository (external)

To convert policies from an external repository (e.g., HashiCorp's CIS Policy Set):

**Step 1:** Download the repository:

```bash
curl -L https://github.com/hashicorp/policy-library-CIS-Policy-Set-for-AWS-Terraform/archive/refs/heads/main.zip | tar xz -C /tmp
```

**Step 2:** Configure the external repository path in `.env`:

```bash
EXTERNAL_REPO_DIR=/tmp/policy-library-CIS-Policy-Set-for-AWS-Terraform-main/policies/cloudtrail
```

この場合は、localではなくChoose data source locationで、externalを選択しなければいけない。


### Fine-Grained Execution

While this guide focuses on using coding agents (OpenCode or GitHub Copilot CLI), you can also run the pipeline manually without coding agent support. This allows for more fine-grained control, such as running specific stages of the pipeline or using custom prompts.

For more details, refer to the [README.md](README.md).

## Troubleshooting

If you encounter issues not covered here:

1. **Check logs:** Review stage logs in `data/output/stage*.log`
2. **Verify configuration:** Double-check all settings in `.env`

---

**Document Version:** 2.0  
**Last Updated:** June 2026  