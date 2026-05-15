"""Register on-disk built-in skills with the in-memory registry at boot.

Built-in skill source files live in the API server image at
``SKILLS_TEMPLATE_PATH``. ``register_builtins()`` is idempotent for the lifetime
of a process — the registry rejects duplicate slugs — so callers (lifespan,
tests) should reset the registry before re-registering.
"""

from pathlib import Path

from onyx.server.features.build.configs import SKILLS_TEMPLATE_PATH
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.utils.logger import setup_logger

logger = setup_logger()


BUILTIN_SLUGS: tuple[str, ...] = ("pptx", "image-generation", "company-search")


def register_builtin_skills() -> None:
    """Register every slug under ``BUILTIN_SLUGS`` with the registry.

    Each skill's metadata is read from its on-disk ``SKILL.md`` /
    ``SKILL.md.template`` frontmatter (see ``BuiltinSkillRegistry.register``).
    All three skills are unconditionally available — the company-search
    template handles the "no connected sources" case gracefully, so no
    DB-driven gating is needed.
    """
    registry = BuiltinSkillRegistry.instance()
    base = Path(SKILLS_TEMPLATE_PATH)
    for slug in BUILTIN_SLUGS:
        try:
            registry.register(slug=slug, source_dir=base / slug)
        except ValueError as e:
            logger.error("Failed to register built-in skill %s: %s", slug, e)
            raise
