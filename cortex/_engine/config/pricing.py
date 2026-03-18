import json
import os
import re
import threading
from fnmatch import fnmatch
from typing import Dict, Any, Optional


# USD per 1M tokens (input/output)
_DEFAULT_PRICING: Dict[str, Dict[str, float]] = {
    "gemini-2.5-flash-lite": {"input_per_million": 0.10, "output_per_million": 0.40},
    "gemini-2.5-flash-lite-preview-09-2025": {"input_per_million": 0.10, "output_per_million": 0.40},
    "gemini-3.1-flash-lite-preview": {"input_per_million": 0.10, "output_per_million": 0.40},
    "gemini-2.0-flash": {"input_per_million": 0.10, "output_per_million": 0.40},
    "gemini-2.5-flash": {"input_per_million": 0.15, "output_per_million": 0.60},
    "gemini-3-flash-preview": {"input_per_million": 0.50, "output_per_million": 3.00},
    "gemini-3.1-flash-preview": {"input_per_million": 0.50, "output_per_million": 3.00},
    "gemini-2.5-pro": {"input_per_million": 1.25, "output_per_million": 10.00},
    "gemini-3-pro-preview": {"input_per_million": 2.00, "output_per_million": 12.00},
    "gemini-3.1-pro-preview": {"input_per_million": 2.00, "output_per_million": 12.00},
    "gpt-4.1-nano": {"input_per_million": 0.10, "output_per_million": 0.40},
    "gpt-4o-mini": {"input_per_million": 0.15, "output_per_million": 0.60},
    "gpt-5-mini": {"input_per_million": 0.25, "output_per_million": 1.00},
    "gpt-4.1-mini": {"input_per_million": 0.40, "output_per_million": 1.60},
    "gpt-5": {"input_per_million": 1.25, "output_per_million": 10.00},
    "o4-mini": {"input_per_million": 1.10, "output_per_million": 4.40},
    "gpt-4.1": {"input_per_million": 2.00, "output_per_million": 8.00},
    "o3": {"input_per_million": 2.00, "output_per_million": 8.00},
    "gpt-4o": {"input_per_million": 2.50, "output_per_million": 10.00},
    "claude-haiku-3": {"input_per_million": 0.25, "output_per_million": 1.25},
    "claude-haiku-3-5": {"input_per_million": 0.80, "output_per_million": 4.00},
    "claude-haiku-4-5-20251001": {"input_per_million": 1.00, "output_per_million": 5.00},
    "claude-sonnet-4": {"input_per_million": 3.00, "output_per_million": 15.00},
    "claude-sonnet-4-5": {"input_per_million": 3.00, "output_per_million": 15.00},
    "claude-sonnet-4-6": {"input_per_million": 3.00, "output_per_million": 15.00},
    "claude-opus-4-5": {"input_per_million": 5.00, "output_per_million": 25.00},
    "claude-opus-4-6": {"input_per_million": 5.00, "output_per_million": 25.00},
    "claude-opus-4-1": {"input_per_million": 15.00, "output_per_million": 75.00},
}

_USER_PRICING_PATH = os.path.expanduser("~/delfhos/pricing.json")

_cache_lock = threading.Lock()
_cache_mtime: Optional[float] = None
_cache_data: Dict[str, Dict[str, float]] = {}


def _normalize_pricing_map(raw: Any) -> Dict[str, Dict[str, float]]:
    normalized: Dict[str, Dict[str, float]] = {}
    if not isinstance(raw, dict):
        return normalized

    for model_name, entry in raw.items():
        if not isinstance(model_name, str) or not isinstance(entry, dict):
            continue

        input_rate = entry.get("input_per_million")
        output_rate = entry.get("output_per_million")

        try:
            input_rate_f = float(input_rate)
            output_rate_f = float(output_rate)
        except (TypeError, ValueError):
            continue

        if input_rate_f < 0 or output_rate_f < 0:
            continue

        normalized[model_name.strip().lower()] = {
            "input_per_million": input_rate_f,
            "output_per_million": output_rate_f,
        }

    return normalized


def ensure_user_pricing_file() -> str:
    parent = os.path.dirname(_USER_PRICING_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)

    if not os.path.exists(_USER_PRICING_PATH):
        payload = {
            "_comment": "USD per 1M tokens. Edit rates or add models. Wildcards are supported, e.g. gpt-*.",
            "models": _DEFAULT_PRICING,
        }
        with open(_USER_PRICING_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    return _USER_PRICING_PATH


def _load_user_pricing() -> Dict[str, Dict[str, float]]:
    ensure_user_pricing_file()
    try:
        with open(_USER_PRICING_PATH, "r", encoding="utf-8") as f:
            raw_text = f.read()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                # Accept JSONC-style comments so users can annotate pricing files.
                stripped = re.sub(r"(?m)//.*$", "", raw_text)
                stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
                data = json.loads(stripped)
    except Exception:
        return {}

    if isinstance(data, dict) and "models" in data:
        return _normalize_pricing_map(data.get("models"))

    if isinstance(data, dict):
        llm_section = data.get("llm")
        if isinstance(llm_section, dict) and "models" in llm_section:
            return _normalize_pricing_map(llm_section.get("models"))

    return _normalize_pricing_map(data)


def load_pricing_map() -> Dict[str, Dict[str, float]]:
    global _cache_mtime, _cache_data

    ensure_user_pricing_file()
    try:
        mtime = os.path.getmtime(_USER_PRICING_PATH)
    except OSError:
        mtime = None

    with _cache_lock:
        if _cache_mtime is not None and _cache_mtime == mtime and _cache_data:
            return dict(_cache_data)

        merged = {k.lower(): dict(v) for k, v in _DEFAULT_PRICING.items()}
        merged.update(_load_user_pricing())

        _cache_mtime = mtime
        _cache_data = merged
        return dict(_cache_data)


def _resolve_model_pricing(model: Optional[str], pricing_map: Dict[str, Dict[str, float]]) -> Optional[Dict[str, float]]:
    if not model:
        return None

    key = model.strip().lower()
    if key in pricing_map:
        return pricing_map[key]

    wildcard_matches = [(pattern, rates) for pattern, rates in pricing_map.items() if "*" in pattern and fnmatch(key, pattern)]
    if wildcard_matches:
        wildcard_matches.sort(key=lambda item: len(item[0]), reverse=True)
        return wildcard_matches[0][1]

    if "/" in key:
        model_only = key.split("/", 1)[1].strip()
        if model_only in pricing_map:
            return pricing_map[model_only]
        wildcard_matches = [(pattern, rates) for pattern, rates in pricing_map.items() if "*" in pattern and fnmatch(model_only, pattern)]
        if wildcard_matches:
            wildcard_matches.sort(key=lambda item: len(item[0]), reverse=True)
            return wildcard_matches[0][1]

    return None


def has_pricing_for_model(model: Optional[str]) -> bool:
    pricing_map = load_pricing_map()
    return _resolve_model_pricing(model, pricing_map) is not None


def calculate_cost_usd(model: Optional[str], input_tokens: int, output_tokens: int) -> Optional[float]:
    pricing_map = load_pricing_map()
    rates = _resolve_model_pricing(model, pricing_map)
    if not rates:
        return None

    in_rate = float(rates.get("input_per_million", 0.0))
    out_rate = float(rates.get("output_per_million", 0.0))

    in_cost = (max(int(input_tokens or 0), 0) / 1_000_000.0) * in_rate
    out_cost = (max(int(output_tokens or 0), 0) / 1_000_000.0) * out_rate
    return round(in_cost + out_cost, 8)


def get_user_pricing_path() -> str:
    return ensure_user_pricing_file()
