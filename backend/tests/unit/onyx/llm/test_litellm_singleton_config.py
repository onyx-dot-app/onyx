import threading
from unittest.mock import patch

_SAMPLE_MODELS = (
    "ollama_chat/gpt-oss:20b",
    "ollama_chat/deepseek-r1:14b",
    "ollama/glm-4.6",
)


def test_ollama_chat_models_support_function_calling() -> None:
    """Locally hosted Ollama models have no catalog entry, so the rendered map
    carries their capability flags via the supplement-style extra entries."""
    from onyx.llm.model_catalog import build_model_map

    model_map = build_model_map()
    for model in _SAMPLE_MODELS:
        entry = model_map.get(model)
        assert entry is not None, f"{model} missing from rendered model map"
        assert entry.get("supports_function_calling") is True


def test_initialize_litellm_runs_once() -> None:
    from onyx.llm.litellm_singleton import config

    with patch.object(config, "configure_litellm_settings") as configure:
        # Importing the package already initialized litellm. Reset so this
        # covers the first call and the second one, not just the second.
        config._initialized = False
        try:
            config.initialize_litellm()
            config.initialize_litellm()
        finally:
            config._initialized = True

    assert configure.call_count == 1


def test_initialize_litellm_runs_once_under_concurrency() -> None:
    from onyx.llm.litellm_singleton import config

    with patch.object(config, "configure_litellm_settings") as configure:
        config._initialized = False
        try:
            barrier = threading.Barrier(8)

            def worker() -> None:
                barrier.wait()
                config.initialize_litellm()

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            config._initialized = True

    assert configure.call_count == 1
