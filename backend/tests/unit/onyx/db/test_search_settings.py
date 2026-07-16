from unittest.mock import MagicMock

from onyx.db.search_settings import get_next_index_name


def _db_returning(index_names: list[str]) -> MagicMock:
    """A db_session whose scalars() yields the given index_names (the query is mocked
    away, so pass the names the same-model prefix filter would return)."""
    db = MagicMock()
    db.scalars.return_value = index_names
    return db


def test_get_next_index_name_increments_from_db_max() -> None:
    db = _db_returning(
        [
            "danswer_chunk_m_000001",
            "danswer_chunk_m_000002",
            "danswer_chunk_m__danswer_alt_index",  # legacy, non-numeric -> ignored
        ]
    )
    assert get_next_index_name(db, "danswer_chunk_m") == "danswer_chunk_m_000003"


def test_get_next_index_name_starts_at_one_when_no_versioned_names() -> None:
    db = _db_returning(["danswer_chunk_m__danswer_alt_index"])
    assert get_next_index_name(db, "danswer_chunk_m") == "danswer_chunk_m_000001"


def test_get_next_index_name_skips_versions_whose_index_still_exists() -> None:
    """DB max is 000003, but 000004's OpenSearch index lingers (its PAST row was deleted).
    The allocator must skip it rather than reuse a stale index the create-only port would
    409-skip and silently promote."""
    db = _db_returning(["danswer_chunk_m_000003"])
    lingering = {"danswer_chunk_m_000004"}
    name = get_next_index_name(
        db, "danswer_chunk_m", index_exists=lambda n: n in lingering
    )
    assert name == "danswer_chunk_m_000005"
