"""Tests for LLM recommendations config resolution (remote vs bundled)."""

from datetime import datetime
from datetime import timezone
from unittest.mock import patch

from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.auto_update_service import fetch_llm_recommendations
from onyx.llm.well_known_providers.auto_update_service import (
    load_bundled_recommendations,
)


def _make_config(updated_at: datetime) -> LLMRecommendations:
    return LLMRecommendations(
        version="test",
        updated_at=updated_at,
        providers={},
    )


_MODULE = "onyx.llm.well_known_providers.auto_update_service"


def test_remote_wins_when_newer() -> None:
    remote = _make_config(datetime(2026, 7, 1, tzinfo=timezone.utc))
    bundled = _make_config(datetime(2026, 6, 1, tzinfo=timezone.utc))
    with (
        patch(f"{_MODULE}.fetch_llm_recommendations_from_github", return_value=remote),
        patch(f"{_MODULE}.load_bundled_recommendations", return_value=bundled),
    ):
        assert fetch_llm_recommendations() is remote


def test_bundled_wins_when_newer() -> None:
    """A fresh release must not be held back by a stale remote config."""
    remote = _make_config(datetime(2026, 6, 1, tzinfo=timezone.utc))
    bundled = _make_config(datetime(2026, 7, 1, tzinfo=timezone.utc))
    with (
        patch(f"{_MODULE}.fetch_llm_recommendations_from_github", return_value=remote),
        patch(f"{_MODULE}.load_bundled_recommendations", return_value=bundled),
    ):
        assert fetch_llm_recommendations() is bundled


def test_bundled_used_when_remote_unavailable() -> None:
    bundled = _make_config(datetime(2026, 7, 1, tzinfo=timezone.utc))
    with (
        patch(f"{_MODULE}.fetch_llm_recommendations_from_github", return_value=None),
        patch(f"{_MODULE}.load_bundled_recommendations", return_value=bundled),
    ):
        assert fetch_llm_recommendations() is bundled


def test_none_when_both_unavailable() -> None:
    with (
        patch(f"{_MODULE}.fetch_llm_recommendations_from_github", return_value=None),
        patch(f"{_MODULE}.load_bundled_recommendations", return_value=None),
    ):
        assert fetch_llm_recommendations() is None


def test_naive_timestamps_compare_safely() -> None:
    """A config authored without an explicit timezone must not crash the
    comparison against a tz-aware one."""
    remote = _make_config(datetime(2026, 6, 1, tzinfo=timezone.utc))
    bundled = _make_config(datetime(2026, 7, 1))  # naive
    with (
        patch(f"{_MODULE}.fetch_llm_recommendations_from_github", return_value=remote),
        patch(f"{_MODULE}.load_bundled_recommendations", return_value=bundled),
    ):
        assert fetch_llm_recommendations() is bundled


def test_bundled_file_parses_and_includes_current_anthropic_models() -> None:
    """The shipped recommended-models.json must be valid and carry the
    current Anthropic generation (regression: Fable 5 / Sonnet 5 were
    missing, so auto-mode providers never offered them)."""
    bundled = load_bundled_recommendations()
    assert bundled is not None
    anthropic_models = {m.name for m in bundled.get_visible_models("anthropic")}
    assert "claude-fable-5" in anthropic_models
    assert "claude-sonnet-5" in anthropic_models
