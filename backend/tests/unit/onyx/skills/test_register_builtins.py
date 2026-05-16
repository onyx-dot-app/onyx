from onyx.skills.builtins import BUILTIN_SLUGS
from onyx.skills.builtins import register_builtin_skills
from onyx.skills.registry import BuiltinSkillRegistry


def test_register_builtin_skills_registers_all_known_slugs() -> None:
    BuiltinSkillRegistry._reset_for_testing()
    register_builtin_skills()

    registry = BuiltinSkillRegistry.instance()
    registered = {skill.slug for skill in registry.list_all()}
    assert registered == set(BUILTIN_SLUGS)


def test_register_builtin_skills_populates_required_metadata() -> None:
    BuiltinSkillRegistry._reset_for_testing()
    register_builtin_skills()

    registry = BuiltinSkillRegistry.instance()
    for slug in BUILTIN_SLUGS:
        skill = registry.get(slug)
        assert skill is not None
        assert skill.name
        assert skill.description
        assert skill.source_dir.is_dir()


def test_company_search_is_marked_as_template() -> None:
    BuiltinSkillRegistry._reset_for_testing()
    register_builtin_skills()

    registry = BuiltinSkillRegistry.instance()
    company_search = registry.get("company-search")
    assert company_search is not None
    assert company_search.has_template is True

    pptx = registry.get("pptx")
    assert pptx is not None
    assert pptx.has_template is False
