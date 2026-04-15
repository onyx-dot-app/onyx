"""Tests for permission-sync-specific Prometheus metrics."""

import pytest

from onyx.server.metrics.perm_sync_metrics import DOC_PERM_SYNC_DB_UPDATE_DURATION
from onyx.server.metrics.perm_sync_metrics import DOC_PERM_SYNC_DOCS_PROCESSED
from onyx.server.metrics.perm_sync_metrics import DOC_PERM_SYNC_DURATION
from onyx.server.metrics.perm_sync_metrics import DOC_PERM_SYNC_ERRORS
from onyx.server.metrics.perm_sync_metrics import GROUP_SYNC_DURATION
from onyx.server.metrics.perm_sync_metrics import GROUP_SYNC_ERRORS
from onyx.server.metrics.perm_sync_metrics import GROUP_SYNC_GROUPS_PROCESSED
from onyx.server.metrics.perm_sync_metrics import GROUP_SYNC_UPSERT_DURATION
from onyx.server.metrics.perm_sync_metrics import GROUP_SYNC_USERS_PROCESSED
from onyx.server.metrics.perm_sync_metrics import inc_doc_perm_sync_docs_processed
from onyx.server.metrics.perm_sync_metrics import inc_doc_perm_sync_errors
from onyx.server.metrics.perm_sync_metrics import inc_group_sync_errors
from onyx.server.metrics.perm_sync_metrics import inc_group_sync_groups_processed
from onyx.server.metrics.perm_sync_metrics import inc_group_sync_users_processed
from onyx.server.metrics.perm_sync_metrics import (
    observe_doc_perm_sync_db_update_duration,
)
from onyx.server.metrics.perm_sync_metrics import observe_doc_perm_sync_duration
from onyx.server.metrics.perm_sync_metrics import observe_group_sync_duration
from onyx.server.metrics.perm_sync_metrics import observe_group_sync_upsert_duration


# --- Doc permission sync: overall duration ---


class TestObserveDocPermSyncDuration:
    def test_observes_duration(self) -> None:
        before = DOC_PERM_SYNC_DURATION.labels(connector_type="google_drive")._sum.get()

        observe_doc_perm_sync_duration(10.0, "google_drive")

        after = DOC_PERM_SYNC_DURATION.labels(connector_type="google_drive")._sum.get()
        assert after == pytest.approx(before + 10.0)

    def test_labels_by_connector_type(self) -> None:
        before_gd = DOC_PERM_SYNC_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        before_conf = DOC_PERM_SYNC_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        observe_doc_perm_sync_duration(5.0, "google_drive")

        after_gd = DOC_PERM_SYNC_DURATION.labels(
            connector_type="google_drive"
        )._sum.get()
        after_conf = DOC_PERM_SYNC_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        assert after_gd == pytest.approx(before_gd + 5.0)
        assert after_conf == pytest.approx(before_conf)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DOC_PERM_SYNC_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_doc_perm_sync_duration(1.0, "google_drive")


# --- Doc permission sync: DB update duration ---


class TestObserveDocPermSyncDbUpdateDuration:
    def test_observes_duration(self) -> None:
        before = DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        observe_doc_perm_sync_db_update_duration(3.0, "confluence")

        after = DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        assert after == pytest.approx(before + 3.0)

    def test_labels_by_connector_type(self) -> None:
        before_conf = DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        before_slack = DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(
            connector_type="slack"
        )._sum.get()

        observe_doc_perm_sync_db_update_duration(2.0, "confluence")

        after_conf = DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        after_slack = DOC_PERM_SYNC_DB_UPDATE_DURATION.labels(
            connector_type="slack"
        )._sum.get()

        assert after_conf == pytest.approx(before_conf + 2.0)
        assert after_slack == pytest.approx(before_slack)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DOC_PERM_SYNC_DB_UPDATE_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_doc_perm_sync_db_update_duration(1.0, "confluence")


# --- Doc permission sync: docs processed counter ---


class TestIncDocPermSyncDocsProcessed:
    def test_increments_counter(self) -> None:
        before = DOC_PERM_SYNC_DOCS_PROCESSED.labels(
            connector_type="google_drive"
        )._value.get()

        inc_doc_perm_sync_docs_processed("google_drive", 5)

        after = DOC_PERM_SYNC_DOCS_PROCESSED.labels(
            connector_type="google_drive"
        )._value.get()
        assert after == before + 5

    def test_labels_by_connector_type(self) -> None:
        before_gd = DOC_PERM_SYNC_DOCS_PROCESSED.labels(
            connector_type="google_drive"
        )._value.get()
        before_jira = DOC_PERM_SYNC_DOCS_PROCESSED.labels(
            connector_type="jira"
        )._value.get()

        inc_doc_perm_sync_docs_processed("google_drive", 3)

        after_gd = DOC_PERM_SYNC_DOCS_PROCESSED.labels(
            connector_type="google_drive"
        )._value.get()
        after_jira = DOC_PERM_SYNC_DOCS_PROCESSED.labels(
            connector_type="jira"
        )._value.get()

        assert after_gd == before_gd + 3
        assert after_jira == before_jira

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DOC_PERM_SYNC_DOCS_PROCESSED,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_doc_perm_sync_docs_processed("google_drive")


# --- Doc permission sync: errors counter ---


class TestIncDocPermSyncErrors:
    def test_increments_counter(self) -> None:
        before = DOC_PERM_SYNC_ERRORS.labels(connector_type="sharepoint")._value.get()

        inc_doc_perm_sync_errors("sharepoint", 2)

        after = DOC_PERM_SYNC_ERRORS.labels(connector_type="sharepoint")._value.get()
        assert after == before + 2

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            DOC_PERM_SYNC_ERRORS,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_doc_perm_sync_errors("sharepoint")


# --- Group sync: overall duration ---


class TestObserveGroupSyncDuration:
    def test_observes_duration(self) -> None:
        before = GROUP_SYNC_DURATION.labels(connector_type="google_drive")._sum.get()

        observe_group_sync_duration(20.0, "google_drive")

        after = GROUP_SYNC_DURATION.labels(connector_type="google_drive")._sum.get()
        assert after == pytest.approx(before + 20.0)

    def test_labels_by_connector_type(self) -> None:
        before_gd = GROUP_SYNC_DURATION.labels(connector_type="google_drive")._sum.get()
        before_slack = GROUP_SYNC_DURATION.labels(connector_type="slack")._sum.get()

        observe_group_sync_duration(7.0, "google_drive")

        after_gd = GROUP_SYNC_DURATION.labels(connector_type="google_drive")._sum.get()
        after_slack = GROUP_SYNC_DURATION.labels(connector_type="slack")._sum.get()

        assert after_gd == pytest.approx(before_gd + 7.0)
        assert after_slack == pytest.approx(before_slack)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            GROUP_SYNC_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_group_sync_duration(1.0, "google_drive")


# --- Group sync: upsert duration ---


class TestObserveGroupSyncUpsertDuration:
    def test_observes_duration(self) -> None:
        before = GROUP_SYNC_UPSERT_DURATION.labels(
            connector_type="confluence"
        )._sum.get()

        observe_group_sync_upsert_duration(4.0, "confluence")

        after = GROUP_SYNC_UPSERT_DURATION.labels(
            connector_type="confluence"
        )._sum.get()
        assert after == pytest.approx(before + 4.0)

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            GROUP_SYNC_UPSERT_DURATION,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        observe_group_sync_upsert_duration(1.0, "confluence")


# --- Group sync: groups processed counter ---


class TestIncGroupSyncGroupsProcessed:
    def test_increments_counter(self) -> None:
        before = GROUP_SYNC_GROUPS_PROCESSED.labels(
            connector_type="github"
        )._value.get()

        inc_group_sync_groups_processed("github", 10)

        after = GROUP_SYNC_GROUPS_PROCESSED.labels(connector_type="github")._value.get()
        assert after == before + 10

    def test_labels_by_connector_type(self) -> None:
        before_gh = GROUP_SYNC_GROUPS_PROCESSED.labels(
            connector_type="github"
        )._value.get()
        before_slack = GROUP_SYNC_GROUPS_PROCESSED.labels(
            connector_type="slack"
        )._value.get()

        inc_group_sync_groups_processed("github", 4)

        after_gh = GROUP_SYNC_GROUPS_PROCESSED.labels(
            connector_type="github"
        )._value.get()
        after_slack = GROUP_SYNC_GROUPS_PROCESSED.labels(
            connector_type="slack"
        )._value.get()

        assert after_gh == before_gh + 4
        assert after_slack == before_slack

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            GROUP_SYNC_GROUPS_PROCESSED,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_group_sync_groups_processed("github")


# --- Group sync: users processed counter ---


class TestIncGroupSyncUsersProcessed:
    def test_increments_counter(self) -> None:
        before = GROUP_SYNC_USERS_PROCESSED.labels(connector_type="github")._value.get()

        inc_group_sync_users_processed("github", 25)

        after = GROUP_SYNC_USERS_PROCESSED.labels(connector_type="github")._value.get()
        assert after == before + 25

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            GROUP_SYNC_USERS_PROCESSED,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_group_sync_users_processed("github")


# --- Group sync: errors counter ---


class TestIncGroupSyncErrors:
    def test_increments_counter(self) -> None:
        before = GROUP_SYNC_ERRORS.labels(connector_type="sharepoint")._value.get()

        inc_group_sync_errors("sharepoint")

        after = GROUP_SYNC_ERRORS.labels(connector_type="sharepoint")._value.get()
        assert after == before + 1

    def test_does_not_raise_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            GROUP_SYNC_ERRORS,
            "labels",
            lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        inc_group_sync_errors("sharepoint")
