"""Write Pi model configuration from injected GlomiAI LLM environment."""

import json
import os
from pathlib import Path
from typing import Any


def build_config() -> dict[str, Any]:
    base_url = os.environ["GLOMI_LLM_BASE_URL"]
    model = os.environ["GLOMI_LLM_MODEL"]
    return {
        "providers": {
            "glomi": {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": "GLOMI_LLM_API_KEY",
                "compat": {
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                },
                "models": [{"id": model}],
            }
        }
    }


def main() -> None:
    target_dir = Path.home() / ".pi" / "agent"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "models.json").write_text(
        json.dumps(build_config(), indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
