import pytest

from onyx.file_store import legacy_copy


def test_all_objects_skips_the_record_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legacy_copy, "LEGACY_COPY_ALL_OBJECTS", True)
    monkeypatch.setattr(
        legacy_copy,
        "get_session_with_tenant",
        lambda **_: pytest.fail("the record check must not open a session"),
    )

    assert legacy_copy._keys_with_records("bucket", ["a", "b"]) == {"a", "b"}
    assert legacy_copy._key_has_record("bucket", "a")
