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

import json
import os
from typing import Type, TypeVar

from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from src.db import log_llm_call

load_dotenv()

T = TypeVar("T", bound=BaseModel)

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


class LLMOutputError(Exception):
    """
    Raised when the LLM's output cannot be parsed/validated into the
    expected structured schema.

    Callers (e.g. the Planner Agent) should catch this and treat it as
    a failed proposal - NEVER attempt to "fix up" or guess at invalid
    output. The Guardrail layer downstream should log this as a rejection.
    """
    pass


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


def ask_llm_structured(
    prompt: str,
    response_model: Type[T],
    system_prompt: str | None = None,
    provider: str | None = None,
    temperature: float = 0.2,
) -> T:
    """
    Send a prompt and validate the LLM's response against a Pydantic model.

    Best-effort strategy (works across providers/models with varying
    structured-output support):
      1. Ask the model for JSON matching response_model's schema via the
         OpenAI-compatible `response_format` parameter. Some providers/
         endpoints may ignore this - that's fine, see step 2.
      2. Regardless of whether response_format was honored, parse the
         returned text as JSON and validate it against response_model.
      3. If parsing or validation fails, raise LLMOutputError instead of
         silently returning something invalid or crashing with a raw
         JSONDecodeError/ValidationError. This makes failure modes explicit
         and catchable by calling agents.

    This function NEVER makes a safety/business decision about the parsed
    data - it only guarantees the data CAN be trusted to have the right
    shape. Rule validation still belongs to the Guardrail layer.
    """
    resolved_provider = provider or os.getenv("LLM_PROVIDER", "deepseek")
    client, model = _get_client_and_model(resolved_provider)

    schema = response_model.model_json_schema()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    # Reinforce the schema in-prompt too, since not all providers honor
    # response_format strictly - this is a defense-in-depth measure.
    messages.append({
        "role": "user",
        "content": (
            f"{prompt}\n\n"
            f"Respond with ONLY a single JSON object matching this schema "
            f"(no markdown fences, no extra text):\n{json.dumps(schema)}"
        ),
    })

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        )
    except Exception:
        # Some providers/models reject the response_format parameter
        # outright rather than ignoring it. Retry once without it.
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )

    raw_content = response.choices[0].message.content

    # Log token usage for cost tracking (never let logging failures crash
    # the pipeline - log_llm_call already swallows its own exceptions).
    if response.usage:
        log_llm_call(
            provider=resolved_provider,
            model=model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    # Defensive cleanup: strip markdown code fences if the model added them
    # despite instructions not to.
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed_json = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMOutputError(
            f"LLM output was not valid JSON: {e}\nRaw output: {raw_content!r}"
        ) from e

    try:
        return response_model.model_validate(parsed_json)
    except ValidationError as e:
        raise LLMOutputError(
            f"LLM output did not match {response_model.__name__} schema: {e}\n"
            f"Parsed JSON: {parsed_json!r}"
        ) from e
