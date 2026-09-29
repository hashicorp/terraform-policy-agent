# Cost Estimate — Terraform PAC Agent

This document provides approximate cost guidance for running the Terraform PAC Agent pipeline using different LLM providers.

---

## GitHub Copilot (Recommended)

GitHub Copilot is billed as a flat subscription — there are no per-token charges.

| Plan | Monthly Cost | Notes |
|---|---|---|
| Individual | $10/mo | Suitable for personal use and small batches |
| Business | $19/mo per seat | Suitable for team use |
| Enterprise | $39/mo per seat | Includes additional policy controls |

**Pipeline cost per policy:** $0 additional (covered by subscription)

> ⚠️ A valid paid GitHub Copilot subscription is **required**. Free accounts cannot authenticate with the Copilot API and will fail at Stage 0.

---

## Amazon Bedrock

Amazon Bedrock is billed per token (input + output).

**Estimated total cost for 10 policies (Claude Sonnet 5): $5–$10**

> Prices are approximate and subject to AWS pricing changes. See [AWS Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) for current rates.

---

## LiteLLM (Enterprise)

Cost depends on your organisation's LiteLLM endpoint configuration and the underlying model. Contact your LiteLLM administrator for cost information.

---

## Tips for Cost Control

- **Use GitHub Copilot** for most use cases — flat subscription cost with no per-run charges.
- **Start with a small batch** (5–10 policies) to validate output quality before running large batches.
- **Avoid Claude Opus** for batch runs — Sonnet offers comparable quality at a fraction of the cost.
- **Set `MAX_WORKERS`** appropriately to avoid unnecessary parallel API calls.
