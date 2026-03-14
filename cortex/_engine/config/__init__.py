"""Configuration module for Hierarchical LLM Router"""

from .env_loader import get_api_key, require_api_key, get_env_loader

# Global API key cache
_api_key_cache = {}

def configure_api_keys():
    """Load and cache all API keys at startup to avoid repeated loading."""
    global _api_key_cache
    loader = get_env_loader()
    
    # Try to load common API keys
    for service in ['gemini']:
        try:
            if key := loader.get_api_key(service):
                _api_key_cache[service] = key
        except Exception:
            continue  # If key not found, continue
    
    # Use console only if it's already imported somewhere, otherwise fallback to print
    try:
        from ..utils.console import console
        console.system("API Configuration", f"Loaded keys for: {', '.join(_api_key_cache.keys())}")
    except ImportError:
        print(f"✅ API keys loaded for: {list(_api_key_cache.keys())}")

def get_cached_api_key(service: str) -> str:
    """Get cached API key for a service."""
    return _api_key_cache.get(service) or require_api_key(service)

__all__ = ['get_api_key', 'require_api_key', 'get_env_loader', 'configure_api_keys', 'get_cached_api_key']
