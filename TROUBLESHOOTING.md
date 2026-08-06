# Terraform Policy Agent - Troubleshooting Guide

## Stage 0: Authorization failed

**Symptom:**
```
Stage 0: Authorization failed. Exiting.
```

**Possible causes and fixes:**

| Provider | Fix |
|---|---|
| GitHub Copilot | Check your subscription at https://github.com/settings/copilot. Verify `GITHUB_COPILOT_ACCESS_TOKEN` (and optionally `GITHUB_COPILOT_REFRESH_TOKEN`) in `.env` are correct. Also verify `MODEL_NAME` is a valid GitHub Copilot model (e.g. `claude-sonnet-5`). |
| LiteLLM | Verify `MODEL_BASE_URL`, `MODEL_API_KEY`, and `MODEL_NAME` in `.env` are correct. |
| Amazon Bedrock | Verify `MODEL_API_KEY` (Base64-encoded Bearer Token) and `MODEL_NAME` in `.env` are correct. |

---

## `code .` — command not found

**Symptom:**
```
zsh: command not found: code
```

**Fix:**
Open VS Code, press `Cmd+Shift+P`, search for **Shell Command: Install 'code' command in PATH**, and run it. Then restart your terminal.

---

## Pipeline was working before but now fails at Stage 0

**Symptom:**
The pipeline ran successfully before, but now fails immediately at Stage 0 with an authorization error.

**Step 1: Check if your API credentials are still valid**

Run the following command first to confirm whether the token is the cause:

```bash
./pre-check.sh api
```

- 🟢 **api** — credentials are valid. The issue is not token-related; check other Stage 0 causes above.
- 🔴 **api** — credentials are invalid or expired. Proceed to Step 2.

**Step 2: Re-acquire your GitHub Copilot tokens**

GitHub Copilot access tokens expire periodically. When a token expires, the pipeline fails silently at Stage 0 with no clear indication that the token is the cause.

Re-acquire your GitHub Copilot tokens by following the [**"How to get GitHub Copilot tokens"** section in the README](./README.md#how-to-get-github-copilot-tokens), then update `GITHUB_COPILOT_ACCESS_TOKEN` (and optionally `GITHUB_COPILOT_REFRESH_TOKEN` and `GITHUB_COPILOT_EXPIRES`) in your `.env` file.


---

## Token exposed or compromised — immediate revocation steps

If you suspect a token has been leaked (e.g. visible in a screenshot, committed to Git, shared in a support request), revoke it immediately using the steps below.

### GitHub Copilot token

1. Go to [https://github.com/settings/tokens](https://github.com/settings/tokens)
2. Find the token (look for tokens starting with `ghu_` or `ghp_`)
3. Click **Delete** to revoke it
4. Re-acquire new tokens by following the [**"How to get GitHub Copilot tokens"** section in the README](./README.md#how-to-get-github-copilot-tokens)
5. Update `GITHUB_COPILOT_ACCESS_TOKEN` (and optionally `GITHUB_COPILOT_REFRESH_TOKEN`) in your `.env` file

### Amazon Bedrock API key

1. Go to [https://us-east-1.console.aws.amazon.com/iam/home#/security_credentials](https://us-east-1.console.aws.amazon.com/iam/home#/security_credentials)
2. Find the exposed access key under **Access keys**
3. Click **Actions → Deactivate**, then **Delete**
4. Create a new access key and generate a new Base64-encoded Bearer Token
5. Update `MODEL_API_KEY` in your `.env` file

### LiteLLM API key

1. Contact your LiteLLM endpoint administrator to revoke the exposed key
2. Request a new API key
3. Update `MODEL_API_KEY` in your `.env` file


---

## No GitHub Copilot subscription or AWS Bedrock access — using a local LLM via LiteLLM

If you don't have access to GitHub Copilot or Amazon Bedrock, you can run the pipeline fully offline by hosting a local LLM behind a LiteLLM-compatible endpoint.

**Setup:**

1. Install and start a local LLM server (e.g. [Ollama](https://ollama.ai), [LM Studio](https://lmstudio.ai), or any OpenAI-compatible server)
2. Start LiteLLM as a proxy pointing to your local model:
   ```bash
   pip install litellm
   litellm --model ollama/llama3 --port 8000
   ```
3. Set the following in your `.env`:
   ```
   AUTH_PROVIDER=litellm
   MODEL_BASE_URL=http://localhost:8000
   MODEL_NAME=ollama/llama3
   MODEL_API_KEY=dummy
   ```
4. Run the pipeline as normal:
   ```bash
   ./run.sh local
   ```

> **Note:** Local models may produce lower quality conversions than cloud models. Test with a small batch first.


---

## macOS: "Terminal would like to control Script Editor" permission dialog

**Symptom:**
A system dialog appears during the pipeline run:
> "Terminal" would like to control "Script Editor". Allowing control will provide access to documents and data in "Script Editor", and to perform actions within that app.

**Fix:**
Click **OK** to allow. The pipeline requires this Automation permission to operate correctly on macOS.

**If the pipeline stops for no apparent reason — this might be why:**
On corporate Macs managed via MDM, the Automation permission can be silently denied — no dialog appears, no error is shown, the pipeline simply stops. If you cannot identify the cause, check this first:

1. Open **System Settings → Privacy & Security → Automation**
2. Find **Terminal** in the list and ensure **Script Editor** is checked.

If the toggle is greyed out, you cannot fix this yourself — ask your IT administrator to grant `com.apple.Terminal` automation access.

