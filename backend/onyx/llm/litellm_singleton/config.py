import litellm


def configure_litellm_settings() -> None:
    # If a user configures a different model and it doesn't support all the same
    # parameters like frequency and presence, just ignore them
    litellm.drop_params = True
    litellm.telemetry = False
    litellm.modify_params = True


def register_ollama_models() -> None:
    litellm.register_model(
        model_cost={
            # GPT-OSS models
            "ollama_chat/gpt-oss:120b-cloud": {"supports_function_calling": True},
            "ollama_chat/gpt-oss:120b": {"supports_function_calling": True},
            "ollama_chat/gpt-oss:20b-cloud": {"supports_function_calling": True},
            "ollama_chat/gpt-oss:20b": {"supports_function_calling": True},
            # DeepSeek models
            "ollama_chat/deepseek-r1:latest": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:1.5b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:7b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:8b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:14b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:32b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:70b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:671b": {"supports_function_calling": True},
            "ollama_chat/deepseek-v3.1:latest": {"supports_function_calling": True},
            "ollama_chat/deepseek-v3.1:671b": {"supports_function_calling": True},
            "ollama_chat/deepseek-v3.1:671b-cloud": {"supports_function_calling": True},
            # Gemma3 models
            "ollama_chat/gemma3:latest": {"supports_function_calling": True},
            "ollama_chat/gemma3:270m": {"supports_function_calling": True},
            "ollama_chat/gemma3:1b": {"supports_function_calling": True},
            "ollama_chat/gemma3:4b": {"supports_function_calling": True},
            "ollama_chat/gemma3:12b": {"supports_function_calling": True},
            "ollama_chat/gemma3:27b": {"supports_function_calling": True},
            # Qwen models
            "ollama_chat/qwen3-coder:latest": {"supports_function_calling": True},
            "ollama_chat/qwen3-coder:30b": {"supports_function_calling": True},
            "ollama_chat/qwen3-coder:480b": {"supports_function_calling": True},
            "ollama_chat/qwen3-coder:480b-cloud": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:latest": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:2b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:4b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:8b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:30b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:32b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:235b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:235b-cloud": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:235b-instruct-cloud": {
                "supports_function_calling": True
            },
            # Kimi
            "ollama_chat/kimi-k2:1t": {"supports_function_calling": True},
            "ollama_chat/kimi-k2:1t-cloud": {"supports_function_calling": True},
            # GLM
            "ollama_chat/glm-4.6:cloud": {"supports_function_calling": True},
            "ollama_chat/glm-4.6": {"supports_function_calling": True},
        }
    )


def initialize_litellm() -> None:
    configure_litellm_settings()
    register_ollama_models()
