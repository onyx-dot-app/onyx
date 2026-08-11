"""Guards the incognito recording policy: which mode permits which sink.

The mode enum is the only policy object, so these tests pin the full
mode x sink matrix. A behavior change that is not also a deliberate edit
here is a policy regression.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects import postgresql

from onyx.chat.incognito import (
    content_free_file_descriptors,
    resolve_incognito_record_mode,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatSession
from onyx.file_store.models import ChatFileType, FileDescriptor


def _mode_column_type() -> SqlEnum:
    column_type = ChatSession.__table__.c.incognito_record_mode.type
    assert isinstance(column_type, SqlEnum)
    return column_type


def _mode_processors() -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    """The column's bind and result processors, against the real dialect."""
    column_type = _mode_column_type()
    dialect = postgresql.dialect()
    to_db = column_type.bind_processor(dialect)
    from_db = column_type.result_processor(dialect, None)
    assert to_db is not None and from_db is not None
    return to_db, from_db


class TestModeSinkMatrix:
    @pytest.mark.parametrize(
        "mode,persists_content,emits_external_traces,fires_hooks",
        [
            (IncognitoRecordMode.FULL_HISTORY, True, True, True),
            (IncognitoRecordMode.USAGE_ONLY, False, False, False),
        ],
    )
    def test_matrix(
        self,
        mode: IncognitoRecordMode,
        persists_content: bool,
        emits_external_traces: bool,
        fires_hooks: bool,
    ) -> None:
        assert mode.persists_content is persists_content
        assert mode.emits_external_traces is emits_external_traces
        assert mode.fires_hooks is fires_hooks

    def test_only_full_history_persists_content(self) -> None:
        """The guarantee: no other mode may write conversation content."""
        persisting = [m for m in IncognitoRecordMode if m.persists_content]
        assert persisting == [IncognitoRecordMode.FULL_HISTORY]

    def test_no_mode_emits_external_traces_without_persisting_content(self) -> None:
        """External egress never outlives the decision to record."""
        for mode in IncognitoRecordMode:
            if mode.emits_external_traces:
                assert mode.persists_content


class TestModeIdentity:
    def test_wire_values_are_the_contract(self) -> None:
        """These strings cross the API and the admin setting. Renaming one is
        a breaking change, so they are pinned explicitly."""
        assert IncognitoRecordMode.FULL_HISTORY.value == "full_history"
        assert IncognitoRecordMode.USAGE_ONLY.value == "usage_only"

    def test_exactly_two_modes(self) -> None:
        """Record-nothing is unrepresentable: usage metering feeds token rate
        limits, so a mode that skips it would be a quota-evasion route. The
        feature-off state is the availability setting, never a session mode."""
        assert len(list(IncognitoRecordMode)) == 2


class TestStorageContract:
    """Pins what the chat_session column actually writes to Postgres.

    ``Enum(native_enum=False)`` persists the member NAME by default, which
    would store FULL_HISTORY under a column the API reports as full_history.
    ``values_callable`` closes that gap. These compile the type against the
    postgres dialect, so the contract is pinned without needing a database.
    """

    def test_column_persists_wire_values(self) -> None:
        assert set(_mode_column_type().enums) == {m.value for m in IncognitoRecordMode}

    def test_column_round_trips_every_mode(self) -> None:
        to_db, from_db = _mode_processors()
        for mode in IncognitoRecordMode:
            stored = to_db(mode)
            assert stored == mode.value
            assert from_db(stored) is mode

    def test_null_stays_null(self) -> None:
        """NULL means ordinary chat, so it must not coerce to a mode."""
        to_db, from_db = _mode_processors()
        assert to_db(None) is None
        assert from_db(None) is None


class TestResolver:
    @pytest.mark.parametrize("mode", list(IncognitoRecordMode))
    def test_resolves_to_the_admin_setting(self, mode: IncognitoRecordMode) -> None:
        with patch(
            "onyx.chat.incognito.get_security_settings",
            return_value=MagicMock(incognito_record_mode=mode),
        ):
            assert resolve_incognito_record_mode() is mode

    def test_unknown_context_value_fails_closed(self) -> None:
        """A corrupt contextvar must never read as content-persisting."""
        resolved = IncognitoRecordMode.from_context_value("garbage")
        assert resolved is IncognitoRecordMode.USAGE_ONLY
        assert IncognitoRecordMode.from_context_value(None) is None


class TestContentFreeFileDescriptors:
    """The persisted descriptor of a content-free turn keeps linkage, never
    the filename."""

    def test_strips_name_and_keeps_linkage(self) -> None:
        scrubbed = content_free_file_descriptors(
            [
                FileDescriptor(
                    id="file-1",
                    type=ChatFileType.DOC,
                    name="acquisition_target.pdf",
                    user_file_id="uf-1",
                )
            ]
        )
        assert scrubbed == [
            FileDescriptor(id="file-1", type=ChatFileType.DOC, user_file_id="uf-1")
        ]
        assert "name" not in scrubbed[0]
