from types import SimpleNamespace
from unittest.mock import Mock

from pytest import MonkeyPatch

from onyx.background.celery.tasks.docprocessing import tasks as docprocessing_tasks
from onyx.db.enums import ConnectorCredentialPairStatus


def _build_cc_pair(
    refresh_freq: int | None,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
) -> SimpleNamespace:
    connector = SimpleNamespace(refresh_freq=refresh_freq)
    return SimpleNamespace(
        id=42,
        connector_id=99,
        connector=connector,
        status=status,
    )


def test_auto_pause_pauses_active_connector_in_multi_tenant(
    monkeypatch: MonkeyPatch,
) -> None:
    session: Mock = Mock()
    cc_pair = _build_cc_pair(refresh_freq=3600)
    patched_get: Mock = Mock(return_value=cc_pair)

    monkeypatch.setattr(docprocessing_tasks, "MULTI_TENANT", True)
    monkeypatch.setattr(
        docprocessing_tasks,
        "get_connector_credential_pair_from_id",
        patched_get,
    )

    docprocessing_tasks._auto_pause_cc_pair_after_repeated_failures(
        db_session=session,
        cc_pair_id=cc_pair.id,
        search_settings_id=7,
    )

    assert cc_pair.status == ConnectorCredentialPairStatus.PAUSED
    session.commit.assert_called_once()  # type: ignore[attr-defined]
    patched_get.assert_called_once()


def test_auto_pause_skips_if_refresh_freq_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    session: Mock = Mock()
    cc_pair = _build_cc_pair(refresh_freq=None)
    patched_get: Mock = Mock(return_value=cc_pair)

    monkeypatch.setattr(docprocessing_tasks, "MULTI_TENANT", True)
    monkeypatch.setattr(
        docprocessing_tasks,
        "get_connector_credential_pair_from_id",
        patched_get,
    )

    docprocessing_tasks._auto_pause_cc_pair_after_repeated_failures(
        db_session=session,
        cc_pair_id=cc_pair.id,
        search_settings_id=7,
    )

    assert cc_pair.status == ConnectorCredentialPairStatus.ACTIVE
    session.commit.assert_not_called()  # type: ignore[attr-defined]
    patched_get.assert_called_once()


def test_auto_pause_noop_when_not_multi_tenant(
    monkeypatch: MonkeyPatch,
) -> None:
    session: Mock = Mock()
    cc_pair = _build_cc_pair(refresh_freq=3600)
    patched_get: Mock = Mock(return_value=cc_pair)

    monkeypatch.setattr(docprocessing_tasks, "MULTI_TENANT", False)
    monkeypatch.setattr(
        docprocessing_tasks,
        "get_connector_credential_pair_from_id",
        patched_get,
    )

    docprocessing_tasks._auto_pause_cc_pair_after_repeated_failures(
        db_session=session,
        cc_pair_id=cc_pair.id,
        search_settings_id=7,
    )

    assert cc_pair.status == ConnectorCredentialPairStatus.ACTIVE
    session.commit.assert_not_called()  # type: ignore[attr-defined]
    patched_get.assert_not_called()
