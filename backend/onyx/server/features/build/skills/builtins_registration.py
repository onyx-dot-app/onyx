from pathlib import Path

from sqlalchemy.orm import Session

from onyx.db.image_generation import get_default_image_generation_config
from onyx.skills.registry import BuiltinSkillRegistry


def _image_generation_available(db: Session) -> bool:
    return get_default_image_generation_config(db) is not None


def register_craft_builtins(registry: BuiltinSkillRegistry) -> None:
    reserved = registry.reserved_slugs()
    skills_dir = Path(__file__).parent
    if "company-search" not in reserved:
        registry.register(
            slug="company-search",
            source_dir=skills_dir / "company-search",
        )
    if "pptx" not in reserved:
        registry.register(slug="pptx", source_dir=skills_dir / "pptx")
    if "image-generation" not in reserved:
        registry.register(
            slug="image-generation",
            source_dir=skills_dir / "image-generation",
            is_available=_image_generation_available,
            unavailable_reason="No image generation provider configured.",
        )
