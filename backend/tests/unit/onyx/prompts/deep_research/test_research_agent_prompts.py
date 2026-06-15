from onyx.prompts.deep_research.dr_tool_prompts import OPEN_URLS_TOOL_DESCRIPTION
from onyx.prompts.deep_research.dr_tool_prompts import WEB_SEARCH_TOOL_DESCRIPTION
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT
from onyx.prompts.deep_research.research_agent import RESEARCH_AGENT_PROMPT_REASONING
from onyx.prompts.deep_research.research_agent import RESEARCH_REPORT_PROMPT


def test_deep_research_web_tool_description_contains_query_strategy() -> None:
    assert "query portfolio" in WEB_SEARCH_TOOL_DESCRIPTION
    assert "Chinese" in WEB_SEARCH_TOOL_DESCRIPTION
    assert "Source routing" in WEB_SEARCH_TOOL_DESCRIPTION
    assert "mode=deep" in WEB_SEARCH_TOOL_DESCRIPTION


def test_deep_research_open_url_description_contains_evidence_reading() -> None:
    assert "Evidence reading with open_url" in OPEN_URLS_TOOL_DESCRIPTION
    assert "snippets" in OPEN_URLS_TOOL_DESCRIPTION


def test_research_agent_prompts_require_evidence_pack() -> None:
    rendered = RESEARCH_AGENT_PROMPT.format(
        available_tools="web_search, open_url",
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        optional_internal_search_tool_description="",
        optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION,
        optional_open_url_tool_description=OPEN_URLS_TOOL_DESCRIPTION,
    )
    reasoning_rendered = RESEARCH_AGENT_PROMPT_REASONING.format(
        available_tools="web_search, open_url",
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        optional_internal_search_tool_description="",
        optional_web_search_tool_description=WEB_SEARCH_TOOL_DESCRIPTION,
        optional_open_url_tool_description=OPEN_URLS_TOOL_DESCRIPTION,
    )
    assert "Research agent evidence work" in rendered
    assert "Evidence Pack" in rendered
    assert "Research agent evidence work" in reasoning_rendered


def test_research_report_prompt_preserves_conflicts_and_gaps() -> None:
    assert "conflicts" in RESEARCH_REPORT_PROMPT.lower()
    assert "remaining gaps" in RESEARCH_REPORT_PROMPT.lower()
    assert "source context" in RESEARCH_REPORT_PROMPT.lower()
