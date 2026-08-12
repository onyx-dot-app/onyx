"""Guards the incognito recording policy: which mode permits which sink.

The mode enum is the only policy object, so these tests pin the full
mode x sink matrix. A behavior change that is not also a deliberate edit
here is a policy regression.
"""

from unittest.mock import MagicMock, patch

import pytest

from onyx.chat.incognito import (
    content_free_file_descriptors,
    resolve_incognito_record_mode,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.file_store.models import ChatFileType, FileDescriptor


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


class TestResolver:
    @pytest.mark.parametrize("mode", list(IncognitoRecordMode))
    def test_resolves_to_the_admin_setting(self, mode: IncognitoRecordMode) -> None:
        with patch(
            "onyx.chat.incognito.load_effective_uncached",
            return_value=MagicMock(incognito_record_mode=mode),
        ):
            assert resolve_incognito_record_mode() is mode

    def test_reads_past_the_settings_cache(self) -> None:
        """The pin is durable, so a cached pre-save mode must never reach it."""
        with (
            patch(
                "onyx.chat.incognito.load_effective_uncached",
                return_value=MagicMock(
                    incognito_record_mode=IncognitoRecordMode.USAGE_ONLY
                ),
            ) as uncached,
            patch(
                "onyx.chat.incognito.get_security_settings",
                return_value=MagicMock(
                    incognito_record_mode=IncognitoRecordMode.FULL_HISTORY
                ),
            ) as cached,
        ):
            assert resolve_incognito_record_mode() is IncognitoRecordMode.USAGE_ONLY
        assert uncached.called
        assert not cached.called

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
