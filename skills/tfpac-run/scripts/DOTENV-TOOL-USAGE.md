# dotenv_tool.py Usage Guide

## Overview

`dotenv_tool.py` is a utility for managing environment variables in `.env` files.

## Basic Commands

### Get Variables

```bash
# Get a single variable
./docs/slash-commands/scripts/dotenv_tool.py MODEL_BASE_URL

# Get multiple variables
./docs/slash-commands/scripts/dotenv_tool.py MODEL_BASE_URL MODEL_NAME

# Get all variables
./docs/slash-commands/scripts/dotenv_tool.py --all
```

### Set Variables

**IMPORTANT:** Use `--set` only once, then provide all KEY=VALUE pairs as separate arguments.

```bash
# Set a single variable
./docs/slash-commands/scripts/dotenv_tool.py --set MODEL_BASE_URL=http://host.docker.internal:18080

# Set multiple variables (correct way)
./docs/slash-commands/scripts/dotenv_tool.py --set MODEL_BASE_URL=http://host.docker.internal:18080 MODEL_API_KEY=my-api-key

# Values with spaces must be quoted
./docs/slash-commands/scripts/dotenv_tool.py --set "MODEL_NAME=[ete-lite] aws-claude-haiku-4-5"

# Multiple variables including quoted values
./docs/slash-commands/scripts/dotenv_tool.py --set MODEL_BASE_URL=http://host.docker.internal:18080 "MODEL_NAME=[ete-lite] aws-claude-haiku-4-5" MODEL_API_KEY=my-api-key
```

**Common Mistake:**
```bash
# ❌ WRONG - Do NOT repeat --set for each variable
./docs/slash-commands/scripts/dotenv_tool.py --set MODEL_BASE_URL=http://host.docker.internal:18080 --set MODEL_NAME=value --set MODEL_API_KEY=key

# ✅ CORRECT - Use --set once, then list all KEY=VALUE pairs
./docs/slash-commands/scripts/dotenv_tool.py --set MODEL_BASE_URL=http://host.docker.internal:18080 MODEL_NAME=value MODEL_API_KEY=key
```

### Unset Variables

```bash
# Remove a single variable
./docs/slash-commands/scripts/dotenv_tool.py --unset MODEL_BASE_URL

# Remove multiple variables
./docs/slash-commands/scripts/dotenv_tool.py --unset MODEL_BASE_URL MODEL_NAME
```

### Check Required Variables

```bash
# Check if all required variables are set
./docs/slash-commands/scripts/dotenv_tool.py --check
```

## Output Formats

```bash
# Default format (value only)
./docs/slash-commands/scripts/dotenv_tool.py MODEL_BASE_URL
# Output: http://host.docker.internal:18080

# Export format (for shell scripts)
./docs/slash-commands/scripts/dotenv_tool.py --all --format export
# Output: export MODEL_BASE_URL=http://host.docker.internal:18080

# JSON format
./docs/slash-commands/scripts/dotenv_tool.py --all --format json
# Output: "MODEL_BASE_URL": "http://host.docker.internal:18080",
```

## Custom .env File Path

```bash
# Use a different .env file
./docs/slash-commands/scripts/dotenv_tool.py MODEL_BASE_URL --env-file /path/to/.env
```

## Security Features

Secret variables (API keys, tokens) are automatically masked when displayed:

```bash
./docs/slash-commands/scripts/dotenv_tool.py MODEL_API_KEY
# Output: sk-*** (first 3 characters + ***)
```

Secret variables:
- `MODEL_API_KEY`
- `GITHUB_COPILOT_ACCESS_TOKEN`
- `GITHUB_COPILOT_REFRESH_TOKEN`

## Required Variables

The following variables are required for the terraform-pac-agent:
- `MODEL_BASE_URL`
- `MODEL_API_KEY`
- `MODEL_NAME`

Use `--check` to verify all required variables are set.

## Examples

### Initial Setup

```bash
# Set all required variables at once
./docs/slash-commands/scripts/dotenv_tool.py --set \
  MODEL_BASE_URL=http://host.docker.internal:18080 \
  "MODEL_NAME=[ete-lite] aws-claude-haiku-4-5" \
  MODEL_API_KEY=my-aws-api-key

# Verify configuration
./docs/slash-commands/scripts/dotenv_tool.py --check
./docs/slash-commands/scripts/dotenv_tool.py --all
```

### Update Configuration

```bash
# Change model
./docs/slash-commands/scripts/dotenv_tool.py --set "MODEL_NAME=[ete-lite] aws-claude-sonnet-4-5"

# Update multiple values
./docs/slash-commands/scripts/dotenv_tool.py --set \
  MODEL_BASE_URL=https://api.openai.com/v1 \
  MODEL_API_KEY=sk-new-key
```

### Troubleshooting

```bash
# Check what's currently set
./docs/slash-commands/scripts/dotenv_tool.py --all

# Verify required variables
./docs/slash-commands/scripts/dotenv_tool.py --check

# Get specific variable value
./docs/slash-commands/scripts/dotenv_tool.py MODEL_NAME