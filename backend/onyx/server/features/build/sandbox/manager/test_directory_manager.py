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

    skills_path = templates_dir / "skills"
    skills_path.mkdir()

    agent_instructions = templates_dir / "AGENTS.md"
    agent_instructions.write_text("# Agent Instructions\n")

    return {
        "outputs": outputs_template,
        "venv": venv_template,
        "skills": skills_path,
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
        skills_path=temp_templates["skills"],
        agent_instructions_template_path=temp_templates["agent_instructions"],
    )


class TestSetupOpencodeConfig:
    """Tests for DirectoryManager.setup_opencode_config()."""

    def test_openai_config_with_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test that OpenAI provider includes reasoning configuration."""
        session_id = "test_openai_session"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="openai",
            model_name="gpt-4o",
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == "openai/gpt-4o"
        assert "$schema" in config
        assert "provider" in config
        assert "openai" in config["provider"]
        assert config["provider"]["openai"]["options"]["apiKey"] == "test-api-key"

        # Verify OpenAI reasoning configuration in model config
        assert "models" in config["provider"]["openai"]
        assert "gpt-4o" in config["provider"]["openai"]["models"]
        model_options = config["provider"]["openai"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"

    def test_anthropic_config_with_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test that Anthropic provider includes thinking configuration."""
        session_id = "test_anthropic_session"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="anthropic",
            model_name="claude-sonnet-4-5",
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == "anthropic/claude-sonnet-4-5"
        assert "$schema" in config
        assert "provider" in config
        assert "anthropic" in config["provider"]
        assert config["provider"]["anthropic"]["options"]["apiKey"] == "test-api-key"

        # Verify Anthropic thinking configuration in model config
        assert "models" in config["provider"]["anthropic"]
        assert "claude-sonnet-4-5" in config["provider"]["anthropic"]["models"]
        model_options = config["provider"]["anthropic"]["models"]["claude-sonnet-4-5"][
            "options"
        ]
        assert "thinking" in model_options
        assert model_options["thinking"]["type"] == "enabled"
        assert model_options["thinking"]["budgetTokens"] == 16000

    def test_google_config_with_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test that Google provider includes thinking configuration."""
        session_id = "test_google_session"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="google",
            model_name="gemini-3-pro",
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == "google/gemini-3-pro"
        assert "$schema" in config
        assert "provider" in config
        assert "google" in config["provider"]
        assert config["provider"]["google"]["options"]["apiKey"] == "test-api-key"

        # Verify Google thinking configuration in model config
        assert "models" in config["provider"]["google"]
        assert "gemini-3-pro" in config["provider"]["google"]["models"]
        model_options = config["provider"]["google"]["models"]["gemini-3-pro"][
            "options"
        ]
        assert model_options["thinking_budget"] == 16000
        assert model_options["thinking_level"] == "high"

    def test_bedrock_config_with_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test that Bedrock provider includes thinking configuration."""
        session_id = "test_bedrock_session"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="bedrock",
            model_name="anthropic.claude-v3-5-sonnet-20250219-v1:0",
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == "bedrock/anthropic.claude-v3-5-sonnet-20250219-v1:0"
        assert "$schema" in config
        assert "provider" in config
        assert "bedrock" in config["provider"]
        assert config["provider"]["bedrock"]["options"]["apiKey"] == "test-api-key"

        # Verify Bedrock thinking configuration in model config (same as Anthropic)
        assert "models" in config["provider"]["bedrock"]
        model_name = "anthropic.claude-v3-5-sonnet-20250219-v1:0"
        assert model_name in config["provider"]["bedrock"]["models"]
        model_options = config["provider"]["bedrock"]["models"][model_name]["options"]
        assert "thinking" in model_options
        assert model_options["thinking"]["type"] == "enabled"
        assert model_options["thinking"]["budgetTokens"] == 16000

    def test_azure_config_with_thinking(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test that Azure provider includes thinking configuration."""
        session_id = "test_azure_session"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="azure",
            model_name="gpt-4o",
            api_key="test-api-key",
        )

        config_path = sandbox_path / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())

        # Verify basic structure
        assert config["model"] == "azure/gpt-4o"
        assert "$schema" in config
        assert "provider" in config
        assert "azure" in config["provider"]
        assert config["provider"]["azure"]["options"]["apiKey"] == "test-api-key"

        # Verify Azure reasoning configuration in model config (same as OpenAI)
        assert "models" in config["provider"]["azure"]
        assert "gpt-4o" in config["provider"]["azure"]["models"]
        model_options = config["provider"]["azure"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"

    def test_openai_config_with_api_base(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
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
        temp_base_path: Path,
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
        temp_base_path: Path,
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

        # Verify default permissions are still present
        assert config["permission"]["read"] == "allow"
        assert config["permission"]["write"] == "allow"
        assert config["permission"]["edit"] == "allow"
        assert config["permission"]["grep"] == "allow"
        assert "bash" in config["permission"]
        assert config["permission"]["bash"]["rm"] == "deny"

        # Verify thinking config is still present in model options
        assert "models" in config["provider"]["openai"]
        model_options = config["provider"]["openai"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"

    def test_config_without_api_key(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
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
        temp_base_path: Path,
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
        temp_base_path: Path,
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

    def test_full_config_structure_openai(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test full OpenAI config structure matches expected format."""
        session_id = "test_full_openai"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="openai",
            model_name="gpt-4o",
            api_key="test-openai-key",
            api_base="https://api.openai.com/v1",
            disabled_tools=["webfetch"],
        )

        config_path = sandbox_path / "opencode.json"
        config: dict[str, Any] = json.loads(config_path.read_text())

        # Verify key parts of structure (permission has defaults now)
        assert config["model"] == "openai/gpt-4o"
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert config["provider"]["openai"]["options"]["apiKey"] == "test-openai-key"
        assert config["provider"]["openai"]["api"] == "https://api.openai.com/v1"
        assert "models" in config["provider"]["openai"]
        model_options = config["provider"]["openai"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"
        assert config["permission"]["webfetch"] == "deny"

    def test_full_config_structure_anthropic(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test full Anthropic config structure matches expected format."""
        session_id = "test_full_anthropic"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="anthropic",
            model_name="claude-sonnet-4-5",
            api_key="test-anthropic-key",
            api_base="https://api.anthropic.com",
            disabled_tools=["question"],
        )

        config_path = sandbox_path / "opencode.json"
        config: dict[str, Any] = json.loads(config_path.read_text())

        # Verify structure (permission has defaults now, so we check for overrides)
        assert config["model"] == "anthropic/claude-sonnet-4-5"
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert (
            config["provider"]["anthropic"]["options"]["apiKey"] == "test-anthropic-key"
        )
        assert config["provider"]["anthropic"]["api"] == "https://api.anthropic.com"
        assert "models" in config["provider"]["anthropic"]
        model_options = config["provider"]["anthropic"]["models"]["claude-sonnet-4-5"][
            "options"
        ]
        assert model_options["thinking"]["type"] == "enabled"
        assert model_options["thinking"]["budgetTokens"] == 16000
        assert config["permission"]["question"] == "deny"

    def test_full_config_structure_google(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test full Google config structure matches expected format."""
        session_id = "test_full_google"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="google",
            model_name="gemini-3-pro",
            api_key="test-google-key",
            api_base="https://generativelanguage.googleapis.com",
            disabled_tools=["webfetch"],
        )

        config_path = sandbox_path / "opencode.json"
        config: dict[str, Any] = json.loads(config_path.read_text())

        # Verify structure
        assert config["model"] == "google/gemini-3-pro"
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert config["provider"]["google"]["options"]["apiKey"] == "test-google-key"
        assert (
            config["provider"]["google"]["api"]
            == "https://generativelanguage.googleapis.com"
        )
        assert "models" in config["provider"]["google"]
        model_options = config["provider"]["google"]["models"]["gemini-3-pro"][
            "options"
        ]
        assert model_options["thinking_budget"] == 16000
        assert model_options["thinking_level"] == "high"
        assert config["permission"]["webfetch"] == "deny"

    def test_full_config_structure_bedrock(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test full Bedrock config structure matches expected format."""
        session_id = "test_full_bedrock"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="bedrock",
            model_name="anthropic.claude-v3-5-sonnet-20250219-v1:0",
            api_key="test-bedrock-key",
            disabled_tools=["question"],
        )

        config_path = sandbox_path / "opencode.json"
        config: dict[str, Any] = json.loads(config_path.read_text())

        # Verify structure
        assert config["model"] == "bedrock/anthropic.claude-v3-5-sonnet-20250219-v1:0"
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert config["provider"]["bedrock"]["options"]["apiKey"] == "test-bedrock-key"
        model_name = "anthropic.claude-v3-5-sonnet-20250219-v1:0"
        assert "models" in config["provider"]["bedrock"]
        model_options = config["provider"]["bedrock"]["models"][model_name]["options"]
        assert model_options["thinking"]["type"] == "enabled"
        assert model_options["thinking"]["budgetTokens"] == 16000
        assert config["permission"]["question"] == "deny"

    def test_full_config_structure_azure(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test full Azure config structure matches expected format."""
        session_id = "test_full_azure"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        directory_manager.setup_opencode_config(
            sandbox_path=sandbox_path,
            provider="azure",
            model_name="gpt-4o",
            api_key="test-azure-key",
            api_base="https://myresource.openai.azure.com",
            disabled_tools=["bash"],
        )

        config_path = sandbox_path / "opencode.json"
        config: dict[str, Any] = json.loads(config_path.read_text())

        # Verify structure
        assert config["model"] == "azure/gpt-4o"
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert config["provider"]["azure"]["options"]["apiKey"] == "test-azure-key"
        assert (
            config["provider"]["azure"]["api"] == "https://myresource.openai.azure.com"
        )
        assert "models" in config["provider"]["azure"]
        model_options = config["provider"]["azure"]["models"]["gpt-4o"]["options"]
        assert model_options["reasoningEffort"] == "high"
        assert config["permission"]["bash"] == "deny"


class TestSandboxDirectoryStructure:
    """Tests for complete sandbox directory setup."""

    def test_create_complete_sandbox(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
    ) -> None:
        """Test creating a complete sandbox with all components including opencode.json."""
        session_id = "test_complete_sandbox"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)

        # Setup all components
        directory_manager.setup_outputs_directory(sandbox_path)
        directory_manager.setup_venv(sandbox_path)
        directory_manager.setup_agent_instructions(sandbox_path)
        directory_manager.setup_skills(sandbox_path)
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
        assert (sandbox_path / ".opencode" / "skills").exists()
        assert (sandbox_path / "attachments").exists()
        assert (sandbox_path / "opencode.json").exists()

        # Verify opencode.json has thinking config
        config = json.loads((sandbox_path / "opencode.json").read_text())
        model_options = config["provider"]["anthropic"]["models"]["claude-sonnet-4-5"][
            "options"
        ]
        assert model_options["thinking"]["type"] == "enabled"

    def test_setup_skills_copies_and_overwrites(
        self,
        directory_manager: DirectoryManager,
        temp_base_path: Path,
        temp_templates: dict[str, Path],
    ) -> None:
        """Test that setup_skills copies skills and overwrites existing ones."""
        session_id = "test_skills_setup"
        sandbox_path = directory_manager.create_sandbox_directory(session_id)
        skills_dest = sandbox_path / ".opencode" / "skills"

        # Create a test skill in the source directory
        test_skill_dir = temp_templates["skills"] / "test-skill"
        test_skill_dir.mkdir()
        test_skill_file = test_skill_dir / "SKILL.md"
        test_skill_file.write_text("# Test Skill\nOriginal content")

        # First call - should copy skills
        directory_manager.setup_skills(sandbox_path)
        assert skills_dest.exists()
        assert (skills_dest / "test-skill" / "SKILL.md").exists()
        assert (
            skills_dest / "test-skill" / "SKILL.md"
        ).read_text() == "# Test Skill\nOriginal content"

        # Update the source skill
        test_skill_file.write_text("# Test Skill\nUpdated content")

        # Second call - should overwrite existing skills
        directory_manager.setup_skills(sandbox_path)
        assert skills_dest.exists()
        assert (skills_dest / "test-skill" / "SKILL.md").exists()
        assert (
            skills_dest / "test-skill" / "SKILL.md"
        ).read_text() == "# Test Skill\nUpdated content"
