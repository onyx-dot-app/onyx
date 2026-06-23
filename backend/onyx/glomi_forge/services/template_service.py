from pathlib import Path

from pydantic import BaseModel

from onyx.db.enums import ForgeArtifactType
from onyx.glomi_forge.configs import GLOMI_FORGE_DEFAULT_SNAPSHOT
from onyx.glomi_forge.configs import LANDING_PAGE_TEMPLATE_ID
from onyx.glomi_forge.configs import SANDBOX_PREVIEW_PORT

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class TemplateDescriptor(BaseModel):
    template_id: str
    artifact_type: ForgeArtifactType
    snapshot: str
    preview_port: int
    agents_md: str
    system_md: str
    output_contract: str


def _read(template_dir: Path, name: str) -> str:
    return (template_dir / name).read_text(encoding="utf-8")


class TemplateService:
    """Resolve an artifact type to the template shipped by sub-project A."""

    def resolve(self, artifact_type: ForgeArtifactType) -> TemplateDescriptor:
        if artifact_type != ForgeArtifactType.LANDING_PAGE:
            raise ValueError(
                f"No Glomi Forge template for artifact_type={artifact_type}"
            )

        template_dir = _TEMPLATES_DIR / LANDING_PAGE_TEMPLATE_ID
        return TemplateDescriptor(
            template_id=LANDING_PAGE_TEMPLATE_ID,
            artifact_type=ForgeArtifactType.LANDING_PAGE,
            snapshot=GLOMI_FORGE_DEFAULT_SNAPSHOT,
            preview_port=SANDBOX_PREVIEW_PORT,
            agents_md=_read(template_dir, "AGENTS.md"),
            system_md=_read(template_dir, "SYSTEM.md"),
            output_contract=_read(template_dir, "output_contract.md"),
        )
