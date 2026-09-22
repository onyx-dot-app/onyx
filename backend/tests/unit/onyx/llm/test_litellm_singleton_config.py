import copy
import threading
from types import ModuleType
from unittest.mock import patch

import pytest

_SAMPLE_MODELS = (
    "ollama_chat/gpt-oss:20b",
    "ollama_chat/deepseek-r1:14b",
    "ollama/glm-4.6",
)


@pytest.fixture
def configured_litellm() -> ModuleType:
    """The litellm module after the singleton package has configured it."""
    import litellm

    import onyx.llm.litellm_singleton  # noqa: F401

    return litellm


def test_ollama_chat_models_support_function_calling(
    configured_litellm: ModuleType,
) -> None:
    for model in (
        "ollama_chat/gpt-oss:20b",
        "ollama_chat/deepseek-r1:14b",
        "ollama_chat/glm-4.6",
        "ollama/gpt-oss:20b",
    ):
        assert configured_litellm.supports_function_calling(model=model) is True


def test_register_ollama_models_needs_one_pass_and_no_server(
    configured_litellm: ModuleType,
) -> None:
    """Registration must not depend on a reachable Ollama server, or on a second pass.

    litellm treats an unknown model name as a live deployment and probes the
    Ollama server for it, then stores the entry under the prefix-stripped name.
    Seeding the keys keeps it on the static path.
    """
    from onyx.llm.litellm_singleton.config import register_ollama_models

    # The names litellm checks before deciding a model is a live deployment.
    keys = {
        name
        for model in _SAMPLE_MODELS
        for name in (
            model,
            model.split("/", 1)[1],
            "ollama/" + model.split("/", 1)[1],
            "ollama_chat/" + model.split("/", 1)[1],
        )
    }
    snapshot = {
        key: copy.deepcopy(configured_litellm.model_cost[key])
        for key in keys
        if key in configured_litellm.model_cost
    }

    try:
        for key in keys:
            configured_litellm.model_cost.pop(key, None)

        with patch.object(
            configured_litellm.module_level_client,
            "post",
            side_effect=AssertionError("registration probed the Ollama server"),
        ):
            register_ollama_models()

        for model in _SAMPLE_MODELS:
            assert configured_litellm.supports_function_calling(model=model) is True
    finally:
        configured_litellm.model_cost.update(snapshot)
        register_ollama_models()


@pytest.mark.usefixtures("configured_litellm")
def test_initialize_litellm_runs_once() -> None:
    from onyx.llm.litellm_singleton import config

    with (
        patch.object(config, "configure_litellm_settings") as configure,
        patch.object(config, "register_ollama_models") as register,
        patch.object(config, "load_model_metadata_enrichments") as enrich,
    ):
        # Importing the package already initialized litellm. Reset so this
        # covers the first call and the second one, not just the second.
        config._initialized = False
        try:
            config.initialize_litellm()
            config.initialize_litellm()
        finally:
            config._initialized = True

    assert configure.call_count == 1
    assert register.call_count == 1
    assert enrich.call_count == 1


@pytest.mark.usefixtures("configured_litellm")
def test_initialize_litellm_runs_once_under_concurrency() -> None:
    from onyx.llm.litellm_singleton import config

    with (
        patch.object(config, "configure_litellm_settings") as configure,
        patch.object(config, "register_ollama_models") as register,
        patch.object(config, "load_model_metadata_enrichments") as enrich,
    ):
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
    assert register.call_count == 1
    assert enrich.call_count == 1
