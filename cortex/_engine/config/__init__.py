"""Configuration module for Hierarchical LLM Router"""

from .env_loader import get_api_key, require_api_key, get_env_loader
from typing import Dict, Optional

# Global API key cache
_api_key_cache = {}
_SERVICE_ALIASES = {
    "gemini": "google",
    "google": "google",
    "openai": "openai",
    "anthropic": "anthropic",
}


def _normalize_service(service: str) -> str:
    return _SERVICE_ALIASES.get((service or "").strip().lower(), (service or "").strip().lower())


def configure_api_keys(providers: Optional[Dict[str, str]] = None):
    """Load and cache provider API keys.

    If `providers` is provided, those keys are used as the primary source.
    Missing providers are then auto-discovered from `.env` / process environment.
    """
    global _api_key_cache
    _api_key_cache = {}

    if providers:
        for provider, key in providers.items():
            if not provider or not key:
                continue
            _api_key_cache[_normalize_service(provider)] = key

    loader = get_env_loader()
    for service in ["google", "openai", "anthropic"]:
        if service in _api_key_cache:
            continue
        try:
            if key := loader.get_api_key(service):
                _api_key_cache[service] = key
        except Exception:
            continue  # If key not found, continue
    
    # Use console only if it's already imported somewhere, otherwise fallback to print
    try:
        from ..utils.console import console
        console.system("API keys loaded", f"{', '.join(_api_key_cache.keys())}")
    except ImportError:
        print(f"✅ API keys loaded for: {list(_api_key_cache.keys())}")

def get_cached_api_key(service: str) -> str:
    """Get cached API key for a service."""
    normalized = _normalize_service(service)
    if normalized in _api_key_cache:
        return _api_key_cache[normalized]

    # Lazy fallback: if key appears later in env, capture it in cache.
    if key := get_api_key(normalized):
        _api_key_cache[normalized] = key
        return key

    return require_api_key(normalized)

__all__ = ['get_api_key', 'require_api_key', 'get_env_loader', 'configure_api_keys', 'get_cached_api_key']
