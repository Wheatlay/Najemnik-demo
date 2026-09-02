import json

import requests

from core.infra.config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL


class OllamaUnavailable(Exception):
    """The model server itself is unreachable - aborts the whole pipeline,
    since no further calls will succeed either."""


class BadModelOutput(Exception):
    """The server responded but the answer wasn't valid JSON - only the one
    field/call in question should be treated as missing, not the whole
    listing, since the server is otherwise healthy."""


def is_online() -> bool:
    try:
        requests.get(OLLAMA_URL.replace("/api/generate", "/api/tags"), timeout=3)
        return True
    except requests.RequestException:
        return False


def generate_json(prompt: str, timeout: int = OLLAMA_TIMEOUT) -> dict:
    """Calls the local Ollama model and parses its JSON response.

    Raises OllamaUnavailable when the server itself can't be reached (caller
    should abort the whole enrichment run). Raises BadModelOutput when the
    server responded but produced unparseable JSON (caller should treat just
    that one answer as missing and continue)."""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL, "prompt": prompt, "format": "json", "stream": False,
                "options": {"temperature": 0},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise OllamaUnavailable(str(e)) from e
    try:
        return json.loads(resp.json()["response"])
    except (requests.JSONDecodeError, json.JSONDecodeError, KeyError) as e:
        raise BadModelOutput(str(e)) from e
