import threading
import time
from unittest.mock import patch

from core.pipeline.enrich.llm import OllamaProvider, run_with_enrichment_queue


def test_ollama_provider_delegates_to_ollama_client():
    with patch("core.pipeline.enrich.llm._ollama_generate_json", return_value={"answer": "tak"}) as mock:
        result = OllamaProvider().complete_json("prompt", timeout=10)
    assert result == {"answer": "tak"}
    mock.assert_called_once_with("prompt", timeout=10)


def test_ollama_provider_is_online_delegates():
    with patch("core.pipeline.enrich.llm._ollama_is_online", return_value=True) as mock:
        assert OllamaProvider().is_online() is True
    mock.assert_called_once()


def test_enrichment_queue_serializes_concurrent_calls():
    """Two concurrent run_with_enrichment_queue() calls must never execute
    their bodies at the same time - proves the GPU-serialization lock
    actually blocks, not just exists."""
    order = []
    lock = threading.Lock()

    def slow_task(label):
        def _run():
            with lock:
                order.append(f"{label}-start")
            time.sleep(0.05)
            with lock:
                order.append(f"{label}-end")
        return run_with_enrichment_queue(_run)

    t1 = threading.Thread(target=slow_task, args=("a",))
    t2 = threading.Thread(target=slow_task, args=("b",))
    t1.start()
    time.sleep(0.01)  # ensure t1 acquires the lock first
    t2.start()
    t1.join()
    t2.join()

    # Whichever thread ran first must fully finish (both its start and end)
    # before the other one's start appears.
    assert order in (["a-start", "a-end", "b-start", "b-end"], ["b-start", "b-end", "a-start", "a-end"])


def test_enrichment_queue_reports_queued_only_when_actually_waiting():
    queued_calls = []

    def on_queued():
        queued_calls.append(True)

    result = run_with_enrichment_queue(lambda: "done", on_queued=on_queued)
    assert result == "done"
    assert queued_calls == []  # lock was free, never had to wait
