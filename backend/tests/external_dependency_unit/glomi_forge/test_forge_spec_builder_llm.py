import os

import pytest

from onyx.db.enums import ForgeArtifactType
from onyx.glomi_forge.services.forge_spec_builder import ForgeSpecBuilder
from onyx.llm.factory import get_default_llm


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="needs OpenAI key",
)
def test_real_llm_produces_valid_spec() -> None:
    spec = ForgeSpecBuilder(get_default_llm()).build(
        "帮我做一个面向年轻人的国潮咖啡品牌中文落地页",
        ForgeArtifactType.LANDING_PAGE,
    )

    assert spec.title
    assert spec.goal
