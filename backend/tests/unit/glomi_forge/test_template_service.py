from onyx.db.enums import ForgeArtifactType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.glomi_forge.services.template_service import TemplateService
from onyx.tracing.flows import LLMFlow


def test_resolve_landing_page() -> None:
    descriptor = TemplateService().resolve(ForgeArtifactType.LANDING_PAGE)

    assert descriptor.snapshot == "glomi-landing-page"
    assert descriptor.preview_port == 3000
    assert "AGENTS" in descriptor.agents_md or len(descriptor.agents_md) > 0


def test_new_error_codes_and_flow_exist() -> None:
    assert OnyxErrorCode.FORGE_PROVISION_FAILED.status_code == 502
    assert LLMFlow.FORGE_SPEC_GENERATION.value == "build_spec_generation"
