"""
LLM provider abstraction (SPEC §8). Only Ollama is implemented in Phase 1
(self-hosted is a core product principle - no listing text leaves the
machine); no cloud provider is built. The interface exists so one could be
added later as a ~50-line class without touching pipeline.py/enrich.py.

Interface note: SPEC sketches a richer `complete_json(system, prompt,
schema, max_tokens)` signature modeled after a hosted structured-output
API. That doesn't fit how core/pipeline/enrich/field_specs.py already builds single
combined prompt strings and relies on Ollama's `format: "json"` flag
(no separate system/schema channel) - `complete_json(prompt, timeout)`
below is the interface actually exercised by this codebase.

Also implements the in-process enrichment queue: one GPU serves one
enrichment run at a time (SPEC §8's "serving-stack decision"), so
concurrent imports don't all hammer Ollama together.
"""
import threading
from typing import Protocol

from core.infra.config import OLLAMA_TIMEOUT
from core.pipeline.enrich.ollama_client import BadModelOutput, OllamaUnavailable
from core.pipeline.enrich.ollama_client import generate_json as _ollama_generate_json
from core.pipeline.enrich.ollama_client import is_online as _ollama_is_online

# Re-exported under provider-neutral names so callers don't need to know
# the concrete provider to catch these.
LLMUnavailable = OllamaUnavailable
LLMBadOutput = BadModelOutput


class LLMProvider(Protocol):
    # `timeout` must stay optional, defaulting to OLLAMA_TIMEOUT: the
    # whole-listing callers (comparative_analysis, suggest_tags) send one
    # long prompt and want the full budget, while the field-by-field
    # pipeline passes its own much shorter OLLAMA_FIELD_TIMEOUT. Making it
    # required here silently broke both of the former (they call
    # generate_json(prompt) with one argument) until a browser found it.
    def complete_json(self, prompt: str, timeout: int = OLLAMA_TIMEOUT) -> dict: ...
    def is_online(self) -> bool: ...


class OllamaProvider:
    model_name = "ollama"

    def complete_json(self, prompt: str, timeout: int = OLLAMA_TIMEOUT) -> dict:
        return _ollama_generate_json(prompt, timeout=timeout)

    def is_online(self) -> bool:
        return _ollama_is_online()


_provider: LLMProvider = OllamaProvider()


def get_provider() -> LLMProvider:
    return _provider


def generate_json(prompt: str, timeout: int = OLLAMA_TIMEOUT) -> dict:
    """Thin module-level wrapper so callers (core/pipeline/enrich/pipeline.py,
    core/pipeline/enrich/enrich.py) don't need to look up the provider themselves -
    kept as a plain function, not a re-exported bound method, so tests can
    patch it by the importing module's qualified name as before."""
    return get_provider().complete_json(prompt, timeout)


# --- Enrichment queue (SPEC §8: one GPU, one enrichment at a time) ---

_enrichment_queue_lock = threading.Lock()


def run_with_enrichment_queue(fn, *, on_queued=None):
    """Runs `fn()` holding the single global enrichment slot, so concurrent
    enrichment jobs (multiple imports, a re-enrich batch) serialize onto
    the one local GPU instead of contending for it. Calls `on_queued()`
    once, only if this call actually had to wait for the lock, so the UI
    can show "w kolejce…" without lying to the common case (queue empty)."""
    acquired = _enrichment_queue_lock.acquire(blocking=False)
    if not acquired:
        if on_queued:
            on_queued()
        _enrichment_queue_lock.acquire()
    try:
        return fn()
    finally:
        _enrichment_queue_lock.release()
