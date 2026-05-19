"""Tests for DirectoryManager.

These are unit tests that test DirectoryManager's behavior in isolation,
focusing on the setup_opencode_config method with different provider configurations.
"""

import json
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from onyx.server.features.build.sandbox.manager.directory_manager import (
    DirectoryManager,
)


@pytest.fixture
def temp_base_path() -> Generator[Path, None, None]:
    """Create a temporary base path for testing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_dir_manager_"))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_templates(temp_base_path: Path) -> dict[str, Path]:
    """Create temporary template directories and files."""
    templates_dir = temp_base_path / "templates"
    templates_dir.mkdir()

    outputs_template = templates_dir / "outputs"
    outputs_template.mkdir()

    venv_template = templates_dir / "venv"
    venv_template.mkdir()

    agent_instructions = templates_dir / "AGENTS.md"
    agent_instructions.write_text("# Agent Instructions\n")

    return {
        "outputs": outputs_template,
        "venv": venv_template,
        "agent_instructions": agent_instructions,
    }


@pytest.fixture
def directory_manager(
    temp_base_path: Path, temp_templates: dict[str, Path]
) -> DirectoryManager:
    """Create a DirectoryManager instance with temporary paths."""
    return DirectoryManager(
        base_path=temp_base_path,
        outputs_template_path=temp_templates["outputs"],
        venv_template_path=temp_templates["venv"],
        agent_instructions_template_path=temp_templates["agent_instructions"],
    )


def _assert_provider_thinking_options(
    model_options: dict[str, Any], provider: str
) -> None:
    """Verify provider-specific thinking/reasoning options."""
    if provider in ("openai", "azure"):
        assert model_options["reasoningEffort"] == "high"
    elif provider in ("anthropic", "bedrock"):
        assert model_options["thinking"]["type"] == "enabled"
        assert model_options["thinking"]["budgetTokens"] == 16000
    elif provider == "google":
        assert model_options["thinking_budget"] == 16000
        assert model_options["thinking_level"] == "high"
    else:
        raise AssertionError(f"Unexpected provider: {provider}")


class TestSetupOpencodeConfig:
    """Tests for DirectoryManager.setup_opencode_config()."""

    @pytest.mark.parametrize(
        "provider,model_name",
        [
            ("openai", "gpt-4o"),
            ("anthropic", "claude-sonnet-4-5"),
            ("google", "gemini-3-pro"),
            ("bedrock", "anthropic.claude-v3-5-sonnet-20250219-v1:0"),
            ("azure", "gpt-4o"),
        ],
    )
    def test_provider_config_with_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
        provider: str,
        model_name: str,
    ) -> None:
        """Test that each provider includes its thinking/reasoning configuration."""
        session_id = f"test_{provider}_session"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider=provider,
            model_name=model_name,
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == f"{provider}/{model_name}"
        assert "$schema" in config
        assert "provider" in config
        assert provider in config["provider"]
        assert config["provider"][provider]["options"]["apiKey"] == "test-api-key"

        # Verify provider-specific thinking/reasoning configuration in model config
        assert "models" in config["provider"][provider]
        assert model_name in config["provider"][provider]["models"]
        model_options = config["provider"][provider]["models"][model_name]["options"]
        _assert_provider_thinking_options(model_options, provider)

    def test_openai_config_with_api_base(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test OpenAI config with custom API base URL."""
        session_id = "test_openai_api_base"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="openai",
            model_name="gpt-4o",
            api_key="test-api-key",
            api_base="https://custom.api.endpoint",
        )

        config_path = sandbox_path / "opencode.json"
        config = json.loads(config_path.read_text())

        # Verify API base is included
        assert config["provider"]["openai"]["api"] == "https://custom.api.endpoint"

        # Verify thinking config is still present in model options
        assert "models" in config["provider"]["openai"]
        model_options = config["provider"]["openai"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"

    def test_anthropic_config_with_api_base(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test Anthropic config with custom API base URL."""
        session_id = "test_anthropic_api_base"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="anthropic",
            model_name="claude-sonnet-4-5",
            api_key="test-api-key",
            api_base="https://custom.anthropic.endpoint",
        )

        config_path = sandbox_path / "opencode.json"
        config = json.loads(config_path.read_text())

        # Verify API base is included
        assert (
            config["provider"]["anthropic"]["api"]
            == "https://custom.anthropic.endpoint"
        )

        # Verify thinking config is still present in model options
        assert "models" in config["provider"]["anthropic"]
        model_options = config["provider"]["anthropic"]["models"]["claude-sonnet-4-5"][
            "options"
        ]
        assert model_options["thinking"]["type"] == "enabled"

    def test_config_with_disabled_tools(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test config with disabled tools permissions."""
        session_id = "test_disabled_tools"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="openai",
            model_name="gpt-4o",
            api_key="test-api-key",
            disabled_tools=["question", "webfetch"],
        )

        config_path = sandbox_path / "opencode.json"
        config = json.loads(config_path.read_text())

        # Verify disabled tools
        assert "permission" in config
        assert config["permission"]["question"] == "deny"
        assert config["permission"]["webfetch"] == "deny"

        # Verify default permissions are still present.
        # `read`/`write`/`edit`/`grep` use a path-pattern map: the "*" key is
        # the catch-all and resolves to "allow" by default; specific paths can
        # override with "deny" (e.g. opencode.json read-block at line 128-132
        # of opencode_config.py).
        for verb in ("read", "write", "edit", "grep"):
            permission = config["permission"][verb]
            assert isinstance(permission, dict)
            assert permission.get("*") == "allow"
        assert "bash" in config["permission"]
        assert config["permission"]["bash"]["rm"] == "deny"

        # Verify thinking config is still present in model options
        assert "models" in config["provider"]["openai"]
        model_options = config["provider"]["openai"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"

    def test_config_without_api_key(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test config without API key still includes thinking settings."""
        session_id = "test_no_api_key"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="openai",
            model_name="gpt-4o",
        )

        config_path = sandbox_path / "opencode.json"
        config = json.loads(config_path.read_text())

        # Should still have provider config structure even without API key
        assert "provider" in config
        assert "openai" in config["provider"]
        # Should not have options (API key) without API key
        assert "options" not in config["provider"]["openai"]

        # But should still have thinking config in model options
        assert "models" in config["provider"]["openai"]
        assert "gpt-4o" in config["provider"]["openai"]["models"]
        model_options = config["provider"]["openai"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"

    def test_other_provider_no_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test that other providers (non OpenAI/Anthropic/Google/Bedrock/Azure) don't get thinking configuration."""
        session_id = "test_other_provider"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="cohere",
            model_name="command-r-plus",
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == "cohere/command-r-plus"
        assert "$schema" in config
        assert "provider" in config
        assert "cohere" in config["provider"]

        # Should not have model config (thinking) for other providers
        assert "models" not in config["provider"]["cohere"]

    def test_config_overwritten_if_exists(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test that existing opencode.json is overwritten with new config."""
        session_id = "test_existing_config"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        # Create existing config
        existing_config = {"model": "existing/model", "custom": "value"}
        config_path = sandbox_path / "opencode.json"
        config_path.write_text(json.dumps(existing_config, indent=2))

        # Try to setup new config
        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="openai",
            model_name="gpt-4o",
            api_key="test-api-key",
        )

        # Verify config is overwritten with new config
        config = json.loads(config_path.read_text())
        assert config["model"] == "openai/gpt-4o"
        assert "custom" not in config  # Old config is replaced
        assert config["provider"]["openai"]["options"]["apiKey"] == "test-api-key"

    @pytest.mark.parametrize(
        "provider,model_name,api_base,disabled_tool",
        [
            ("openai", "gpt-4o", "https://api.openai.com/v1", "webfetch"),
            (
                "anthropic",
                "claude-sonnet-4-5",
                "https://api.anthropic.com",
                "question",
            ),
            (
                "google",
                "gemini-3-pro",
                "https://generativelanguage.googleapis.com",
                "webfetch",
            ),
            (
                "bedrock",
                "anthropic.claude-v3-5-sonnet-20250219-v1:0",
                None,
                "question",
            ),
            (
                "azure",
                "gpt-4o",
                "https://myresource.openai.azure.com",
                "bash",
            ),
        ],
    )
    def test_full_config_structure(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
        provider: str,
        model_name: str,
        api_base: str | None,
        disabled_tool: str,
    ) -> None:
        """Test full config structure matches expected format for each provider."""
        session_id = f"test_full_{provider}"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider=provider,
            model_name=model_name,
            api_key=f"test-{provider}-key",
            api_base=api_base,
            disabled_tools=[disabled_tool],
        )

        config_path = sandbox_path / "opencode.json"
        config: dict[str, Any] = json.loads(config_path.read_text())

        # Verify key parts of structure (permission has defaults now)
        assert config["model"] == f"{provider}/{model_name}"
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert (
            config["provider"][provider]["options"]["apiKey"] == f"test-{provider}-key"
        )
        if api_base is not None:
            assert config["provider"][provider]["api"] == api_base
        assert "models" in config["provider"][provider]
        model_options = config["provider"][provider]["models"][model_name]["options"]
        _assert_provider_thinking_options(model_options, provider)
        assert config["permission"][disabled_tool] == "deny"


class TestSandboxDirectoryStructure:
    """Tests for complete sandbox directory setup."""

    def test_create_complete_sandbox(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,  # noqa: ARG002
    ) -> None:
        """Test creating a complete sandbox with all components including opencode.json."""
        session_id = "test_complete_sandbox"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        # Setup all components (these methods use sandbox_path as session path — legacy naming)
        directory_manager.setup_outputs_directory(sandbox_path)
        directory_manager.setup_venv(sandbox_path)
        directory_manager.setup_agent_instructions(
            sandbox_path, skills_section="No skills available."
        )
        directory_manager.setup_attachments_directory(sandbox_path)
        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="anthropic",
            model_name="claude-sonnet-4-5",
            api_key="test-key",
        )

        # Verify all components exist
        assert (sandbox_path / "outputs").exists()
        assert (sandbox_path / ".venv").exists()
        assert (sandbox_path / "AGENTS.md").exists()
        assert (sandbox_path / "attachments").exists()
        assert (sandbox_path / "opencode.json").exists()

        # Verify opencode.json has thinking config
        config = json.loads((sandbox_path / "opencode.json").read_text())
        model_options = config["provider"]["anthropic"]["models"]["claude-sonnet-4-5"][
            "options"
        ]
        assert model_options["thinking"]["type"] == "enabled"
