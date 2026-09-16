"""
Shared LLM Helpers for RAG and Agents.
"""

import json
from typing import Any, List, Optional, Type
from pydantic import BaseModel

from app.config import settings

async def generate_gemini_content(
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
    model = model_name or settings.GEMINI_MODEL

    response = await client.aio.models.generate_content(
        model=model,
        contents=user_content,
        config=config,
    )
    return response.text or ""

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
