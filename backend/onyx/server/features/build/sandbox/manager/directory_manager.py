"""Directory management for sandbox lifecycle.

Supports user-shared sandbox model where:
- One sandbox per user with shared files/ directory
- Per-session workspaces under sessions/$session_id/
"""

import json
import shutil
from pathlib import Path

from onyx.server.features.build.sandbox.util.agent_instructions import (
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_config,
)
from onyx.server.features.build.sandbox.util.persona_mapping import (
    generate_user_identity_content,
)
from onyx.server.features.build.sandbox.util.persona_mapping import get_persona_info
from onyx.server.features.build.sandbox.util.persona_mapping import ORG_INFO_AGENTS_MD
from onyx.server.features.build.sandbox.util.persona_mapping import (
    ORGANIZATION_STRUCTURE,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class DirectoryManager:
    """Manages sandbox directory creation and cleanup.

    Responsible for:
    - Creating sandbox directory structure (user-level)
    - Creating session workspace directories (session-level)
    - Setting up symlinks to knowledge files
    - Copying templates (outputs, venv, skills, AGENTS.md)
    - Cleaning up sandbox/session directories on termination

    Directory Structure:
        $base_path/$sandbox_id/
        ├── files/                     # Symlink to knowledge/source files (SHARED)
        └── sessions/
            ├── $session_id_1/         # Per-session workspace
            │   ├── outputs/           # Agent output (from template or snapshot)
            │   │   └── web/           # Next.js app
            │   ├── .venv/             # Python virtual environment
            │   ├── .agent/skills/     # Opencode skills
            │   ├── files/             # Symlink to sandbox-level files/ (SHARED)
            │   ├── AGENTS.md          # Agent instructions
            │   ├── opencode.json      # LLM config
            │   └── attachments/
            └── $session_id_2/
                └── ...
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

    def create_sandbox_directory(self, sandbox_id: str) -> Path:
        """Create sandbox directory structure (user-level).

        Creates the base directory for a user's sandbox:
        {base_path}/{sandbox_id}/
        ├── files/                      # Symlink to knowledge/source files (set up separately)
        └── sessions/                   # Container for per-session workspaces

        NOTE: This only creates the sandbox-level structure.
        Call create_session_directory() to create per-session workspaces.

        Args:
            sandbox_id: Unique identifier for the sandbox

        Returns:
            Path to the created sandbox directory
        """
        sandbox_path = self._base_path / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        # Create sessions directory for per-session workspaces
        (sandbox_path / "sessions").mkdir(exist_ok=True)
        return sandbox_path

    def create_session_directory(self, sandbox_path: Path, session_id: str) -> Path:
        """Create session workspace directory structure.

        Creates a per-session workspace within the sandbox:
        {sandbox_path}/sessions/{session_id}/
        ├── outputs/                    # Working directory from template
        │   ├── web/                    # Next.js app
        │   ├── slides/
        │   ├── markdown/
        │   └── graphs/
        ├── .venv/                      # Python virtual environment
        ├── AGENTS.md                   # Agent instructions
        ├── opencode.json               # LLM config (set up separately)
        ├── attachments/                # User-uploaded files
        └── .opencode/
            └── skills/                 # Agent skills

        NOTE: This creates the directory structure but doesn't copy templates.
        Call setup_outputs_directory(), setup_venv(), etc. to set up contents.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Unique identifier for the session

        Returns:
            Path to the created session workspace directory
        """
        session_path = sandbox_path / "sessions" / session_id
        session_path.mkdir(parents=True, exist_ok=True)
        return session_path

    def cleanup_session_directory(self, sandbox_path: Path, session_id: str) -> None:
        """Remove session workspace directory and all contents.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Session ID to clean up
        """
        session_path = sandbox_path / "sessions" / session_id
        if session_path.exists():
            shutil.rmtree(session_path)
            logger.info(f"Cleaned up session directory: {session_path}")

    def get_session_path(self, sandbox_path: Path, session_id: str) -> Path:
        """Get path to session workspace.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Session ID

        Returns:
            Path to sessions/$session_id/
        """
        return sandbox_path / "sessions" / session_id

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

    def setup_org_info(
        self,
        session_path: Path,
        user_work_area: str | None,
        user_level: str | None,
    ) -> None:
        """Create org_info directory with organizational context files.

        Creates an org_info/ directory at the session root level with:
        - AGENTS.md: Description of available org info files
        - user_identity_profile.txt: User's persona information
        - organization_structure.json: Org hierarchy with managers and reports

        Uses shared constants from persona_mapping module as single source of truth.

        Args:
            session_path: Path to the session directory
            user_work_area: User's work area (e.g., "engineering", "product")
            user_level: User's level (e.g., "ic", "manager")
        """
        # Get persona info from mapping
        persona = get_persona_info(user_work_area, user_level)
        if not persona:
            logger.debug(
                f"No persona found for work_area={user_work_area}, "
                f"level={user_level}, skipping org_info setup"
            )
            return

        # Create org_info directory at session root
        org_info_dir = session_path / "org_info"
        org_info_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. AGENTS.md - Description of org info contents
            (org_info_dir / "AGENTS.md").write_text(ORG_INFO_AGENTS_MD)

            # 2. user_identity_profile.txt - User's persona
            (org_info_dir / "user_identity_profile.txt").write_text(
                generate_user_identity_content(persona)
            )

            # 3. organization_structure.json - Org hierarchy
            (org_info_dir / "organization_structure.json").write_text(
                json.dumps(ORGANIZATION_STRUCTURE, indent=2)
            )

            logger.info(
                f"Created org_info with identity: {persona['name']} <{persona['email']}>"
            )
        except Exception as e:
            # Don't fail provisioning if org_info setup fails
            logger.warning(f"Failed to setup org_info: {e}")

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
                raise RuntimeError(
                    f"Outputs template path does not exist: {self._outputs_template_path}"
                )

        # Create additional output directories for generated content
        (output_dir / "markdown").mkdir(parents=True, exist_ok=True)
        # TODO: no images for now
        # (output_dir / "slides").mkdir(parents=True, exist_ok=True)
        # TODO: No graphs for now
        # (output_dir / "graphs").mkdir(parents=True, exist_ok=True)

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
        use_demo_data: bool = False,
        include_org_info: bool = False,
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
            use_demo_data: If True, exclude user context from AGENTS.md
            include_org_info: Whether to include the org_info section (demo data mode)
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
            use_demo_data=use_demo_data,
            include_org_info=include_org_info,
        )

        # Write the generated content
        agent_md_path.write_text(content)
        logger.debug(f"Generated AGENTS.md at {agent_md_path}")

    def setup_skills(self, sandbox_path: Path, overwrite: bool = True) -> None:
        """Copy skills directory to .opencode/skills.

        Copies all skills from the source skills directory to the sandbox's
        .opencode/skills directory. If the destination already exists, it will
        be removed and recreated to ensure skills are up-to-date.

        Args:
            sandbox_path: Path to the sandbox directory
            overwrite: If True, overwrite existing skills. If False, preserve existing skills.
        """
        skills_dest = sandbox_path / ".opencode" / "skills"

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
        dev_mode: bool = False,
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
            dev_mode: If True, allow all external directories (local dev).
                      If False (default), only whitelist /workspace/files and /workspace/demo_data.
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
            dev_mode=dev_mode,
        )

        config_json = json.dumps(config, indent=2)
        config_path.write_text(config_json)

    def cleanup_sandbox_directory(self, sandbox_path: Path) -> None:
        """Remove sandbox directory and all contents.

        Args:
            sandbox_path: Path to the sandbox directory to remove
        """
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)

    def get_outputs_path(
        self, sandbox_path: Path, session_id: str | None = None
    ) -> Path:
        """Return path to outputs directory.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Optional session ID for session-specific outputs

        Returns:
            Path to the outputs directory
        """
        if session_id:
            return sandbox_path / "sessions" / session_id / "outputs"
        return sandbox_path / "outputs"

    def get_web_path(self, sandbox_path: Path, session_id: str) -> Path:
        """Return path to Next.js web directory.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Optional session ID for session-specific web directory

        Returns:
            Path to the web directory
        """
        if session_id:
            return sandbox_path / "sessions" / session_id / "outputs" / "web"
        return sandbox_path / "outputs" / "web"

    def get_venv_path(self, sandbox_path: Path, session_id: str | None = None) -> Path:
        """Return path to virtual environment.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Optional session ID for session-specific venv

        Returns:
            Path to the .venv directory
        """
        if session_id:
            return sandbox_path / "sessions" / session_id / ".venv"
        return sandbox_path / ".venv"

    def directory_exists(self, sandbox_path: Path) -> bool:
        """Check if sandbox directory exists.

        Args:
            sandbox_path: Path to check

        Returns:
            True if directory exists and is a directory
        """
        return sandbox_path.exists() and sandbox_path.is_dir()

    def session_exists(self, sandbox_path: Path, session_id: str) -> bool:
        """Check if session workspace exists.

        Args:
            sandbox_path: Path to sandbox directory
            session_id: Session ID to check

        Returns:
            True if session directory exists
        """
        session_path = sandbox_path / "sessions" / session_id
        return session_path.exists() and session_path.is_dir()

    def setup_attachments_directory(
        self, sandbox_path: Path, session_id: str | None = None
    ) -> Path:
        """Create attachments directory for user-uploaded files.

        This directory is used to store files uploaded by the user
        through the chat interface.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Optional session ID for session-specific uploads

        Returns:
            Path to the attachments directory
        """
        if session_id:
            attachments_path = sandbox_path / "sessions" / session_id / "attachments"
        else:
            attachments_path = sandbox_path / "attachments"
        attachments_path.mkdir(parents=True, exist_ok=True)
        return attachments_path

    def get_attachments_path(
        self, sandbox_path: Path, session_id: str | None = None
    ) -> Path:
        """Return path to attachments directory.

        Args:
            sandbox_path: Path to the sandbox directory
            session_id: Optional session ID for session-specific uploads

        Returns:
            Path to the attachments directory
        """
        if session_id:
            return sandbox_path / "sessions" / session_id / "attachments"
        return sandbox_path / "attachments"
