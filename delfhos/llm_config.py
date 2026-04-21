"""
LLMConfig — flexible LLM provider configuration for Delfhos agents.

Allows using any OpenAI-compatible endpoint: local models, enterprise servers,
open-source models via Ollama/vLLM/LM Studio, or any custom API.

Usage examples::

    from delfhos import Agent, LLMConfig

    # Local Ollama model
    agent = Agent(
        tools=[...],
        llm=LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")
    )

    # Enterprise server running vLLM
    agent = Agent(
        tools=[...],
        llm=LLMConfig(
            model="mistral-7b-instruct",
            base_url="https://llm.corp.internal/v1",
            api_key="my-enterprise-token"
        )
    )

    # Enterprise server with multiple required auth headers
    agent = Agent(
        tools=[...],
        llm=LLMConfig(
            model="llama-3-70b",
            base_url="https://llm.corp.internal/v1",
            headers={
                "X-Tenant-ID": "acme-prod",
                "X-User-Token": "tok_abc123",
                "X-Request-Source": "delfhos",
            }
        )
    )

    # Any OpenAI-compatible provider (Together AI, Groq, Anyscale, etc.)
    agent = Agent(
        tools=[...],
        llm=LLMConfig(model="meta-llama/Llama-3-70b-chat-hf", base_url="https://api.together.xyz/v1", api_key="...")
    )

    # Mix: fast local model for prefilter, strong cloud model for generation
    agent = Agent(
        tools=[...],
        light_llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1"),
        heavy_llm="gemini-2.5-flash",
    )
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


_SETTING_ALIASES = {
    "top-k": "top_k",
    "top_p": "top_p",
    "top-p": "top_p",
    "max-tokens": "max_tokens",
    "max_output_tokens": "max_tokens",
    "max-output-tokens": "max_tokens",
    "max_completion_tokens": "max_tokens",
    "max-completion-tokens": "max_tokens",
    "presence-penalty": "presence_penalty",
    "frequency-penalty": "frequency_penalty",
}

_SUPPORTED_SETTINGS = {
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
    "stop",
}

_SUPPORTED_PROVIDERS = {"auto", "google", "openai", "anthropic"}


def _normalize_setting_key(key: str) -> str:
    normalized = key.strip().lower().replace("-", "_")
    normalized = _SETTING_ALIASES.get(normalized, normalized)
    return normalized


def _normalize_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not settings:
        return {}

    normalized_settings: Dict[str, Any] = {}
    for raw_key, raw_value in settings.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("LLMConfig.settings keys must be non-empty strings")

        key = _normalize_setting_key(raw_key)
        if key not in _SUPPORTED_SETTINGS:
            supported = ", ".join(sorted(_SUPPORTED_SETTINGS))
            raise ValueError(
                f"Unsupported llm setting '{raw_key}'. Supported keys: {supported}"
            )

        if raw_value is None:
            continue

        if key in {"temperature", "top_p", "presence_penalty", "frequency_penalty"}:
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ValueError(f"LLM setting '{key}' must be a number")
            value = float(raw_value)
        elif key in {"top_k", "max_tokens"}:
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError(f"LLM setting '{key}' must be an integer")
            if raw_value <= 0:
                raise ValueError(f"LLM setting '{key}' must be > 0")
            value = raw_value
        elif key == "stop":
            if isinstance(raw_value, str):
                value = raw_value
            elif isinstance(raw_value, (list, tuple)) and all(isinstance(x, str) for x in raw_value):
                value = list(raw_value)
            else:
                raise ValueError("LLM setting 'stop' must be a string or list[str]")
        else:
            value = raw_value

        normalized_settings[key] = value

    return normalized_settings


@dataclass
class LLMConfig:
    """
    Flexible LLM configuration for any OpenAI-compatible endpoint.

    Use this when you want to go beyond the built-in providers (Google, OpenAI,
    Anthropic) — for example a local Ollama instance, a vLLM enterprise server,
    or any third-party that exposes an OpenAI-compatible /v1/chat/completions API.

    Args:
        model:    Model name as the endpoint expects it (e.g. "llama3.2", "mistral-7b-instruct").
        base_url: Base URL of the OpenAI-compatible API (e.g. "http://localhost:11434/v1").
                  Defaults to OPENAI_BASE_URL env var, then "https://api.openai.com/v1".
        api_key:  API key / bearer token. Defaults to OPENAI_API_KEY env var.
                  For local models that don't require auth, pass api_key="local" or omit it.
        headers:  Extra HTTP headers sent with every request. Use this for enterprise servers
                  that require tenant IDs, session tokens, or other custom auth headers in
                  addition to (or instead of) a bearer token.
                  Example: {"X-Tenant-ID": "acme", "X-User-Token": "tok_abc123"}
        settings: Optional generation settings applied to this model everywhere it is used.
              Supported keys: temperature, top_p, top_k, max_tokens,
              presence_penalty, frequency_penalty, stop.
              Aliases like "top-k" and "max-tokens" are accepted.
        provider: Provider routing mode: "auto", "google", "openai", "anthropic".
              - "auto" (default): infer from model name when base_url is not set.
              - if base_url is set, requests use OpenAI-compatible protocol.

    Examples::

        # Ollama running locally
        LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")

        # LM Studio (also exposes OpenAI-compatible API)
        LLMConfig(model="lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
                  base_url="http://localhost:1234/v1")

        # Groq (cloud, OpenAI-compatible)
        LLMConfig(model="llama-3.3-70b-versatile",
                  base_url="https://api.groq.com/openai/v1",
                  api_key="gsk_...")

        # vLLM enterprise server with multiple auth headers
        LLMConfig(model="llama-3-70b",
                  base_url="https://llm.corp.internal/v1",
                  headers={
                      "X-Tenant-ID": "acme-prod",
                      "X-User-Token": "tok_abc123",
                      "X-Request-Source": "delfhos",
                  })
    """

    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    settings: Optional[Dict[str, Any]] = None
    provider: str = field(default="auto")

    def __post_init__(self):
        if not self.model or not self.model.strip():
            raise ValueError("LLMConfig.model must be a non-empty string")
        self.model = self.model.strip()
        self.provider = (self.provider or "auto").strip().lower()
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        self.settings = _normalize_settings(self.settings)
        if self.provider not in _SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(_SUPPORTED_PROVIDERS))
            raise ValueError(
                f"LLMConfig provider '{self.provider}' is not supported. "
                f"Supported providers: {supported}."
            )

    def with_settings(self, **settings: Any) -> "LLMConfig":
        """Return self after merging pythonic generation settings.

        Example:
            cfg = LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")
            cfg.with_settings(temperature=0.2, top_k=40, max_tokens=1200)
        """
        merged = dict(self.settings or {})
        merged.update(settings)
        self.settings = _normalize_settings(merged)
        return self

    def __repr__(self) -> str:
        parts = [f"model={self.model!r}"]
        if self.base_url:
            parts.append(f"base_url={self.base_url!r}")
        if self.api_key:
            parts.append("api_key='***'")
        if self.headers:
            masked = {k: "***" for k in self.headers}
            parts.append(f"headers={masked!r}")
        if self.provider != "auto":
            parts.append(f"provider={self.provider!r}")
        if self.settings:
            parts.append(f"settings={self.settings!r}")
        return f"LLMConfig({', '.join(parts)})"
