"""Register on-disk built-in skills with the in-memory registry at boot.

``register_builtin_skills()`` must be called exactly once per process;
tests that need to re-register should call
``BuiltinSkillRegistry._reset_for_testing()`` first.
"""

from pathlib import Path

from onyx.server.features.build.configs import SKILLS_TEMPLATE_PATH
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.utils.logger import setup_logger

logger = setup_logger()


BUILTIN_SLUGS: tuple[str, ...] = ("pptx", "image-generation", "company-search")


def register_builtin_skills() -> None:
    registry = BuiltinSkillRegistry.instance()
    base = Path(SKILLS_TEMPLATE_PATH)
    for slug in BUILTIN_SLUGS:
        try:
            registry.register(slug=slug, source_dir=base / slug)
        except ValueError as e:
            logger.error("Failed to register built-in skill %s: %s", slug, e)
            raise
