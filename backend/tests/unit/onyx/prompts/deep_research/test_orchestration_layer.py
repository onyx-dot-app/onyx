from onyx.prompts.deep_research.orchestration_layer import FINAL_REPORT_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT
from onyx.prompts.deep_research.orchestration_layer import (
    ORCHESTRATOR_PROMPT_REASONING,
)
from onyx.prompts.deep_research.orchestration_layer import RESEARCH_PLAN_PROMPT


def test_research_plan_prompt_contains_information_gap_planning() -> None:
    rendered = RESEARCH_PLAN_PROMPT.format(current_datetime="June 13, 2026")
    assert "information gaps" in rendered
    assert "source types" in rendered
    assert "Chinese plus English" in rendered


def test_orchestrator_prompts_contain_cycle_evaluation_rules() -> None:
    rendered = ORCHESTRATOR_PROMPT.format(
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        max_cycles=3,
        research_plan="1. 调研市场\n2. 调研政策",
        internal_search_research_task_guidance="",
    )
    reasoning_rendered = ORCHESTRATOR_PROMPT_REASONING.format(
        current_datetime="June 13, 2026",
        current_cycle_count=1,
        max_cycles=3,
        research_plan="1. 调研市场\n2. 调研政策",
        internal_search_research_task_guidance="",
    )
    assert "Deep research orchestration" in rendered
    assert "information gaps remain" in rendered
    assert "Deep research orchestration" in reasoning_rendered
    assert "information gaps remain" in reasoning_rendered


def test_final_report_prompt_contains_chinese_report_structure() -> None:
    rendered = FINAL_REPORT_PROMPT.format(current_datetime="June 13, 2026")
    assert "Chinese final report shape" in rendered
    assert "摘要" in rendered
    assert "关键结论" in rendered
    assert "inline citations" in rendered
