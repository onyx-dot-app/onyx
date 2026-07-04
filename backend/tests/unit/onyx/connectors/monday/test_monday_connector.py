from onyx.connectors.monday.connector import _normalize_id_filter


def test_normalize_id_filter_empty_list_becomes_none() -> None:
    assert _normalize_id_filter([]) is None


def test_normalize_id_filter_none_stays_none() -> None:
    assert _normalize_id_filter(None) is None


def test_normalize_id_filter_preserves_values() -> None:
    assert _normalize_id_filter(["123", "456"]) == ["123", "456"]
