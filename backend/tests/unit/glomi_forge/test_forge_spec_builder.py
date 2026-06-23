from types import SimpleNamespace

from onyx.db.enums import ForgeArtifactType
from onyx.glomi_forge.services.forge_spec_builder import ForgeSpecBuilder


class _FakeLLM:
    def invoke(self, prompt, structured_response_format=None, **kwargs):
        self.prompt = prompt
        self.structured_response_format = structured_response_format
        self.kwargs = kwargs
        content = (
            '{"title":"产品发布页","goal":"中文落地页",'
            '"requirements":["Hero","CTA"],'
            '"acceptance_criteria":["可预览"],"visual_style":["科技感"]}'
        )
        return SimpleNamespace(
            choice=SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None)
            )
        )


def test_build_parses_structured_output() -> None:
    spec = ForgeSpecBuilder(_FakeLLM()).build(
        "帮我做一个产品发布页",
        ForgeArtifactType.LANDING_PAGE,
    )

    assert spec.title == "产品发布页"
    assert "Hero" in spec.requirements
