"""
LLM client for the Industrial Multi-Agent Guardian project.

Design principle (per project philosophy):
This module ONLY wraps LLM calls for planning/narration purposes.
It must NEVER be used to make safety-critical decisions directly -
those belong to the rule-based Guardrail layer (see src/guardrail.py).

Supports two providers, both OpenAI SDK-compatible:
- "deepseek"   -> optional fallback backend (not currently funded/used)
- "openrouter" -> primary backend for this project (funded, default)

Provider is selected via the LLM_PROVIDER environment variable.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# --- Provider configuration -------------------------------------------------

_PROVIDER_CONFIG = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "openrouter": {
        "api_key_env": "OPENROUTER_API_KEY",
        "base_url_env": "OPENROUTER_BASE_URL",
        "model_env": "OPENROUTER_MODEL",
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": None,  # must be set explicitly in .env, no safe default
    },
}


def _get_client_and_model(provider: str) -> tuple[OpenAI, str]:
    """Build an OpenAI-SDK client configured for the requested provider."""
    if provider not in _PROVIDER_CONFIG:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. "
            f"Valid options: {list(_PROVIDER_CONFIG.keys())}"
        )

    cfg = _PROVIDER_CONFIG[provider]

    api_key = os.getenv(cfg["api_key_env"])
    if not api_key or api_key.startswith("your_"):
        raise RuntimeError(
            f"Missing API key for provider '{provider}'. "
            f"Set {cfg['api_key_env']} in your .env file."
        )

    base_url = os.getenv(cfg["base_url_env"], cfg["default_base_url"])
    model = os.getenv(cfg["model_env"], cfg["default_model"])
    if not model:
        raise RuntimeError(
            f"No model configured for provider '{provider}'. "
            f"Set {cfg['model_env']} in your .env file."
        )

    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


def ask_llm(
    prompt: str,
    system_prompt: str | None = None,
    provider: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    Send a prompt to the configured LLM provider and return the text response.

    Args:
        prompt: The user-facing prompt/content to send.
        system_prompt: Optional system message (e.g. agent role instructions).
        provider: Override the provider for this single call
                  ("deepseek" or "openrouter"). Defaults to LLM_PROVIDER env var,
                  falling back to "deepseek" if unset.
        temperature: Sampling temperature. Kept low by default since this
                     client is used for planning/narration, not creative tasks.

    Returns:
        The model's text response as a string.

    Note:
        This function must only be used for planning/narration/explanation.
        Any accept/reject decision about machine allocation, scheduling, or
        resource limits must go through the rule-based Guardrail layer,
        never through this function's output directly.
    """
    resolved_provider = provider or os.getenv("LLM_PROVIDER", "deepseek")
    client, model = _get_client_and_model(resolved_provider)

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )

    return response.choices[0].message.content
