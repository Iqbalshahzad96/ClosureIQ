"""
Configuration regression tests for Gemini default/example configuration.
Ensures gemini-3.1-flash-lite is the default model, configurable via env, and no secrets in .env.example.
"""

import os
from unittest.mock import patch
from pathlib import Path
import pytest

from app.config import Settings


def test_gemini_model_default_is_gemini_3_1_flash_lite():
    """Default model must be gemini-3.1-flash-lite when GEMINI_MODEL env var is absent."""
    with patch.dict(os.environ, {}, clear=False):
        if "GEMINI_MODEL" in os.environ:
            del os.environ["GEMINI_MODEL"]
        cfg = Settings()
        assert cfg.GEMINI_MODEL == "gemini-3.1-flash-lite", (
            f"Expected default 'gemini-3.1-flash-lite', got '{cfg.GEMINI_MODEL}'"
        )


def test_gemini_model_is_configurable_via_env():
    """GEMINI_MODEL must be configurable through environment variables."""
    with patch.dict(os.environ, {"GEMINI_MODEL": "custom-model-test"}):
        cfg = Settings()
        assert cfg.GEMINI_MODEL == "custom-model-test"


def test_env_example_contains_safe_placeholders_only():
    """backend/.env.example must have safe placeholder and default to gemini-3.1-flash-lite."""
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    assert env_example_path.exists(), ".env.example must exist"
    content = env_example_path.read_text(encoding="utf-8")

    assert "GEMINI_API_KEY=your_real_key_here" in content
    assert "GEMINI_MODEL=gemini-3.1-flash-lite" in content
    assert "gemini-2.5-flash" not in content
