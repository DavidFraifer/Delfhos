import pytest

from delfhos.llm_config import LLMConfig
from cortex._engine.internal.llm import resolve_model, _resolve_generation_settings


def test_llm_config_normalizes_aliases():
    cfg = LLMConfig(
        model="llama3.2",
        base_url="http://localhost:11434/v1",
        settings={
            "temperature": 0.2,
            "top-k": 40,
            "max-tokens": 1200,
            "stop": ["END"],
        },
    )

    assert cfg.settings["temperature"] == 0.2
    assert cfg.settings["top_k"] == 40
    assert cfg.settings["max_tokens"] == 1200
    assert cfg.settings["stop"] == ["END"]


def test_llm_config_with_settings_is_pythonic():
    cfg = LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")

    returned = cfg.with_settings(temperature=0.1, top_k=32, max_tokens=900)

    assert returned is cfg
    assert cfg.settings == {
        "temperature": 0.1,
        "top_k": 32,
        "max_tokens": 900,
    }


def test_resolve_model_exposes_settings():
    cfg = LLMConfig(
        model="llama3.2",
        base_url="http://localhost:11434/v1",
        settings={"top_k": 25, "temperature": 0.3},
    )

    provider, model_id, base_url, api_key, headers, settings = resolve_model(cfg)

    assert provider == "openai"
    assert model_id == "llama3.2"
    assert base_url == "http://localhost:11434/v1"
    assert api_key is None
    assert headers is None
    assert settings == {"top_k": 25, "temperature": 0.3}


def test_resolve_model_google_native_from_llmconfig_without_base_url():
    cfg = LLMConfig(model="gemini-2.5-flash", settings={"temperature": 0.8})

    provider, model_id, base_url, api_key, headers, settings = resolve_model(cfg)

    assert provider == "google"
    assert model_id == "gemini-2.5-flash"
    assert base_url is None
    assert api_key is None
    assert headers is None
    assert settings["temperature"] == 0.8


def test_resolve_model_openai_native_from_llmconfig_without_base_url():
    cfg = LLMConfig(model="gpt-4o", settings={"temperature": 0.3})

    provider, model_id, base_url, api_key, headers, settings = resolve_model(cfg)

    assert provider == "openai"
    assert model_id == "gpt-4o"
    assert base_url is None
    assert settings["temperature"] == 0.3


def test_resolve_model_anthropic_native_from_llmconfig_without_base_url():
    cfg = LLMConfig(model="claude-3-5-sonnet", settings={"temperature": 0.1})

    provider, model_id, base_url, api_key, headers, settings = resolve_model(cfg)

    assert provider == "anthropic"
    assert model_id == "claude-3-5-sonnet"
    assert base_url is None
    assert settings["temperature"] == 0.1


def test_resolve_model_keeps_custom_openai_compatible_when_base_url_present():
    cfg = LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1", settings={"temperature": 0.2})

    provider, model_id, base_url, api_key, headers, settings = resolve_model(cfg)

    assert provider == "openai"
    assert model_id == "llama3.2"
    assert base_url == "http://localhost:11434/v1"
    assert settings["temperature"] == 0.2


def test_resolve_generation_settings_applies_overrides():
    temp, max_tokens, optional = _resolve_generation_settings(
        settings={
            "temperature": 0.8,
            "max_tokens": 2048,
            "top_k": 50,
            "top_p": 0.95,
        },
        temperature=0.0,
        max_tokens=100,
    )

    assert temp == 0.8
    assert max_tokens == 2048
    assert optional == {"top_k": 50, "top_p": 0.95}


def test_llm_config_rejects_unknown_setting_key():
    with pytest.raises(ValueError):
        LLMConfig(
            model="llama3.2",
            base_url="http://localhost:11434/v1",
            settings={"foo": "bar"},
        )
