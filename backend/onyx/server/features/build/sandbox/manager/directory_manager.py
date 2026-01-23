"""Directory management for sandbox lifecycle."""

import json
import shutil
from pathlib import Path

from onyx.server.features.build.sandbox.templates.agent_instructions import (
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.templates.opencode_config import (
    build_opencode_config,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


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

    def setup_agent_instructions(
        self,
        sandbox_path: Path,
        provider: str | None = None,
        model_name: str | None = None,
        nextjs_port: int | None = None,
        disabled_tools: list[str] | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> None:
        """Generate AGENTS.md with dynamic configuration.

        Reads the template file and replaces placeholders with actual values
        including user personalization, LLM configuration, runtime settings,
        and dynamically discovered knowledge sources.

        Args:
            sandbox_path: Path to the sandbox directory
            provider: LLM provider type (e.g., "openai", "anthropic")
            model_name: Model name (e.g., "claude-sonnet-4-5", "gpt-4o")
            nextjs_port: Port for Next.js development server
            disabled_tools: List of disabled tools
            user_name: User's name for personalization
            user_role: User's role/title for personalization
        """
        agent_md_path = sandbox_path / "AGENTS.md"
        if agent_md_path.exists():
            return

        # Get the files path (symlink to knowledge sources)
        files_path = sandbox_path / "files"

        # Use shared utility to generate content
        content = generate_agent_instructions(
            template_path=self._agent_instructions_template_path,
            skills_path=self._skills_path,
            files_path=files_path if files_path.exists() else None,
            provider=provider,
            model_name=model_name,
            nextjs_port=nextjs_port,
            disabled_tools=disabled_tools,
            user_name=user_name,
            user_role=user_role,
        )

        # Write the generated content
        agent_md_path.write_text(content)
        logger.debug(f"Generated AGENTS.md at {agent_md_path}")

    def setup_skills(self, sandbox_path: Path, overwrite: bool = True) -> None:
        """Copy skills directory to .agent/skills.

        Copies all skills from the source skills directory to the sandbox's
        .agent/skills directory. If the destination already exists, it will
        be removed and recreated to ensure skills are up-to-date.

        Args:
            sandbox_path: Path to the sandbox directory
            overwrite: If True, overwrite existing skills. If False, preserve existing skills.
        """
        skills_dest = sandbox_path / ".agent" / "skills"

        if not self._skills_path.exists():
            logger.warning(
                f"Skills path {self._skills_path} does not exist, skipping skills setup"
            )
            return

        if not overwrite and skills_dest.exists():
            logger.debug(
                f"Skills directory already exists at {skills_dest}, skipping skills setup"
            )
            return

        try:
            # Remove existing skills directory if it exists to ensure fresh copy
            if skills_dest.exists():
                shutil.rmtree(skills_dest)

            # Create parent directory and copy skills
            skills_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self._skills_path, skills_dest)

            # Verify the copy succeeded
            if not skills_dest.exists():
                logger.error(
                    f"Skills copy failed: destination {skills_dest} does not exist after copy"
                )
        except Exception as e:
            logger.error(
                f"Failed to copy skills from {self._skills_path} to {skills_dest}: {e}",
                exc_info=True,
            )
            raise

    def setup_opencode_config(
        self,
        sandbox_path: Path,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        disabled_tools: list[str] | None = None,
        overwrite: bool = True,
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
            overwrite: If True, overwrite existing config. If False, preserve existing config.
        """
        config_path = sandbox_path / "opencode.json"
        if not overwrite and config_path.exists():
            logger.debug(
                f"opencode.json already exists at {config_path}, skipping config setup"
            )
            return

        # Use shared config builder
        config = build_opencode_config(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
            disabled_tools=disabled_tools,
        )

        config_json = json.dumps(config, indent=2)
        config_path.write_text(config_json)
        logger.debug(f"Created opencode.json at {config_path}:\n{config_json}")

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
