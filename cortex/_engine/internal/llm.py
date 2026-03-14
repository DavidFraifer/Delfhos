from google import genai
from google.genai import types
from ..utils import report_error, raise_error
from datetime import datetime, timezone
import asyncio
import base64
import os
import requests
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Increase default thread pool for asyncio.to_thread() calls.
# The default (min(32, os.cpu_count()+4)) can bottleneck parallel LLM calls
# (e.g., 10 emails analyzed concurrently via asyncio.gather).
_llm_thread_pool = ThreadPoolExecutor(max_workers=20)


def _get_api_key(model: str) -> str:
    from ..config import get_cached_api_key
    if model.startswith("gemini"):
        return get_cached_api_key('gemini')
    elif model.startswith("mercury"):
        key = os.getenv("INCEPTION_AI")
        if not key:
            raise_error("LLM-001", context={"model": model, "error": "INCEPTION_AI env var not set"})
        return key
    else:
        raise_error("LLM-001", context={"model": model, "supported_models": ["gemini*", "mercury*"]})


async def llm_completion_async(
    model: str,
    prompt: str,
    system_message: str = "",
    temperature: float = 0.0,
    max_tokens: int = 100,  
    response_format: str = "text",
    use_web_search: bool = False,
    images: Optional[List[Union[str, Dict[str, Any]]]] = None,
) -> tuple[str, dict]:

    current_dt = datetime.now(timezone.utc).astimezone()
    current_date_str = current_dt.strftime("%Y-%m-%d")
    current_time_str = current_dt.strftime("%H:%M:%S %Z")
    current_context = f"Current date: {current_date_str}\nCurrent time: {current_time_str}"

    if "Current date:" not in system_message and "Current date:" not in prompt:
        if system_message:
            system_message = f"{system_message}\n\n{current_context}"
        else:
            prompt = f"{current_context}\n\n{prompt}"

    api_key = _get_api_key(model)

    if model.startswith("gemini"):
        # Run Gemini in dedicated thread pool for better parallelism
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _llm_thread_pool,
            _gemini_sync,
            model,
            prompt,
            system_message,
            temperature,
            max_tokens,
            response_format,
            api_key,
            use_web_search,
            images,
        )

    elif model.startswith("mercury"):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _llm_thread_pool,
            _mercury_sync,
            model,
            prompt,
            system_message,
            temperature,
            max_tokens,
            api_key,
        )

    else:
        raise_error("LLM-001", context={"model": model, "supported_models": ["gemini*", "mercury*"], "function": "llm_completion_async"})


# --- Client Caching -------------------------------------------------------------
_genai_clients: Dict[str, genai.Client] = {}

def get_gemini_client(api_key: str) -> genai.Client:
    """Gets or creates a cached Gemini client for the given API key."""
    if api_key not in _genai_clients:
        _genai_clients[api_key] = genai.Client(api_key=api_key)
    return _genai_clients[api_key]


def _prepare_gemini_image_parts(images: List[Union[str, Dict[str, Any]]]) -> List[types.Part]:
    """Helper to decode and prepare image parts for Gemini payload."""
    image_parts = []
    for img in images:
        if isinstance(img, dict):
            # Format: {"type": "image", "data": base64_string, "mime_type": "image/jpeg"}
            img_data = img.get("data", "")
            mime_type = img.get("mime_type", "image/jpeg")
            if img_data:
                try:
                    # Decode base64 to bytes
                    img_bytes = base64.b64decode(img_data)
                    # Create Part from bytes
                    image_parts.append(types.Part.from_bytes(
                        data=img_bytes,
                        mime_type=mime_type
                    ))
                except Exception as e:
                    print(f"Warning: Failed to decode image for Gemini: {e}")
        elif isinstance(img, str):
            # Assume it's base64 encoded string
            try:
                # Remove data URI prefix if present
                if img.startswith("data:"):
                    # Extract mime type and base64 data
                    header, encoded = img.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                    img_bytes = base64.b64decode(encoded)
                else:
                    # Assume PNG if no prefix
                    img_bytes = base64.b64decode(img)
                    mime_type = "image/png"
                
                image_parts.append(types.Part.from_bytes(
                    data=img_bytes,
                    mime_type=mime_type
                ))
            except Exception as e:
                print(f"Warning: Failed to decode image string for Gemini: {e}")
    return image_parts

def _extract_gemini_tokens(response, prompt: str, system_message: str, content: str, images: Optional[List[Any]]) -> dict:
    """Helper to extract token usage from Gemini response, with fallback to estimation."""
    try:
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count
        else:
            # Fallback to estimate if metadata is missing (saves network calls)
            total_input = prompt + (system_message or "")
            input_tokens = len(total_input) // 4
            output_tokens = len(content) // 4
            
        token_info = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "image_count": len(images) if images else 0,
        }
    except Exception as e:
        print(f"Warning: Could not extract tokens for Gemini: {e}")
        total_input = prompt + (system_message or "")
        estimated_total = len(total_input + content) // 4
        token_info = {
            "input_tokens": len(total_input) // 4,
            "output_tokens": len(content) // 4,
            "total_tokens": estimated_total,
            "image_count": len(images) if images else 0,
        }
    return token_info

def _gemini_sync(model: str, prompt: str, system_message: str, temperature: float, max_tokens: int, response_format: str, api_key: str, use_web_search: bool, images: Optional[List[Union[str, Dict[str, Any]]]] = None) -> tuple[str, dict]:
    client = get_gemini_client(api_key)
    full_prompt = f"{system_message}\n\n{prompt}" if system_message else prompt
    
    # Build content parts - support text and images
    parts = [types.Part.from_text(text=full_prompt)]
    
    # Add images if provided
    if images:
        parts.extend(_prepare_gemini_image_parts(images))
    
    content_for_tokens = [types.Content(role="user", parts=parts)]
    
    config_params = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "top_p": 0.6,  # Further reduced for faster generation
        "top_k": 20    # Further reduced for faster generation
    }
    if response_format == "json":
        config_params["response_mime_type"] = "application/json"
    
    if model.startswith("gemini-2.5"):
        config_params["thinking_config"] = types.ThinkingConfig(
            thinking_budget=0,
        )
    if use_web_search:
        config_params["tools"] = [
            types.Tool(
                google_search=types.GoogleSearch()
            )
        ]
    
    response = client.models.generate_content(
        model=model,
        contents=content_for_tokens,
        config=types.GenerateContentConfig(**config_params)
    )
    
    # Provide robust manual extraction of text from parts, as google-genai 0.x sometimes fails
    # with "list object has no attribute strip" when thought_signature is present.
    content = ""
    try:
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = []
            for part in response.candidates[0].content.parts:
                if getattr(part, 'text', None):
                    text_parts.append(part.text)
            content = "".join(text_parts).strip()
        else:
            raw_text = getattr(response, 'text', "")
            if isinstance(raw_text, list):
                content = "".join(str(x) for x in raw_text).strip()
            elif not isinstance(raw_text, str):
                content = str(raw_text).strip()
            else:
                content = raw_text.strip()
    except Exception as e:
        print(f"Warning: Manual text extraction failed: {e}")
        try:
            content = str(response.text).strip()
        except (AttributeError, TypeError, ValueError):
            pass
    
    token_info = _extract_gemini_tokens(response, prompt, system_message, content, images)
    
    return content, token_info


def _mercury_sync(model: str, prompt: str, system_message: str, temperature: float, max_tokens: int, api_key: str) -> tuple[str, dict]:
    """Call Inception Labs Mercury API (OpenAI-compatible)."""
    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})
    
    session = _get_mercury_session(api_key)
    
    response = session.post(
        "https://api.inceptionlabs.ai/v1/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 0.6,  # Narrower sampling for faster generation
        },
        timeout=30
    )
    
    if response.status_code != 200:
        raise LLMExecutionError(detail=f"Mercury API error {response.status_code}: {response.text[:200]}")
    
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})
    
    token_info = {
        "input_tokens": usage.get("prompt_tokens", len(prompt) // 4),
        "output_tokens": usage.get("completion_tokens", len(content) // 4),
        "total_tokens": usage.get("total_tokens", (len(prompt) + len(content)) // 4),
        "image_count": 0,
    }
    
    return content, token_info


# --- Mercury Session Caching (connection reuse) ---
_mercury_sessions: Dict[str, requests.Session] = {}

def _get_mercury_session(api_key: str) -> requests.Session:
    """Gets or creates a cached HTTP session for Mercury API (keeps TCP/TLS alive)."""
    if api_key not in _mercury_sessions:
        s = requests.Session()
        s.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })
        _mercury_sessions[api_key] = s
    return _mercury_sessions[api_key]