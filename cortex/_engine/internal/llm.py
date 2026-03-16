from google import genai
from google.genai import types
from ..utils import report_error, raise_error
from datetime import datetime, timezone
import asyncio
import base64
import os
import requests
from typing import List, Dict, Any, Optional, Union, Tuple
from concurrent.futures import ThreadPoolExecutor
from delfhos.errors import LLMExecutionError

# Increase default thread pool for asyncio.to_thread() calls.
# The default (min(32, os.cpu_count()+4)) can bottleneck parallel LLM calls
# (e.g., 10 emails analyzed concurrently via asyncio.gather).
_llm_thread_pool = ThreadPoolExecutor(max_workers=20)


PROVIDER_ALIASES = {
    "google": "google",
    "gemini": "google",
    "openai": "openai",
    "anthropic": "anthropic",
    "inception": "inception",
}


def resolve_model(model: str) -> Tuple[str, str]:
    """Resolve provider and provider-native model id from a user model string.

    Supported forms:
      - Plain model id: gemini-2.5-flash, gpt-4.1, claude-3-7-sonnet
      - Provider-prefixed: google/gemini-2.5-flash, openai:gpt-4.1
    """
    if not model or not isinstance(model, str):
        raise_error("LLM-001", context={"model": model, "error": "Model identifier must be a non-empty string"})

    model_text = model.strip()
    lowered = model_text.lower()

    for sep in ("/", ":"):
        if sep in model_text:
            maybe_provider, maybe_model = model_text.split(sep, 1)
            provider = PROVIDER_ALIASES.get(maybe_provider.strip().lower())
            if provider and maybe_model.strip():
                return provider, maybe_model.strip()

    if lowered.startswith("gemini"):
        return "google", model_text
    if lowered.startswith("claude"):
        return "anthropic", model_text
    if lowered.startswith(("gpt", "o1", "o3", "o4", "chatgpt")) or "gpt-" in lowered:
        return "openai", model_text
    if lowered.startswith("mercury"):
        return "inception", model_text

    raise_error(
        "LLM-001",
        context={
            "model": model,
            "error": "Could not infer provider from model name",
            "hint": "Use google/<model>, openai/<model>, or anthropic/<model>",
        },
    )


def _get_api_key(provider: str) -> str:
    from ..config import get_cached_api_key

    if provider == "inception":
        key = os.getenv("INCEPTION_AI")
        if not key:
            raise_error("LLM-001", context={"provider": provider, "error": "INCEPTION_AI env var not set"})
        return key

    return get_cached_api_key(provider)


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

    provider, provider_model = resolve_model(model)
    api_key = _get_api_key(provider)

    if provider == "google":
        # Run Gemini in dedicated thread pool for better parallelism
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _llm_thread_pool,
            _gemini_sync,
            provider_model,
            prompt,
            system_message,
            temperature,
            max_tokens,
            response_format,
            api_key,
            use_web_search,
            images,
        )

    if provider == "openai":
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _llm_thread_pool,
            _openai_sync,
            provider_model,
            prompt,
            system_message,
            temperature,
            max_tokens,
            response_format,
            api_key,
            images,
        )

    if provider == "anthropic":
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _llm_thread_pool,
            _anthropic_sync,
            provider_model,
            prompt,
            system_message,
            temperature,
            max_tokens,
            response_format,
            api_key,
            images,
        )

    if provider == "inception":
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _llm_thread_pool,
            _mercury_sync,
            provider_model,
            prompt,
            system_message,
            temperature,
            max_tokens,
            api_key,
        )

    raise_error("LLM-001", context={"model": model, "provider": provider, "function": "llm_completion_async"})


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
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
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
    return _normalize_token_info(token_info, prompt=prompt, system_message=system_message, content=content, images=images)


def _safe_non_negative_int(value: Any, fallback: int = 0) -> int:
    try:
        if value is None:
            return max(int(fallback), 0)
        return max(int(value), 0)
    except (TypeError, ValueError):
        return max(int(fallback), 0)


def _normalize_token_info(token_info: Optional[Dict[str, Any]], prompt: str, system_message: str, content: str, images: Optional[List[Any]] = None) -> Dict[str, int]:
    """Return stable token accounting across providers.

    Guarantees:
    - input/output/total are non-negative ints
    - total is at least input + output
    - image_count is a non-negative int
    """
    info = token_info or {}
    estimated_input = len((system_message or "") + (prompt or "")) // 4
    estimated_output = len(content or "") // 4

    input_tokens = _safe_non_negative_int(info.get("input_tokens"), fallback=estimated_input)
    output_tokens = _safe_non_negative_int(info.get("output_tokens"), fallback=estimated_output)
    provided_total = _safe_non_negative_int(info.get("total_tokens"), fallback=input_tokens + output_tokens)
    image_count = _safe_non_negative_int(info.get("image_count"), fallback=len(images) if images else 0)

    total_tokens = max(provided_total, input_tokens + output_tokens)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "image_count": image_count,
    }

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
    
    base_payload = {
        "model": model,
        "messages": messages,
        "top_p": 0.6,  # Narrower sampling for faster generation
    }
    payload_variants: List[Dict[str, Any]] = [
        {"max_tokens": max_tokens, "temperature": temperature},
        {"max_completion_tokens": max_tokens, "temperature": temperature},
        {"max_tokens": max_tokens},
        {"max_completion_tokens": max_tokens},
    ]

    response = None
    last_error = None
    for variant in payload_variants:
        payload = dict(base_payload)
        payload.update(variant)
        response = session.post(
            "https://api.inceptionlabs.ai/v1/chat/completions",
            json=payload,
            timeout=30,
        )
        if response.status_code < 400:
            break

        details = _openai_error_details(response)
        msg_lower = (details.get("message") or "").lower()
        code = details.get("code")
        is_param_shape_issue = (
            code == "unsupported_parameter"
            or "unsupported parameter" in msg_lower
            or "unknown parameter" in msg_lower
            or "is not supported with this model" in msg_lower
        )
        last_error = response
        if is_param_shape_issue:
            continue
        break

    if response is None or response.status_code >= 400:
        err_response = last_error or response
        if err_response is None:
            raise LLMExecutionError(detail="Mercury API error: request failed before receiving a response")
        raise LLMExecutionError(detail=f"Mercury API error {err_response.status_code}: {err_response.text[:300]}")
    
    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise LLMExecutionError(detail="Mercury API returned no choices")
    message = choices[0].get("message", {})
    content = _openai_extract_content(message.get("content", ""))
    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    fallback_input = len((system_message or "") + prompt) // 4
    fallback_output = len(content) // 4
    
    token_info = {
        "input_tokens": prompt_tokens if isinstance(prompt_tokens, int) else fallback_input,
        "output_tokens": completion_tokens if isinstance(completion_tokens, int) else fallback_output,
        "total_tokens": total_tokens if isinstance(total_tokens, int) else (fallback_input + fallback_output),
        "image_count": 0,
    }
    
    return content, _normalize_token_info(token_info, prompt=prompt, system_message=system_message, content=content)


def _prepare_data_url(image: Union[str, Dict[str, Any]]) -> Optional[str]:
    if isinstance(image, dict):
        data = image.get("data")
        if not data:
            return None
        mime_type = image.get("mime_type", "image/png")
        return f"data:{mime_type};base64,{data}"

    if isinstance(image, str):
        if image.startswith("data:"):
            return image
        return f"data:image/png;base64,{image}"

    return None


def _openai_extract_content(message_content: Any) -> str:
    if isinstance(message_content, str):
        return message_content.strip()
    if isinstance(message_content, list):
        parts = []
        for part in message_content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "".join(parts).strip()
    return str(message_content).strip()


def _openai_error_details(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {
            "code": None,
            "param": None,
            "message": response.text[:300],
        }

    err = data.get("error", {}) if isinstance(data, dict) else {}
    if not isinstance(err, dict):
        err = {}
    return {
        "code": err.get("code"),
        "param": err.get("param"),
        "message": str(err.get("message", "")),
    }


def _anthropic_error_details(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {
            "type": None,
            "message": response.text[:300],
        }

    err = data.get("error", {}) if isinstance(data, dict) else {}
    if not isinstance(err, dict):
        err = {}
    return {
        "type": err.get("type"),
        "message": str(err.get("message", "")),
    }


def _openai_sync(
    model: str,
    prompt: str,
    system_message: str,
    temperature: float,
    max_tokens: int,
    response_format: str,
    api_key: str,
    images: Optional[List[Union[str, Dict[str, Any]]]],
) -> tuple[str, dict]:
    session = _get_openai_session(api_key)

    user_content: Union[str, List[Dict[str, Any]]] = prompt
    if images:
        user_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            data_url = _prepare_data_url(image)
            if data_url:
                user_parts.append({"type": "image_url", "image_url": {"url": data_url}})
        user_content = user_parts

    messages: List[Dict[str, Any]] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": user_content})

    base_payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if response_format == "json":
        base_payload["response_format"] = {"type": "json_object"}

    # OpenAI model families differ in accepted generation params.
    # Try modern names first, then gracefully fall back.
    payload_variants: List[Dict[str, Any]] = [
        {"max_completion_tokens": max_tokens, "temperature": temperature},
        {"max_tokens": max_tokens, "temperature": temperature},
        {"max_completion_tokens": max_tokens},
        {"max_tokens": max_tokens},
    ]

    response = None
    last_error = None
    for variant in payload_variants:
        payload = dict(base_payload)
        payload.update(variant)
        response = session.post(_get_openai_base_url() + "/chat/completions", json=payload, timeout=45)
        if response.status_code < 400:
            break

        details = _openai_error_details(response)
        msg_lower = (details.get("message") or "").lower()
        code = details.get("code")

        # Continue only for parameter-shape incompatibilities.
        is_param_shape_issue = (
            code == "unsupported_parameter"
            or "unsupported parameter" in msg_lower
            or "unknown parameter" in msg_lower
            or "is not supported with this model" in msg_lower
        )

        if is_param_shape_issue:
            last_error = response
            continue

        last_error = response
        break

    if response is None or response.status_code >= 400:
        err_response = last_error or response
        if err_response is None:
            raise LLMExecutionError(detail="OpenAI API error: request failed before receiving a response")
        raise LLMExecutionError(detail=f"OpenAI API error {err_response.status_code}: {err_response.text[:300]}")

    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise LLMExecutionError(detail="OpenAI API returned no choices")

    message = choices[0].get("message", {})
    content = _openai_extract_content(message.get("content", ""))
    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", len((system_message or "") + prompt) // 4)
    output_tokens = usage.get("completion_tokens", len(content) // 4)

    token_info = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("total_tokens", input_tokens + output_tokens),
        "image_count": len(images) if images else 0,
    }
    return content, _normalize_token_info(token_info, prompt=prompt, system_message=system_message, content=content, images=images)


def _anthropic_sync(
    model: str,
    prompt: str,
    system_message: str,
    temperature: float,
    max_tokens: int,
    response_format: str,
    api_key: str,
    images: Optional[List[Union[str, Dict[str, Any]]]],
) -> tuple[str, dict]:
    session = _get_anthropic_session(api_key)

    system_prompt = system_message or ""
    if response_format == "json":
        system_prompt = (system_prompt + "\n\nReturn only valid JSON.").strip()

    if images:
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            data_url = _prepare_data_url(image)
            if not data_url:
                continue
            header, encoded = data_url.split(",", 1)
            mime_type = header.split(";")[0].split(":", 1)[1]
            user_content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": encoded,
                    },
                }
            )
    else:
        user_content = [{"type": "text", "text": prompt}]

    base_payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_content}],
    }
    if system_prompt:
        base_payload["system"] = system_prompt

    # Some Claude variants may reject optional generation params.
    payload_variants: List[Dict[str, Any]] = [
        {"temperature": temperature},
        {},
    ]

    response = None
    last_error = None
    for variant in payload_variants:
        payload = dict(base_payload)
        payload.update(variant)
        response = session.post(_get_anthropic_base_url() + "/messages", json=payload, timeout=45)
        if response.status_code < 400:
            break

        details = _anthropic_error_details(response)
        msg_lower = (details.get("message") or "").lower()
        err_type = str(details.get("type") or "")
        is_param_shape_issue = (
            err_type == "invalid_request_error"
            and (
                "temperature" in msg_lower
                or "unsupported" in msg_lower
                or "unknown" in msg_lower
            )
        )
        last_error = response
        if is_param_shape_issue:
            continue
        break

    if response is None or response.status_code >= 400:
        err_response = last_error or response
        if err_response is None:
            raise LLMExecutionError(detail="Anthropic API error: request failed before receiving a response")
        raise LLMExecutionError(detail=f"Anthropic API error {err_response.status_code}: {err_response.text[:300]}")

    data = response.json()
    content_parts = data.get("content", [])
    text = "".join(str(p.get("text", "")) for p in content_parts if isinstance(p, dict) and p.get("type") == "text").strip()
    usage = data.get("usage", {})

    input_tokens = usage.get("input_tokens", len((system_prompt or "") + prompt) // 4)
    output_tokens = usage.get("output_tokens", len(text) // 4)
    token_info = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "image_count": len(images) if images else 0,
    }
    return text, _normalize_token_info(token_info, prompt=prompt, system_message=system_message, content=text, images=images)


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


_openai_sessions: Dict[str, requests.Session] = {}
_anthropic_sessions: Dict[str, requests.Session] = {}


def _get_openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _get_anthropic_base_url() -> str:
    return os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")


def _get_openai_session(api_key: str) -> requests.Session:
    cache_key = f"{_get_openai_base_url()}::{api_key}"
    if cache_key not in _openai_sessions:
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        _openai_sessions[cache_key] = session
    return _openai_sessions[cache_key]


def _get_anthropic_session(api_key: str) -> requests.Session:
    cache_key = f"{_get_anthropic_base_url()}::{api_key}"
    if cache_key not in _anthropic_sessions:
        session = requests.Session()
        session.headers.update(
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        )
        _anthropic_sessions[cache_key] = session
    return _anthropic_sessions[cache_key]