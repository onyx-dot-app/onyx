"""Unit tests for deep profiling metrics collector."""

from unittest.mock import MagicMock

from onyx.server.metrics.deep_profiling import _strip_path
from onyx.server.metrics.deep_profiling import DeepProfilingCollector


def test_strip_path_site_packages() -> None:
    """Verify site-packages prefix is stripped."""
    path = "/usr/lib/python3.11/site-packages/onyx/chat/process.py"
    assert _strip_path(path) == "onyx/chat/process.py"


def test_strip_path_dist_packages() -> None:
    path = "/usr/lib/python3/dist-packages/sqlalchemy/engine.py"
    assert _strip_path(path) == "sqlalchemy/engine.py"


def test_strip_path_cwd() -> None:
    """Verify cwd prefix is stripped."""
    import os

    cwd = os.getcwd()
    path = f"{cwd}/onyx/server/main.py"
    assert _strip_path(path) == "onyx/server/main.py"


def test_strip_path_unknown_returns_as_is() -> None:
    path = "/some/random/path.py"
    assert _strip_path(path) == path


def _make_mock_stat(filename: str, lineno: int, size: int, count: int) -> MagicMock:
    stat = MagicMock()
    frame = MagicMock()
    frame.filename = filename
    frame.lineno = lineno
    stat.traceback = [frame]
    stat.size = size
    stat.count = count
    stat.size_diff = size  # For delta stats
    return stat


def test_collector_exports_tracemalloc_metrics() -> None:
    """Verify the collector exports top allocation sites."""
    import onyx.server.metrics.deep_profiling as mod

    original_top = mod._current_top_stats
    original_delta = mod._current_delta_stats
    original_total = mod._current_total_bytes

    try:
        mod._current_top_stats = [
            _make_mock_stat("site-packages/onyx/chat.py", 42, 1024, 10),
            _make_mock_stat("site-packages/onyx/db.py", 100, 2048, 5),
        ]
        mod._current_delta_stats = [
            _make_mock_stat("site-packages/onyx/chat.py", 42, 512, 3),
        ]
        mod._current_total_bytes = 3072

        collector = DeepProfilingCollector()
        families = collector.collect()

        # Find specific metric families by name
        family_names = [f.name for f in families]
        assert "onyx_tracemalloc_top_bytes" in family_names
        assert "onyx_tracemalloc_top_count" in family_names
        assert "onyx_tracemalloc_delta_bytes" in family_names
        assert "onyx_tracemalloc_total_bytes" in family_names
        assert "onyx_gc_collections" in family_names
        assert "onyx_gc_collected" in family_names
        assert "onyx_gc_uncollectable" in family_names
        assert "onyx_object_type_count" in family_names

        # Verify top_bytes values
        top_bytes_family = next(
            f for f in families if f.name == "onyx_tracemalloc_top_bytes"
        )
        values = {s.labels["source"]: s.value for s in top_bytes_family.samples}
        assert values["onyx/chat.py:42"] == 1024
        assert values["onyx/db.py:100"] == 2048

        # Verify total
        total_family = next(
            f for f in families if f.name == "onyx_tracemalloc_total_bytes"
        )
        assert total_family.samples[0].value == 3072

    finally:
        mod._current_top_stats = original_top
        mod._current_delta_stats = original_delta
        mod._current_total_bytes = original_total


def test_collector_exports_gc_stats() -> None:
    """Verify GC generation stats are exported."""
    collector = DeepProfilingCollector()
    families = collector.collect()

    gc_collections = next(f for f in families if f.name == "onyx_gc_collections")
    # Should have 3 generations (0, 1, 2)
    assert len(gc_collections.samples) == 3
    generations = {s.labels["generation"] for s in gc_collections.samples}
    assert generations == {"0", "1", "2"}


def test_collector_exports_object_type_counts() -> None:
    """Verify object type counts are exported from cached snapshot data."""
    import onyx.server.metrics.deep_profiling as mod

    original = mod._current_object_type_counts
    try:
        mod._current_object_type_counts = [
            ("dict", 5000),
            ("list", 3000),
            ("tuple", 2000),
        ]

        collector = DeepProfilingCollector()
        families = collector.collect()

        type_count = next(f for f in families if f.name == "onyx_object_type_count")
        assert len(type_count.samples) == 3
        values = {s.labels["type"]: s.value for s in type_count.samples}
        assert values["dict"] == 5000
        assert values["list"] == 3000
    finally:
        mod._current_object_type_counts = original


def test_collector_describe_returns_empty() -> None:
    collector = DeepProfilingCollector()
    assert collector.describe() == []
