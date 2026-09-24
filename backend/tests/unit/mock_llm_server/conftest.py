from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.multi_llm import LitellmLLM
from tests.integration.common_utils.ports import available_port
from tests.integration.mock_services.mock_llm_server.handle import ScriptHandle
from tests.integration.mock_services.mock_llm_server.registry import ScriptRegistry
from tests.integration.mock_services.mock_llm_server.server import MockLLMServerThread


@pytest.fixture(scope="module")
def mock_llm_server() -> Generator[MockLLMServerThread, None, None]:
    server = MockLLMServerThread(ScriptRegistry(), port=available_port())
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def script(
    mock_llm_server: MockLLMServerThread,
) -> Generator[ScriptHandle, None, None]:
    script_id = uuid4().hex
    handle = ScriptHandle(
        mock_llm_server.registry, script_id, mock_llm_server.api_base(script_id)
    )
    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture(autouse=True)
def _no_env_injection() -> Generator[None, None, None]:
    # Env injection reads a deployment setting; off means invoke() does not stream.
    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False):
        yield


def make_llm(api_base: str, model_name: str = "mock-model") -> LitellmLLM:
    return LitellmLLM(
        api_key="sk-mock-llm-server",
        model_provider=LlmProviderNames.OPENAI_COMPATIBLE,
        model_name=model_name,
        max_input_tokens=200000,
        api_base=api_base,
    )


@pytest.fixture
def llm(script: ScriptHandle) -> LitellmLLM:
    return make_llm(script.api_base)
