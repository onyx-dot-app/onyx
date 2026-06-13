from onyx.evals.glomi_search_research_benchmark import BENCHMARK_CASES
from onyx.evals.glomi_search_research_benchmark import BenchmarkCategory
from onyx.evals.glomi_search_research_benchmark import BenchmarkProfile


def test_benchmark_has_phase_one_size() -> None:
    assert len(BENCHMARK_CASES) >= 20


def test_benchmark_covers_chat_and_deep_profiles() -> None:
    profiles = {case.profile for case in BENCHMARK_CASES}
    assert BenchmarkProfile.CHAT_LITE in profiles
    assert BenchmarkProfile.DEEP_RESEARCH in profiles


def test_benchmark_covers_required_categories() -> None:
    categories = {case.category for case in BENCHMARK_CASES}
    assert BenchmarkCategory.FRESH_FACT in categories
    assert BenchmarkCategory.POLICY_RESEARCH in categories
    assert BenchmarkCategory.PRODUCT_COMPARISON in categories
    assert BenchmarkCategory.TECHNICAL_RESEARCH in categories
    assert BenchmarkCategory.MARKET_RESEARCH in categories
    assert BenchmarkCategory.FACT_CHECK in categories


def test_each_case_has_expected_behaviors_and_tools() -> None:
    for case in BENCHMARK_CASES:
        assert case.id
        assert case.prompt
        assert case.expected_behaviors
        assert case.expected_tools


def test_chinese_cases_are_not_english_only() -> None:
    chinese_count = sum(
        any("\u4e00" <= char <= "\u9fff" for char in case.prompt)
        for case in BENCHMARK_CASES
    )
    assert chinese_count == len(BENCHMARK_CASES)
