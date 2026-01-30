"""Template and configuration utilities for sandbox environments.

Contains utilities for:
- Building sandbox templates (Next.js, venv)
- Generating agent instructions (AGENTS.md)
- Generating opencode configuration
"""

from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_knowledge_sources_section,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_skills_section,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_user_context,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    extract_skill_description,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    generate_agent_instructions,
)
from onyx.server.features.build.sandbox.util.agent_instructions import (
    get_provider_display_name,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_opencode_config,
)

__all__ = [
    "build_knowledge_sources_section",
    "build_opencode_config",
    "build_skills_section",
    "build_user_context",
    "extract_skill_description",
    "generate_agent_instructions",
    "get_provider_display_name",
]
