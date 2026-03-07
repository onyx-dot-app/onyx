import os
from unittest.mock import patch
import litellm
from onyx.llm.constants import LlmProviderNames
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.models import UserMessage

def test_novita_llm_init() -> None:
    # Test that Novita provider sets the correct base URL and custom_llm_provider
    llm = LitellmLLM(
        api_key="test_novita_key",
        model_provider=LlmProviderNames.NOVITA,
        model_name="deepseek/deepseek-v3",
        max_input_tokens=4096,
    )
    
    assert llm._api_base == "https://api.novita.ai/openai"
    assert llm._custom_llm_provider == "openai"
    assert llm._api_key == "test_novita_key"

def test_novita_llm_init_from_env(monkeypatch) -> None:
    # Test that Novita provider picks up the API key from environment
    monkeypatch.setenv("NOVITA_API_KEY", "env_novita_key")
    
    llm = LitellmLLM(
        api_key=None,
        model_provider=LlmProviderNames.NOVITA,
        model_name="deepseek/deepseek-v3",
        max_input_tokens=4096,
    )
    
    assert llm._api_key == "env_novita_key"

def test_novita_completion_call() -> None:
    # Test that Novita completion calls litellm with correct arguments
    llm = LitellmLLM(
        api_key="test_novita_key",
        model_provider=LlmProviderNames.NOVITA,
        model_name="deepseek/deepseek-v3",
        max_input_tokens=4096,
    )
    
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = [
            litellm.ModelResponse(
                id="chatcmpl-123",
                choices=[
                    litellm.Choices(
                        delta={"role": "assistant", "content": "Hello"},
                        finish_reason="stop",
                        index=0,
                    )
                ],
                model="deepseek/deepseek-v3",
            )
        ]
        
        messages = [UserMessage(content="Hi")]
        llm.invoke(messages)
        
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "novita/deepseek/deepseek-v3"
        assert kwargs["base_url"] == "https://api.novita.ai/openai"
        assert kwargs["custom_llm_provider"] == "openai"
        assert kwargs["api_key"] == "test_novita_key"
