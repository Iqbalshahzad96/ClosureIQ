"""
Shared LLM Helpers for RAG and Agents.
Supports Grok 4.6 (xAI) as primary model with automatic Gemini (Google) fallback.
"""

import json
import logging
from typing import Any, List, Optional, Type
import httpx
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("closureiq.llm")


async def generate_grok_content(
    system_instruction: str,
    user_content: str,
    response_schema: Optional[Any] = None,
    temperature: float = 0.1,
    model_name: Optional[str] = None,
) -> str:
    """Generate structured or unstructured content using xAI Grok API."""
    api_key = settings.GROK_API_KEY
    if not api_key:
        raise ValueError("Grok (xAI) API key is not configured")

    base_url = (settings.GROK_BASE_URL or "https://api.x.ai/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    model = model_name or settings.GROK_MODEL or "grok-4.6"

    # If response schema is provided, instruct JSON formatting
    enhanced_system = system_instruction
    if response_schema is not None:
        if isinstance(response_schema, type) and issubclass(response_schema, BaseModel):
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            enhanced_system += f"\n\nYou MUST return valid JSON matching this schema:\n{schema_json}"

    messages = [
        {"role": "system", "content": enhanced_system},
        {"role": "user", "content": user_content},
    ]

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    if response_schema is not None:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Grok API error {response.status_code}: {response.text}")
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Grok API returned empty choices: {data}")
        return choices[0].get("message", {}).get("content", "") or ""


async def generate_gemini_raw_content(
    system_instruction: str,
    user_content: str,
    response_schema: Optional[Any] = None,
    response_mime_type: Optional[str] = None,
    temperature: float = 0.1,
    model_name: Optional[str] = None,
) -> str:
    """Generate content using Gemini API."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError("Gemini API key is not configured")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ImportError("google-genai SDK is missing") from exc

    client = genai.Client(api_key=api_key)

    config_kwargs = {
        "system_instruction": system_instruction,
        "temperature": temperature,
    }
    if response_schema:
        config_kwargs["response_schema"] = response_schema
    if response_mime_type:
        config_kwargs["response_mime_type"] = response_mime_type

    config = types.GenerateContentConfig(**config_kwargs)
    model = model_name or settings.GEMINI_MODEL or "gemini-3.5-flash-lite"

    response = await client.aio.models.generate_content(
        model=model,
        contents=user_content,
        config=config,
    )
    return response.text or ""


async def generate_gemini_content(
    system_instruction: str,
    user_content: str,
    response_schema: Optional[Any] = None,
    response_mime_type: Optional[str] = None,
    temperature: float = 0.1,
    model_name: Optional[str] = None,
) -> str:
    """
    Primary LLM entrypoint:
    Attempts generation with Grok 4.6 first (if GROK_API_KEY is configured).
    Automatically falls back to Gemini as backup if Grok fails or is unconfigured.
    """
    primary_provider = (settings.PRIMARY_LLM_PROVIDER or "grok").lower()

    if primary_provider == "grok" and settings.GROK_API_KEY:
        try:
            return await generate_grok_content(
                system_instruction=system_instruction,
                user_content=user_content,
                response_schema=response_schema,
                temperature=temperature,
                model_name=model_name if (model_name and "grok" in model_name.lower()) else settings.GROK_MODEL,
            )
        except Exception as grok_err:
            logger.warning(
                "Primary Grok generation failed: %s. Falling back to Gemini backup...",
                grok_err,
            )

    # Fallback to Gemini
    return await generate_gemini_raw_content(
        system_instruction=system_instruction,
        user_content=user_content,
        response_schema=response_schema,
        response_mime_type=response_mime_type,
        temperature=temperature,
        model_name=model_name if (model_name and "gemini" in model_name.lower()) else settings.GEMINI_MODEL,
    )


def format_chat_history(history: List[Any]) -> str:
    """Format chat history for the prompt."""
    history_lines = []
    for item in history:
        if isinstance(item, dict):
            role = "Assistant" if item.get("role") == "assistant" else "User"
            content = item.get("content", "").strip()
        else:
            role = "Assistant" if getattr(item, "role", "") == "assistant" else "User"
            content = getattr(item, "content", "").strip()
        if content:
            history_lines.append(f"{role}: {content}")
    return chr(10).join(history_lines) if history_lines else "No prior messages."
