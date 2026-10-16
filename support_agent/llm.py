"""
llm.py - the model client.

Isolated in its own module so that:
  - swapping provider (DeepSeek -> OpenAI -> a fake for tests) touches one file
  - tests can replace `llm.client` without importing the API key machinery
"""

import os

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from . import config

load_dotenv()   # finds the project's .env by searching upward from this file

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=config.API_BASE_URL,
    # Jio/NAT64 fix: bind the local socket to IPv4 so DNS64 addresses can't hang the call.
    http_client=httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0")),
    timeout=config.API_TIMEOUT_SECONDS,
    max_retries=config.API_MAX_RETRIES,
)
