"""Directory management for sandbox lifecycle."""

import json
import shutil
from pathlib import Path
from typing import Any


class DirectoryManager:
    """Manages sandbox directory creation and cleanup.

    Responsible for:
    - Creating sandbox directory structure
    - Setting up symlinks to knowledge files
    - Copying templates (outputs, venv, skills, AGENTS.md)
    - Cleaning up sandbox directories on termination
    """

    def __init__(
        self,
        base_path: Path,
        outputs_template_path: Path,
        venv_template_path: Path,
        skills_path: Path,
        agent_instructions_template_path: Path,
    ) -> None:
        """Initialize DirectoryManager with template paths.

        Args:
            base_path: Root directory for all sandboxes
            outputs_template_path: Path to outputs template directory
            venv_template_path: Path to Python virtual environment template
            skills_path: Path to agent skills directory
            agent_instructions_template_path: Path to AGENTS.md template file
        """
        self._base_path = base_path
        self._outputs_template_path = outputs_template_path
        self._venv_template_path = venv_template_path
        self._skills_path = skills_path
        self._agent_instructions_template_path = agent_instructions_template_path

    def create_sandbox_directory(self, session_id: str) -> Path:
        """Create sandbox directory structure.

        Creates the base directory for a sandbox session:
        {base_path}/{session_id}/
        ├── files/                      # Symlink to knowledge/source files
        ├── user_uploaded_files/        # User-uploaded files
        ├── outputs/                    # Working directory from template
        │   ├── web/                    # Next.js app
        │   ├── slides/
        │   ├── markdown/
        │   └── graphs/
        ├── .venv/                      # Python virtual environment
        ├── AGENTS.md                   # Agent instructions
        └── .agent/
            └── skills/                 # Agent skills

        Args:
            session_id: Unique identifier for the session

        Returns:
            Path to the created sandbox directory
        """
        sandbox_path = self._base_path / session_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        return sandbox_path

    def setup_files_symlink(
        self,
        sandbox_path: Path,
        file_system_path: Path,
    ) -> None:
        """Create symlink to knowledge/source files.

        Args:
            sandbox_path: Path to the sandbox directory
            file_system_path: Path to the source files to link
        """
        files_link = sandbox_path / "files"
        if not files_link.exists():
            files_link.symlink_to(file_system_path, target_is_directory=True)

    def setup_outputs_directory(self, sandbox_path: Path) -> None:
        """Copy outputs template and create additional directories.

        Copies the Next.js template and creates additional output
        directories for generated content (slides, markdown, graphs).

        Args:
            sandbox_path: Path to the sandbox directory
        """
        output_dir = sandbox_path / "outputs"
        if not output_dir.exists():
            if self._outputs_template_path.exists():
                shutil.copytree(self._outputs_template_path, output_dir, symlinks=True)
            else:
                output_dir.mkdir(parents=True)

        # Create additional output directories for generated content
        (output_dir / "slides").mkdir(parents=True, exist_ok=True)
        (output_dir / "markdown").mkdir(parents=True, exist_ok=True)
        (output_dir / "graphs").mkdir(parents=True, exist_ok=True)

    def setup_venv(self, sandbox_path: Path) -> Path:
        """Copy virtual environment template.

        Args:
            sandbox_path: Path to the sandbox directory

        Returns:
            Path to the virtual environment directory
        """
        venv_path = sandbox_path / ".venv"
        if not venv_path.exists() and self._venv_template_path.exists():
            shutil.copytree(self._venv_template_path, venv_path, symlinks=True)
        return venv_path

    def setup_agent_instructions(self, sandbox_path: Path) -> None:
        """Copy AGENTS.md instructions template.

        Args:
            sandbox_path: Path to the sandbox directory
        """
        agent_md_path = sandbox_path / "AGENTS.md"
        if (
            not agent_md_path.exists()
            and self._agent_instructions_template_path.exists()
        ):
            shutil.copy(self._agent_instructions_template_path, agent_md_path)

    def setup_skills(self, sandbox_path: Path) -> None:
        """Copy skills directory to .agent/skills.

        Args:
            sandbox_path: Path to the sandbox directory
        """
        skills_dest = sandbox_path / ".agent" / "skills"
        if self._skills_path.exists() and not skills_dest.exists():
            skills_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self._skills_path, skills_dest)

    def setup_opencode_config(
        self,
        sandbox_path: Path,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        disabled_tools: list[str] | None = None,
    ) -> None:
        """Create opencode.json configuration file for the agent.

        Configures the opencode CLI agent with the LLM provider settings
        from Onyx's configured LLM provider.

        Args:
            sandbox_path: Path to the sandbox directory
            provider: LLM provider type (e.g., "openai", "anthropic")
            model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
            api_key: Optional API key for the provider
            api_base: Optional custom API base URL
            disabled_tools: Optional list of tools to disable (e.g., ["question", "webfetch"])
        """
        config_path = sandbox_path / "opencode.json"
        if config_path.exists():
            return

        # Build opencode model string: provider/model-name
        opencode_model = f"{provider}/{model_name}"

        # Build configuration
        config: dict[str, Any] = {
            "model": opencode_model,
        }

        # Add provider-specific configuration if API key provided
        if api_key:
            provider_config: dict[str, Any] = {"options": {"apiKey": api_key}}
            if api_base:
                provider_config["api"] = api_base
            config["provider"] = {provider: provider_config}

        # Add thinking configuration based on provider
        if provider == "openai":
            if "options" not in config:
                config["options"] = {}
            config["options"].update(
                {
                    "reasoningEffort": "high",
                    "textVerbosity": "low",
                    "reasoningSummary": "auto",
                    "include": ["reasoning.encrypted_content"],
                }
            )
        elif provider == "anthropic":
            if "options" not in config:
                config["options"] = {}
            config["options"]["thinking"] = {
                "type": "enabled",
                "budgetTokens": 16000,
            }
        elif provider == "google":
            if "options" not in config:
                config["options"] = {}
            config["options"].update(
                {
                    "thinking_budget": 16000,
                    "thinking_level": "high",
                }
            )
        elif provider == "bedrock":
            if "options" not in config:
                config["options"] = {}
            config["options"]["thinking"] = {
                "type": "enabled",
                "budgetTokens": 16000,
            }
        elif provider == "azure":
            if "options" not in config:
                config["options"] = {}
            config["options"].update(
                {
                    "reasoningEffort": "high",
                    "textVerbosity": "low",
                    "reasoningSummary": "auto",
                    "include": ["reasoning.encrypted_content"],
                }
            )

        # Set default tool permission
        config["permission"] = {
            "bash": {
                "rm": "deny",
                "curl": "deny",
                "wget": "deny",
                "ssh": "deny",
                "scp": "deny",
                "sftp": "deny",
                "ftp": "deny",
                "telnet": "deny",
                "nc": "deny",
                "netcat": "deny",
            },
            "edit": "allow",
            "write": "allow",
            "read": "allow",
            "grep": "allow",
            "glob": "allow",
            "list": "allow",
            "lsp": "allow",
            "patch": "allow",
            "skill": "allow",
            "question": "allow",
            "webfetch": "allow",
        }

        # Disable specified tools via permissions
        if disabled_tools:
            config["permission"] = {tool: "deny" for tool in disabled_tools}

        config_path.write_text(json.dumps(config, indent=2))

    def cleanup_sandbox_directory(self, sandbox_path: Path) -> None:
        """Remove sandbox directory and all contents.

        Args:
            sandbox_path: Path to the sandbox directory to remove
        """
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)

    def get_outputs_path(self, sandbox_path: Path) -> Path:
        """Return path to outputs directory.

        Args:
            sandbox_path: Path to the sandbox directory

        Returns:
            Path to the outputs directory
        """
        return sandbox_path / "outputs"

    def get_web_path(self, sandbox_path: Path) -> Path:
        """Return path to Next.js web directory.

        Args:
            sandbox_path: Path to the sandbox directory

        Returns:
            Path to the web directory
        """
        return sandbox_path / "outputs" / "web"

    def get_venv_path(self, sandbox_path: Path) -> Path:
        """Return path to virtual environment.

        Args:
            sandbox_path: Path to the sandbox directory

        Returns:
            Path to the .venv directory
        """
        return sandbox_path / ".venv"

    def directory_exists(self, sandbox_path: Path) -> bool:
        """Check if sandbox directory exists.

        Args:
            sandbox_path: Path to check

        Returns:
            True if directory exists and is a directory
        """
        return sandbox_path.exists() and sandbox_path.is_dir()

    def setup_user_uploads_directory(self, sandbox_path: Path) -> Path:
        """Create user uploads directory at user_uploaded_files.

        This directory is used to store files uploaded by the user
        through the chat interface.

        Args:
            sandbox_path: Path to the sandbox directory

        Returns:
            Path to the user uploads directory
        """
        uploads_path = sandbox_path / "user_uploaded_files"
        uploads_path.mkdir(parents=True, exist_ok=True)
        return uploads_path

    def get_user_uploads_path(self, sandbox_path: Path) -> Path:
        """Return path to user uploads directory.

        Args:
            sandbox_path: Path to the sandbox directory

        Returns:
            Path to the user_uploaded_files directory
        """
        return sandbox_path / "user_uploaded_files"
