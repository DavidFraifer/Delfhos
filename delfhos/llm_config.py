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
from typing import Dict, Optional


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
        provider: Underlying protocol to use. Currently only "openai" (OpenAI-compatible)
                  is supported for custom endpoints. Defaults to "openai".

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
    provider: str = field(default="openai")

    def __post_init__(self):
        if not self.model or not self.model.strip():
            raise ValueError("LLMConfig.model must be a non-empty string")
        self.model = self.model.strip()
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")
        if self.provider != "openai":
            raise ValueError(
                f"LLMConfig provider '{self.provider}' is not supported. "
                "Only 'openai' (OpenAI-compatible) is supported for custom endpoints. "
                "For Google/Anthropic, pass the model name as a string instead."
            )

    def __repr__(self) -> str:
        parts = [f"model={self.model!r}"]
        if self.base_url:
            parts.append(f"base_url={self.base_url!r}")
        if self.api_key:
            parts.append("api_key='***'")
        if self.headers:
            masked = {k: "***" for k in self.headers}
            parts.append(f"headers={masked!r}")
        return f"LLMConfig({', '.join(parts)})"
