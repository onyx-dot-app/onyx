"""Indexing hands permission-setting over to doc_sync once a source has indexed
successfully. A source that opts out of the handover and then loses the flag
stores every new document with no access list, and those fall back to
connector-level access -- readable by the connector's audience rather than by
the people named on them.
"""

from ee.onyx.external_permissions.sync_params import (
    _SOURCE_TO_SYNC_CONFIG,
    noop_doc_sync,
    source_should_sync_on_every_index,
)
from onyx.configs.constants import DocumentSource


class TestSourcesThatMustKeepSyncingWhileIndexing:
    def test_a_source_whose_doc_sync_does_nothing_must_opt_in(self) -> None:
        """Only the no-op direction is checked. A source with a real doc_sync
        may still set the flag, which is where Zoom lands once it indexes Docs."""
        unmarked = [
            source.value
            for source, config in _SOURCE_TO_SYNC_CONFIG.items()
            if config.doc_sync_config is not None
            and config.doc_sync_config.doc_sync_func is noop_doc_sync
            and not config.doc_sync_config.every_index_should_sync
        ]

        assert unmarked == []

    def test_zoom_keeps_setting_permissions_after_its_first_index(self) -> None:
        assert source_should_sync_on_every_index(DocumentSource.ZOOM) is True

    def test_a_source_that_hands_over_to_doc_sync_is_unaffected(self) -> None:
        assert source_should_sync_on_every_index(DocumentSource.CONFLUENCE) is False
        assert source_should_sync_on_every_index(DocumentSource.GOOGLE_DRIVE) is False

    def test_an_unregistered_source_does_not_opt_in(self) -> None:
        assert source_should_sync_on_every_index(DocumentSource.WEB) is False
