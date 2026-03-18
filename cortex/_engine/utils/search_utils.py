"""
Search Model Validation Utilities

Provides validation for models that support web search capability.
Currently Gemini and OpenAI models support web search.
Claude models do not support web search.
"""

from typing import Optional
from delfhos.errors import ToolDefinitionError


# Models that support web search
SEARCH_SUPPORTED_MODELS = {
    "gemini": ["gemini-3.1-flash-lite-preview", "gemini-3.1-flash", "gemini-3.1-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash"],
    "gpt": ["gpt-5", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"],  # OpenAI models
}

# Models that explicitly do NOT support web search
SEARCH_UNSUPPORTED_MODELS = {
    "claude": "Claude models do not support web search. Use Gemini or OpenAI/GPT models instead."
}


def validate_search_model(model: Optional[str]) -> bool:
    """
    Validate whether a model supports web search capability.
    
    Args:
        model: The model identifier (e.g., "gemini-3.1-flash-lite-preview", "gpt-4", "claude-3-opus")
    
    Returns:
        True if model supports web search, False otherwise
    
    Raises:
        ToolDefinitionError: If model is None or invalid
    """
    if not model or not isinstance(model, str):
        raise ToolDefinitionError(detail="Search model must be a non-empty string")
    
    model_lower = model.lower().strip()
    
    # Check if model starts with any supported provider
    for provider, models in SEARCH_SUPPORTED_MODELS.items():
        if any(model_lower.startswith(p) for p in models):
            return True
    
    return False


def get_search_support_error_message(model: str) -> str:
    """
    Generate a helpful error message for unsupported search models.
    
    Args:
        model: The model identifier that doesn't support search
    
    Returns:
        A formatted error message with suggestions
    """
    model_lower = model.lower().strip()
    
    # Check if it's a known unsupported provider
    for unsupported_prefix, reason in SEARCH_UNSUPPORTED_MODELS.items():
        if model_lower.startswith(unsupported_prefix):
            return f"Model '{model}' does not support web search.\n{reason}"
    
    # Generic message for unknown models
    supported_models = []
    for models in SEARCH_SUPPORTED_MODELS.values():
        supported_models.extend(models)
    
    supported_list = "\n  - ".join(supported_models[:10])  # Show first 10 as examples
    
    return (
        f"Model '{model}' does not support web search.\n"
        f"Supported models include:\n  - {supported_list}\n\n"
        f"To use web search, initialize WebSearch with a supported model:\n"
        f"  # Gemini\n"
        f"  agent = Agent(\n"
        f"    tools=[WebSearch(llm='gemini-3.1-flash-lite-preview')],\n"
        f"    ...\n"
        f"  )\n"
        f"  # OpenAI\n"
        f"  agent = Agent(\n"
        f"    tools=[WebSearch(llm='gpt-4')],\n"
        f"    ...\n"
        f"  )"
    )
