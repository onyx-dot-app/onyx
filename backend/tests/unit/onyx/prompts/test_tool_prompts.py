from onyx.prompts.tool_prompts import OPEN_URLS_GUIDANCE
from onyx.prompts.tool_prompts import TOOL_DESCRIPTION_SEARCH_GUIDANCE
from onyx.prompts.tool_prompts import WEB_SEARCH_GUIDANCE


def test_general_search_guidance_contains_search_intent_rules() -> None:
    assert "Search intent" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "Do not search" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "中文" in TOOL_DESCRIPTION_SEARCH_GUIDANCE


def test_general_search_guidance_contains_adaptive_answer_policy() -> None:
    assert "Ordinary chat research answers" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "Do not use a fixed template" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "deep search does not mean a long answer" in TOOL_DESCRIPTION_SEARCH_GUIDANCE
    assert "synthesize the useful judgment" in TOOL_DESCRIPTION_SEARCH_GUIDANCE


def test_web_search_guidance_contains_query_portfolio_and_source_routing() -> None:
    rendered = WEB_SEARCH_GUIDANCE.format(site_colon_disabled="")
    assert "query portfolio" in rendered
    assert "Source routing" in rendered
    assert "Evidence evaluation" in rendered
    assert "mode=lite" in rendered
    assert "mode=medium" in rendered
    assert "mode=deep" in rendered


def test_open_url_guidance_contains_evidence_reading_rules() -> None:
    assert "Evidence reading with open_url" in OPEN_URLS_GUIDANCE
    assert "Do not rely only on snippets" in OPEN_URLS_GUIDANCE
    assert "near-duplicate" in OPEN_URLS_GUIDANCE
