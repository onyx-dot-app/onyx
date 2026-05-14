from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.utils.logger import setup_logger

logger = setup_logger()


class SkillManifestEntry(BaseModel):
    slug: str
    name: str
    description: str
    source: Literal["builtin", "custom"]


class SkillsManifest(BaseModel):
    builtin: list[SkillManifestEntry]
    custom: list[SkillManifestEntry]


def materialize_skills(
    session_dir: Path,
    user: User | None,  # noqa: ARG001 — per-user filtering lands with custom skills
    db: Session,
    runtime_builtins_path: Path,
    render_ctx: Any = None,  # noqa: ARG001 — populated by template renderer (P1.052)
) -> SkillsManifest:
    """Materialize available skills into the session's `.agents/skills` directory."""
    skills_dir = session_dir / ".agents" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    builtin_entries: list[SkillManifestEntry] = []
    for skill in BuiltinSkillRegistry.instance().list_available(db):
        if skill.has_template:
            # Templated skills require the render pipeline (P1.052) before
            # they can be materialized into a session.
            logger.debug(
                "Skipping templated built-in skill %s (renderer not yet available)",
                skill.slug,
            )
            continue

        link_path = skills_dir / skill.slug
        target = runtime_builtins_path / skill.slug

        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        link_path.symlink_to(target)

        builtin_entries.append(
            SkillManifestEntry(
                slug=skill.slug,
                name=skill.name,
                description=skill.description,
                source="builtin",
            )
        )

    manifest = SkillsManifest(builtin=builtin_entries, custom=[])
    (skills_dir / ".skills_manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest
