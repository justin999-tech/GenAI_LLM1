"""
Multi-provider LLM client manager.

Supports OpenAI-compatible endpoints (covers ~90% of LLM services):
OpenAI, Anthropic (via OpenAI-compat shim), OpenRouter, DeepSeek,
Together AI, Mistral, Groq, Ollama, LM Studio, Fireworks, etc.

Provider configs are stored in providers.json (gitignored). API keys
never leave the server.
"""
import json
import os
import uuid
import time
from typing import Optional

from groq import Groq

PROVIDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "providers.json")

# Built-in templates for the UI to autofill.
PROVIDER_TEMPLATES = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "key_url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "openrouter": {
        "label": "OpenRouter (1 key for all models)",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "anthropic/claude-sonnet-4-6",
            "openai/gpt-4o",
            "google/gemini-2.5-pro",
            "meta-llama/llama-4-scout-17b-instruct",
        ],
        "key_url": "https://openrouter.ai/keys",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "models": [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "Qwen/Qwen2.5-72B-Instruct-Turbo",
        ],
        "key_url": "https://api.together.xyz/settings/api-keys",
    },
    "mistral": {
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-latest", "mistral-small-latest"],
        "key_url": "https://console.mistral.ai/api-keys",
    },
    "ollama": {
        "label": "Ollama (Local)",
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.2", "qwen2.5", "mistral"],
        "key_url": "https://ollama.com/download",
    },
    "lmstudio": {
        "label": "LM Studio (Local)",
        "base_url": "http://localhost:1234/v1",
        "models": [],
        "key_url": "https://lmstudio.ai/",
    },
    "groq": {
        "label": "Groq (built-in)",
        "base_url": None,
        "models": [],
        "key_url": "https://console.groq.com/keys",
    },
}


def _load() -> dict:
    if not os.path.exists(PROVIDERS_FILE):
        return {"providers": {}}
    try:
        with open(PROVIDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"providers": {}}


def _save(data: dict):
    with open(PROVIDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_providers(safe: bool = True) -> list[dict]:
    """Return all configured providers. If safe=True, mask API keys."""
    data = _load()
    out = []
    for pid, p in data.get("providers", {}).items():
        item = dict(p)
        item["id"] = pid
        if safe and item.get("api_key"):
            k = item["api_key"]
            item["api_key"] = (k[:5] + "…" + k[-4:]) if len(k) > 10 else "***"
        out.append(item)
    return out


def add_provider(name: str, type: str, base_url: str,
                 api_key: str, models: list[str]) -> str:
    data = _load()
    pid = str(uuid.uuid4())[:8]
    data.setdefault("providers", {})[pid] = {
        "name": name,
        "type": type,
        "base_url": base_url,
        "api_key": api_key,
        "models": list(models),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_test": None,
        "last_test_ok": None,
    }
    _save(data)
    return pid


def delete_provider(pid: str) -> bool:
    data = _load()
    if pid in data.get("providers", {}):
        del data["providers"][pid]
        _save(data)
        return True
    return False


def update_test_result(pid: str, ok: bool, message: str = ""):
    data = _load()
    if pid in data.get("providers", {}):
        data["providers"][pid]["last_test"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data["providers"][pid]["last_test_ok"] = bool(ok)
        data["providers"][pid]["last_test_message"] = message[:200]
        _save(data)


def get_provider_for_model(model_id: str) -> Optional[dict]:
    """Find which provider owns this model_id. Returns the raw provider
    config (with API key). Returns None for built-in Groq models."""
    data = _load()
    for pid, p in data.get("providers", {}).items():
        if model_id in (p.get("models") or []):
            return {**p, "id": pid}
    return None


def get_client_for_model(model_id: str):
    """Return an OpenAI-compatible client (or Groq client) for a model.
    Falls back to the built-in Groq client when the model isn't in any
    user-added provider."""
    p = get_provider_for_model(model_id)
    if p is None:
        # Built-in Groq.
        return Groq(api_key=os.getenv("GROQ_API_KEY")), "groq"

    # All user-added providers expose OpenAI-compatible /v1 endpoints.
    # Use the openai package which most providers support.
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Install `openai` package for custom providers: pip install openai")
    client = OpenAI(api_key=p["api_key"], base_url=p["base_url"])
    return client, p["type"]


def list_all_models() -> list[dict]:
    """Combined model list: built-in Groq + all user providers.
    Returns shape compatible with chatbot.AVAILABLE_MODELS."""
    from chatbot import AVAILABLE_MODELS as BUILTIN
    out = list(BUILTIN)
    for p in list_providers(safe=False):
        provider_label = p.get("name") or p.get("type") or "custom"
        for m in p.get("models", []):
            out.append({
                "id": m,
                "name": m,
                "desc": f"via {provider_label}",
                "provider_id": p["id"],
                "provider_name": provider_label,
            })
    return out


def test_connection(pid: str) -> tuple[bool, str]:
    """Try a tiny chat request to verify the provider works."""
    data = _load()
    p = data.get("providers", {}).get(pid)
    if not p:
        return False, "Provider not found"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=p["api_key"], base_url=p["base_url"])
        # Minimal request: ask "ok" with 5 max tokens
        models = p.get("models") or []
        if not models:
            # Try a generic listing
            try:
                client.models.list()
                return True, "OK (models endpoint)"
            except Exception as e:
                return False, str(e)[:200]
        resp = client.chat.completions.create(
            model=models[0],
            messages=[{"role": "user", "content": "Say 'ok' only."}],
            max_tokens=5,
        )
        text = resp.choices[0].message.content
        return True, f"OK: '{text[:30]}'"
    except Exception as e:
        return False, str(e)[:200]
