from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.file_store.file_store import FileStore
from onyx.server.features.build.external_apps import api as external_apps_api
from onyx.skills.ingest import IngestedBundle


def test_create_custom_external_app_cleans_new_bundle_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = cast(FileStore, object())
    delete_bundle_blob = MagicMock()
    monkeypatch.setattr(external_apps_api, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(
        "onyx.skills.ingest.ingest_skill_bundle",
        lambda *_args, **_kwargs: IngestedBundle(
            slug="helper-skill",
            bundle_file_id="new-bundle",
            bundle_sha256="0" * 64,
            name="Helper Skill",
            description="Bundle description",
        ),
    )
    monkeypatch.setattr("onyx.skills.ingest.delete_bundle_blob", delete_bundle_blob)

    def raise_db_error(**_kwargs: Any) -> None:
        raise RuntimeError("db write failed")

    monkeypatch.setattr(external_apps_api, "create_external_app", raise_db_error)

    with pytest.raises(RuntimeError):
        external_apps_api.create_custom_external_app(
            name="Helper Skill",
            description="",
            upstream_url_patterns='["https://api.example.com/*"]',
            auth_template='{"Authorization": "Bearer {token}"}',
            organization_credentials='{"token": "secret"}',
            bundle=cast(
                UploadFile,
                SimpleNamespace(
                    file=io.BytesIO(b"bundle"),
                    filename="helper-skill.zip",
                ),
            ),
            db_session=cast(Session, object()),
        )

    delete_bundle_blob.assert_called_once_with(file_store, "new-bundle")


def test_replace_custom_app_bundle_cleans_new_bundle_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_store = cast(FileStore, object())
    delete_bundle_blob = MagicMock()
    app = cast(
        ExternalApp,
        SimpleNamespace(
            app_type=ExternalAppType.CUSTOM,
            skill=SimpleNamespace(slug="helper-skill"),
        ),
    )
    monkeypatch.setattr(external_apps_api, "get_default_file_store", lambda: file_store)
    monkeypatch.setattr(external_apps_api, "_get_app_or_404", lambda *_args: app)
    monkeypatch.setattr(
        "onyx.skills.ingest.ingest_skill_bundle",
        lambda *_args, **_kwargs: IngestedBundle(
            slug="helper-skill",
            bundle_file_id="replacement-bundle",
            bundle_sha256="1" * 64,
            name="Helper Skill",
            description="Bundle description",
        ),
    )
    monkeypatch.setattr("onyx.skills.ingest.delete_bundle_blob", delete_bundle_blob)

    def raise_db_error(**_kwargs: Any) -> None:
        raise RuntimeError("db write failed")

    monkeypatch.setattr(external_apps_api, "update_external_app", raise_db_error)

    with pytest.raises(RuntimeError):
        external_apps_api.replace_custom_app_bundle(
            external_app_id=1,
            bundle=cast(
                UploadFile,
                SimpleNamespace(
                    file=io.BytesIO(b"bundle"),
                    filename="helper-skill.zip",
                ),
            ),
            db_session=cast(Session, object()),
        )

    delete_bundle_blob.assert_called_once_with(file_store, "replacement-bundle")
