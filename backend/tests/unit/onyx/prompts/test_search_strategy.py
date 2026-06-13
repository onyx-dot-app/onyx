from onyx.prompts.search_strategy import CHAT_SEARCH_STRATEGY_GUIDANCE
from onyx.prompts.search_strategy import DEEP_RESEARCH_FINAL_REPORT_GUIDANCE
from onyx.prompts.search_strategy import DEEP_RESEARCH_PLAN_GUIDANCE
from onyx.prompts.search_strategy import EVIDENCE_EVALUATION_GUIDANCE
from onyx.prompts.search_strategy import OPEN_URL_EVIDENCE_GUIDANCE
from onyx.prompts.search_strategy import QUERY_PORTFOLIO_GUIDANCE
from onyx.prompts.search_strategy import RESEARCH_AGENT_EVIDENCE_GUIDANCE
from onyx.prompts.search_strategy import SOURCE_ROUTING_GUIDANCE


def test_chat_search_strategy_has_required_decision_points() -> None:
    assert "Search intent" in CHAT_SEARCH_STRATEGY_GUIDANCE
    assert "Freshness" in CHAT_SEARCH_STRATEGY_GUIDANCE
    assert "Do not search" in CHAT_SEARCH_STRATEGY_GUIDANCE
    assert "中文" in CHAT_SEARCH_STRATEGY_GUIDANCE


def test_query_portfolio_guidance_mentions_bilingual_and_source_queries() -> None:
    assert "query portfolio" in QUERY_PORTFOLIO_GUIDANCE
    assert "Chinese" in QUERY_PORTFOLIO_GUIDANCE
    assert "English" in QUERY_PORTFOLIO_GUIDANCE
    assert "site:" in QUERY_PORTFOLIO_GUIDANCE


def test_source_and_evidence_guidance_cover_authority_and_conflicts() -> None:
    combined = SOURCE_ROUTING_GUIDANCE + EVIDENCE_EVALUATION_GUIDANCE
    assert "official" in combined.lower()
    assert "primary" in combined.lower()
    assert "conflict" in combined.lower()
    assert "freshness" in combined.lower()


def test_open_url_guidance_requires_reading_promising_pages() -> None:
    assert "open_url" in OPEN_URL_EVIDENCE_GUIDANCE
    assert "snippets" in OPEN_URL_EVIDENCE_GUIDANCE
    assert "reliable" in OPEN_URL_EVIDENCE_GUIDANCE


def test_deep_research_guidance_contains_chinese_report_expectations() -> None:
    combined = (
        DEEP_RESEARCH_PLAN_GUIDANCE
        + RESEARCH_AGENT_EVIDENCE_GUIDANCE
        + DEEP_RESEARCH_FINAL_REPORT_GUIDANCE
    )
    assert "information gaps" in combined
    assert "Evidence Pack" in combined
    assert "摘要" in combined
    assert "关键结论" in combined
