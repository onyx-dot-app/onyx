import os

import pytest
import requests

from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.glomi_forge import create_glomi_forge_session
from onyx.db.glomi_forge import get_glomi_forge_session
from onyx.glomi_forge.providers.builder.pi_builder_adapter import PiBuilderAdapter
from onyx.glomi_forge.providers.sandbox.daytona_provider import DaytonaSandboxProvider
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.services.forge_orchestrator import ForgeOrchestrator
from onyx.glomi_forge.services.template_service import TemplateService

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DAYTONA_API_URL") and os.environ.get("DAYTONA_API_KEY")),
    reason="needs reachable Daytona control plane and glomi-landing-page snapshot",
)


def test_landing_page_end_to_end(db_session) -> None:
    spec = ForgeSpec(
        title="测试落地页",
        goal="生成一个含 Hero/CTA 的中文落地页",
        requirements=["Hero 区", "CTA"],
        acceptance_criteria=["可预览"],
    )
    session = create_glomi_forge_session(
        db_session,
        user_id=None,
        artifact_type=ForgeArtifactType.LANDING_PAGE,
        template_id="landing_page",
        spec=spec,
        title=spec.title,
    )
    provider = DaytonaSandboxProvider()

    ForgeOrchestrator(
        db_session,
        provider,
        PiBuilderAdapter(provider),
        TemplateService(),
    ).run(session.id)

    again = get_glomi_forge_session(db_session, session.id)
    assert again is not None
    assert again.status == GlomiForgeStatus.COMPLETED
    assert again.preview_url

    response = requests.get(again.preview_url, timeout=30)
    assert response.status_code == 200
