from unittest.mock import MagicMock, patch

from onyx.file_store.staging import delete_files_best_effort


def test_delete_stops_at_the_deadline_between_files() -> None:
    file_store = MagicMock()
    with (
        patch(
            "onyx.file_store.staging.get_default_file_store", return_value=file_store
        ),
        patch("onyx.file_store.staging.time.monotonic", side_effect=[0.0, 10.0]),
    ):
        deleted = delete_files_best_effort(["first", "second", "third"], deadline=5.0)

    assert deleted == 1
    file_store.delete_file.assert_called_once_with("first", error_on_missing=False)
