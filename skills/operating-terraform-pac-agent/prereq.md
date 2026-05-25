# Prerequisite Check

Use this guide before running or verifying the Terraform Policy Automation pipeline.

## Goal

Confirm that the environment, binaries, Docker image, and input file are ready.

## Checklist

Copy this checklist and track progress if the task is long:

```text
Terraform PAC prerequisite progress:
- [ ] Confirm .env exists
- [ ] Confirm required environment variables are present
- [ ] Confirm terraform and tfpolicy binaries exist and are executable
- [ ] Confirm input file exists
- [ ] Confirm Docker image exists
```

## What to check

### 1. `.env`

Confirm that `.env` exists.

Expected keys include:

- `AUTH_PROVIDER`
- `MODEL_NAME`
- For LiteLLM:
  - `MODEL_BASE_URL`
  - `MODEL_API_KEY`
- For GitHub Copilot:
  - `GITHUB_COPILOT_ACCESS_TOKEN`
- `IMAGE_NAME`
- `IMAGE_TAG`
- `DATA_DIR`
- `INPUT_DIR`
- `INPUT_FILE`
- `OUTPUT_DIR`
- `TERRAFORM_BINARY_PATH`
- `TFPOLICY_BINARY_PATH`

Use:

```bash
python3 skills/operating-terraform-pac-agent/scripts/dotenv_tool.py .env
```

### 2. Binary paths

Confirm that:

- `TERRAFORM_BINARY_PATH` points to a real executable file
- `TFPOLICY_BINARY_PATH` points to a real executable file

On macOS, prefer stable paths such as the project directory or home directory instead of `/tmp`.

Use:

```bash
python3 skills/operating-terraform-pac-agent/scripts/precheck_tool.py
```

### 3. Input file

Confirm that `data/input/policy_goal.txt` exists, unless `.env` sets a different `INPUT_FILE`.

If the input file is missing, ask the user to prepare it manually.

Accepted patterns include:

#### Option A: Inline Sentinel code

````text
Generate TF Policy for
```sentinel
...sentinel code...
```
````

#### Option B: Sentinel file paths

```text
Generate TF Policy for
./data/input/sentinels/policy1.sentinel
./data/input/sentinels/policy2.sentinel
```

Do not invent policy input unless the user explicitly asks.

### 4. Docker image

Confirm that the configured Docker image exists:

```bash
docker image inspect <IMAGE_NAME>:<IMAGE_TAG>
```

## Stop conditions

Do not run the pipeline if any of the following are true:

- `.env` is missing
- required authentication variables are missing
- terraform or tfpolicy binary is missing
- binary file is not executable
- input file is missing
- Docker image does not exist

When a prerequisite fails, tell the user exactly what is missing and how to fix it.