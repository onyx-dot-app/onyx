#!/usr/bin/env python3
"""Standalone script to verify opencode.json generation.

Usage:
  python verify_opencode_config.py

This script creates temporary sandboxes and generates opencode.json files
for different providers, then prints them for manual inspection.
"""

import json
import shutil
import tempfile
from pathlib import Path

from onyx.server.features.build.sandbox.internal.directory_manager import (
    DirectoryManager,
)


def create_temp_templates() -> tuple[Path, dict[str, Path]]:
    """Create temporary template directories."""
    base_path = Path(tempfile.mkdtemp(prefix="verify_opencode_"))

    templates = {
        "outputs": base_path / "templates" / "outputs",
        "venv": base_path / "templates" / "venv",
        "skills": base_path / "templates" / "skills",
        "agent_instructions": base_path / "templates" / "AGENTS.md",
    }

    for path in templates.values():
        if path.suffix == ".md":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Agent Instructions\n")
        else:
            path.mkdir(parents=True, exist_ok=True)

    return base_path, templates


def verify_provider_config(
    provider: str,
    model_name: str,
    api_key: str = "test-api-key",
    api_base: str | None = None,
    disabled_tools: list[str] | None = None,
) -> dict:
    """Generate and return opencode.json config for a provider."""
    base_path, templates = create_temp_templates()

    try:
        manager = DirectoryManager(
            base_path=base_path,
            outputs_template_path=templates["outputs"],
            venv_template_path=templates["venv"],
            skills_path=templates["skills"],
            agent_instructions_template_path=templates["agent_instructions"],
        )

        session_id = f"verify_{provider}"
        sandbox_path = manager.create_sandbox_directory(session_id)

        manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
            disabled_tools=disabled_tools,
        )

        config_path = sandbox_path / "opencode.json"
        return json.loads(config_path.read_text())

    finally:
        shutil.rmtree(base_path, ignore_errors=True)


def main() -> None:
    """Run verification tests for different providers."""
    print("=" * 80)
    print("Verifying opencode.json generation for different providers")
    print("=" * 80)

    # Test OpenAI configuration
    print("\n1. OpenAI Provider (with reasoning configuration)")
    print("-" * 80)
    openai_config = verify_provider_config(
        provider="openai",
        model_name="gpt-4o",
        api_key="{env:OPENAI_API_KEY}",
    )
    print(json.dumps(openai_config, indent=2))

    # Test Anthropic configuration
    print("\n2. Anthropic Provider (with thinking configuration)")
    print("-" * 80)
    anthropic_config = verify_provider_config(
        provider="anthropic",
        model_name="claude-sonnet-4-5",
        api_key="{env:ANTHROPIC_API_KEY}",
    )
    print(json.dumps(anthropic_config, indent=2))

    # Test Google configuration
    print("\n3. Google Provider (with thinking configuration)")
    print("-" * 80)
    google_config = verify_provider_config(
        provider="google",
        model_name="gemini-3-pro",
        api_key="{env:GOOGLE_API_KEY}",
    )
    print(json.dumps(google_config, indent=2))

    # Test Bedrock configuration
    print("\n4. Bedrock Provider (with thinking configuration)")
    print("-" * 80)
    bedrock_config = verify_provider_config(
        provider="bedrock",
        model_name="anthropic.claude-v3-5-sonnet-20250219-v1:0",
        api_key="{env:AWS_ACCESS_KEY_ID}",
    )
    print(json.dumps(bedrock_config, indent=2))

    # Test Azure configuration
    print("\n5. Azure Provider (with thinking configuration)")
    print("-" * 80)
    azure_config = verify_provider_config(
        provider="azure",
        model_name="gpt-4o",
        api_key="{env:AZURE_API_KEY}",
    )
    print(json.dumps(azure_config, indent=2))

    # Test OpenAI with full options
    print("\n6. OpenAI Provider (with API base and disabled tools)")
    print("-" * 80)
    openai_full_config = verify_provider_config(
        provider="openai",
        model_name="gpt-4o",
        api_key="{env:OPENAI_API_KEY}",
        api_base="https://api.openai.com/v1",
        disabled_tools=["webfetch", "question"],
    )
    print(json.dumps(openai_full_config, indent=2))

    # Test Anthropic with full options
    print("\n7. Anthropic Provider (with API base and disabled tools)")
    print("-" * 80)
    anthropic_full_config = verify_provider_config(
        provider="anthropic",
        model_name="claude-sonnet-4-5",
        api_key="{env:ANTHROPIC_API_KEY}",
        api_base="https://api.anthropic.com",
        disabled_tools=["webfetch"],
    )
    print(json.dumps(anthropic_full_config, indent=2))

    # Test Google with full options
    print("\n8. Google Provider (with API base and disabled tools)")
    print("-" * 80)
    google_full_config = verify_provider_config(
        provider="google",
        model_name="gemini-3-pro",
        api_key="{env:GOOGLE_API_KEY}",
        api_base="https://generativelanguage.googleapis.com",
        disabled_tools=["bash"],
    )
    print(json.dumps(google_full_config, indent=2))

    # Test Cohere (no thinking config)
    print("\n9. Cohere Provider (no thinking configuration)")
    print("-" * 80)
    cohere_config = verify_provider_config(
        provider="cohere",
        model_name="command-r-plus",
        api_key="{env:COHERE_API_KEY}",
    )
    print(json.dumps(cohere_config, indent=2))

    # Test without API key
    print("\n10. OpenAI Provider (without API key)")
    print("-" * 80)
    openai_no_key = verify_provider_config(
        provider="openai",
        model_name="gpt-4o",
        api_key=None,  # type: ignore
    )
    print(json.dumps(openai_no_key, indent=2))

    print("\n" + "=" * 80)
    print("Verification complete!")
    print("=" * 80)

    # Validation checks
    print("\n✓ Validation checks:")
    assert openai_config["options"]["reasoningEffort"] == "high"
    assert openai_config["options"]["textVerbosity"] == "low"
    assert openai_config["options"]["reasoningSummary"] == "auto"
    assert openai_config["options"]["include"] == ["reasoning.encrypted_content"]
    print("  ✓ OpenAI reasoning configuration correct")

    assert anthropic_config["options"]["thinking"]["type"] == "enabled"
    assert anthropic_config["options"]["thinking"]["budgetTokens"] == 16000
    print("  ✓ Anthropic thinking configuration correct")

    assert google_config["options"]["thinking_budget"] == 16000
    assert google_config["options"]["thinking_level"] == "high"
    print("  ✓ Google thinking configuration correct")

    assert bedrock_config["options"]["thinking"]["type"] == "enabled"
    assert bedrock_config["options"]["thinking"]["budgetTokens"] == 16000
    print("  ✓ Bedrock thinking configuration correct")

    assert azure_config["options"]["reasoningEffort"] == "high"
    assert azure_config["options"]["textVerbosity"] == "low"
    assert azure_config["options"]["reasoningSummary"] == "auto"
    assert azure_config["options"]["include"] == ["reasoning.encrypted_content"]
    print("  ✓ Azure reasoning configuration correct")

    assert "reasoningEffort" not in cohere_config.get("options", {})
    assert "thinking" not in cohere_config.get("options", {})
    assert "thinking_budget" not in cohere_config.get("options", {})
    print("  ✓ Cohere provider has no thinking configuration (correct)")

    assert "provider" not in openai_no_key
    assert openai_no_key["options"]["reasoningEffort"] == "high"
    print("  ✓ Config without API key still has thinking options (correct)")

    print("\nAll validations passed! ✓")


if __name__ == "__main__":
    main()
