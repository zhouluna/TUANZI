"""NVIDIA chat proxy. Model ids come from the live list, then from probes.

LUNA ZHOU, 2026-11-10. Speed numbers are measured here. A public catalog may
suggest which ids are chat models; it is not the source of the timings.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

import httpx

from .config import models_catalog_url, nvidia_api_key, nvidia_base_url, probe_limit

_NON_CHAT = ("embed", "rerank", "retrieval", "tts", "asr")


def chat_completions_url() -> str:
    return nvidia_base_url() + "/chat/completions"


def models_url() -> str:
    return nvidia_base_url() + "/models"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + nvidia_api_key(), "Content-Type": "application/json"}


def http_json(method: str, url: str, payload: dict | None = None, headers: dict | None = None, timeout: float = 12) -> dict:
    response = httpx.request(method, url, json=payload, headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else {}


def http_stream(url: str, payload: dict, headers: dict, timeout: float = 40) -> Iterator[str]:
    with httpx.stream("POST", url, json=payload, headers=headers, timeout=timeout) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                yield line


def _looks_like_chat(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(token in lowered for token in _NON_CHAT)


def ids_from_nvidia_list(payload: dict) -> list[str]:
    found = []
    for item in payload.get("data") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            found.append(item["id"])
    return found


def ids_from_catalog(payload: dict) -> list[str]:
    """Optional read-only catalog. Only openai-compatible chat ids are kept."""
    found = []
    for item in payload.get("models") or []:
        if not isinstance(item, dict) or item.get("category") != "chat":
            continue
        endpoint = item.get("endpoint") or {}
        if not isinstance(endpoint, dict) or endpoint.get("adapter") != "openai_chat":
            continue
        model_id = endpoint.get("nvidiaModelId") or item.get("id")
        if isinstance(model_id, str) and model_id and _looks_like_chat(model_id):
            found.append(model_id)
    return found


def candidate_models() -> list[str]:
    """Never a baked-in model id. Empty means we have nothing to probe yet."""
    headers = _auth_headers() if nvidia_api_key() else None
    nvidia_ids: list[str] = []
    catalog_ids: list[str] = []
    if nvidia_api_key():
        try:
            nvidia_ids = [model for model in ids_from_nvidia_list(http_json("GET", models_url(), headers=headers)) if _looks_like_chat(model)]
        except (httpx.HTTPError, ValueError):
            nvidia_ids = []
    catalog = models_catalog_url()
    if catalog:
        try:
            catalog_ids = ids_from_catalog(http_json("GET", catalog, timeout=8))
        except (httpx.HTTPError, ValueError):
            catalog_ids = []
    if nvidia_ids and catalog_ids:
        catalog_set = set(catalog_ids)
        both = [model for model in nvidia_ids if model in catalog_set]
        return both or nvidia_ids
    return nvidia_ids or catalog_ids


def _delta_text(line: str) -> str:
    if not line.startswith("data:"):
        return ""
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return ""
    try:
        payload = json.loads(raw)
    except ValueError:
        return ""
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content") if isinstance(delta, dict) else ""
    return content if isinstance(content, str) else ""


def probe_first_token(model_name: str) -> float:
    """Milliseconds until the first streamed token. Raises if the model stays silent."""
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "只回复一个字：喵"}],
        "stream": True,
        "max_tokens": 8,
        "temperature": 0,
    }
    started = time.perf_counter()
    for line in http_stream(chat_completions_url(), payload, _auth_headers(), timeout=12):
        if _delta_text(line):
            return (time.perf_counter() - started) * 1000
    raise TimeoutError("no token")


def stream_model(model_name: str, messages: list[dict]) -> Iterator[str]:
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 400,
    }
    produced = False
    for line in http_stream(chat_completions_url(), payload, _auth_headers(), timeout=45):
        text = _delta_text(line)
        if text:
            produced = True
            yield text
    if not produced:
        raise TimeoutError("empty reply")
