#!/usr/bin/env python3
"""
Use LLM to match policy names between summary.md and report.md.
"""

import os
import sys
import json
import requests

# Load environment variables
API_PROVIDER = os.getenv('API_PROVIDER', 'litellm')
MODEL_BASE_URL = os.getenv('MODEL_BASE_URL', 'https://ete-litellm.ai-models.vpc-int.res.ibm.com')
MODEL_API_KEY = os.getenv('MODEL_API_KEY', '')
MODEL_NAME = os.getenv('MODEL_NAME', 'aws/claude-sonnet-4-5')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')


def call_llm_bedrock(prompt: str) -> str:
    """Call AWS Bedrock API."""
    model_name = MODEL_NAME
    if not model_name.startswith('us.') and not model_name.startswith('eu.'):
        if model_name.startswith('anthropic.'):
            model_name = f"us.{model_name}"
    
    url = f"https://bedrock-runtime.{AWS_REGION}.amazonaws.com/model/{model_name}/converse"
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {MODEL_API_KEY}'
    }
    
    payload = {
        'messages': [{'role': 'user', 'content': [{'text': prompt}]}],
        'inferenceConfig': {'temperature': 0.1, 'maxTokens': 100}
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        return result['output']['message']['content'][0]['text']
    else:
        raise Exception(f"Bedrock API error: {response.status_code} - {response.text}")


def call_llm_litellm(prompt: str) -> str:
    """Call LiteLLM or OpenAI-compatible API."""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {MODEL_API_KEY}'
    }
    
    payload = {
        'model': MODEL_NAME,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
        'max_tokens': 100
    }
    
    response = requests.post(
        f"{MODEL_BASE_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    
    if response.status_code == 200:
        result = response.json()
        return result['choices'][0]['message']['content']
    else:
        raise Exception(f"LLM API error: {response.status_code} - {response.text}")


def call_llm(prompt: str) -> str:
    """Call LLM API."""
    if API_PROVIDER.lower() == 'bedrock':
        return call_llm_bedrock(prompt)
    else:
        return call_llm_litellm(prompt)


def match_policy_names(summary_name: str, report_name: str) -> bool:
    """
    Use LLM to determine if two policy names refer to the same policy.
    
    Returns True if they match, False otherwise.
    """
    prompt = f"""Compare these two policy names and determine if they refer to the same policy.

Policy Name 1 (from summary): {summary_name}
Policy Name 2 (from report): {report_name}

Consider:
- Minor wording differences (e.g., "S3 Bucket" vs "Bucket")
- Presence/absence of "Policy" suffix
- Different word orders that mean the same thing

Respond with ONLY "YES" if they refer to the same policy, or "NO" if they are different policies.
Do not include any explanation."""

    try:
        response = call_llm(prompt).strip().upper()
        return response.startswith('YES')
    except Exception as e:
        print(f"Error calling LLM: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: llm_match_policy.py <summary_name> <report_name>", file=sys.stderr)
        sys.exit(1)
    
    summary_name = sys.argv[1]
    report_name = sys.argv[2]
    
    if match_policy_names(summary_name, report_name):
        print("MATCH")
        sys.exit(0)
    else:
        print("NO_MATCH")
        sys.exit(1)