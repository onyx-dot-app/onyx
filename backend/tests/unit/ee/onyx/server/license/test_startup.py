import base64
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from ee.onyx.server.license import startup
from ee.onyx.server.license.models import LicensePayload, PlanType
from onyx.db.models import License
from tests.unit.ee.onyx.utils.test_license_utils import (
    create_signed_license,
    generate_test_key_pair,
)


@pytest.mark.parametrize("path", [None, ""])
def test_unset_path_does_nothing(
    monkeypatch: pytest.MonkeyPatch, path: str | None
) -> None:
    monkeypatch.setattr(startup, "ONYX_LICENSE_FILE", path)
    monkeypatch.setattr(startup, "MULTI_TENANT", False)
    with (
        patch.object(Path, "read_text") as read_file,
        patch.object(startup, "get_session_with_current_tenant") as session,
    ):
        startup.seed_license_from_file()

    read_file.assert_not_called()
    session.assert_not_called()


def test_multi_tenant_skips_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(startup, "ONYX_LICENSE_FILE", "/missing/license.lic")
    monkeypatch.setattr(startup, "MULTI_TENANT", True)
    with (
        patch.object(Path, "read_text") as read_file,
        patch.object(startup, "get_session_with_current_tenant") as session,
    ):
        startup.seed_license_from_file()

    read_file.assert_not_called()
    session.assert_not_called()


@pytest.mark.parametrize(
    ("armored", "newer_stored_license"), [(False, False), (True, False), (True, True)]
)
def test_signed_file_reaches_the_guarded_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    armored: bool,
    newer_stored_license: bool,
) -> None:
    private_key, public_key = generate_test_key_pair()
    now = datetime.now(timezone.utc)
    payload = LicensePayload(
        version="1.0",
        tenant_id="startup-test",
        issued_at=now,
        expires_at=now + timedelta(days=30),
        seats=10,
        plan_type=PlanType.MONTHLY,
    )
    license_data = create_signed_license(private_key, payload)
    stored = None
    if newer_stored_license:
        stored = License(
            license_data=create_signed_license(
                private_key,
                payload.model_copy(update={"issued_at": now + timedelta(days=1)}),
            )
        )
    content = license_data
    if armored:
        wrapped = "\n".join(
            license_data[index : index + 64]
            for index in range(0, len(license_data), 64)
        )
        content = (
            f"-----BEGIN ONYX LICENSE-----\n{wrapped}\n-----END ONYX LICENSE-----\n"
        )
    license_file = tmp_path / "license.lic"
    license_file.write_text(content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(startup, "ONYX_LICENSE_FILE", license_file.name)
    monkeypatch.setattr(startup, "MULTI_TENANT", False)

    with (
        patch.object(startup, "get_session_with_current_tenant") as session,
        patch("ee.onyx.utils.license._get_public_keys", return_value=[public_key]),
        patch("ee.onyx.db.license.acquire_license_store_lock") as store_lock,
        patch("ee.onyx.db.license.get_license", return_value=stored),
        patch("ee.onyx.db.license.upsert_license") as upsert,
        patch("ee.onyx.utils.license.publish_license_cache") as publish,
        patch("ee.onyx.utils.license.resume_license_reclaim"),
    ):
        startup.seed_license_from_file()

    db_session = session.return_value.__enter__.return_value
    store_lock.assert_called_once_with(db_session)
    if newer_stored_license:
        upsert.assert_not_called()
        db_session.commit.assert_not_called()
        db_session.rollback.assert_called_once()
    else:
        upsert.assert_called_once_with(db_session, license_data, commit=False)
        db_session.commit.assert_called_once()
    publish.assert_called_once_with(db_session)


@pytest.mark.parametrize("contents", [None, b"", b" \n\t", b"\xff", b"invalid"])
def test_bad_file_preserves_the_stored_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: bytes | None
) -> None:
    license_file = tmp_path / "license.lic"
    if contents is not None:
        license_file.write_bytes(contents)
    monkeypatch.setattr(startup, "ONYX_LICENSE_FILE", str(license_file))
    monkeypatch.setattr(startup, "MULTI_TENANT", False)

    with (
        patch.object(startup, "get_session_with_current_tenant") as session,
        patch("ee.onyx.db.license.acquire_license_store_lock") as store_lock,
        patch("ee.onyx.db.license.upsert_license") as upsert,
        patch("ee.onyx.utils.license.publish_license_cache") as publish,
    ):
        startup.seed_license_from_file()

    store_lock.assert_not_called()
    upsert.assert_not_called()
    session.return_value.__enter__.return_value.commit.assert_not_called()
    publish.assert_not_called()


def test_invalid_payload_does_not_log_file_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_marker = "private-license-input"
    contents = base64.b64encode(
        json.dumps(
            {"payload": {"seats": secret_marker}, "signature": secret_marker}
        ).encode()
    ).decode()
    license_file = tmp_path / "license.lic"
    license_file.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(startup, "ONYX_LICENSE_FILE", str(license_file))
    monkeypatch.setattr(startup, "MULTI_TENANT", False)

    with patch.object(startup, "get_session_with_current_tenant"):
        startup.seed_license_from_file()

    assert "ONYX_LICENSE_FILE is invalid" in caplog.text
    assert secret_marker not in caplog.text
    assert contents not in caplog.text


def test_database_errors_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    license_file = tmp_path / "license.lic"
    license_file.write_text("license", encoding="utf-8")
    monkeypatch.setattr(startup, "ONYX_LICENSE_FILE", str(license_file))
    monkeypatch.setattr(startup, "MULTI_TENANT", False)

    with (
        patch.object(startup, "get_session_with_current_tenant"),
        patch.object(
            startup, "verify_and_store_license", side_effect=RuntimeError("database")
        ),
        pytest.raises(RuntimeError, match="database"),
    ):
        startup.seed_license_from_file()


@pytest.mark.asyncio
async def test_lifespan_loads_the_license_after_database_setup() -> None:
    from onyx.main import app

    events: list[str] = []

    @asynccontextmanager
    async def base_lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        events.append("database ready")
        yield
        events.append("database closed")

    from ee.onyx import main

    with (
        patch.object(main, "lifespan_base", base_lifespan),
        patch.object(
            main, "seed_license_from_file", side_effect=lambda: events.append("license")
        ),
        patch.object(main, "seed_db", side_effect=lambda: events.append("seed data")),
    ):
        async with main.lifespan(app):
            assert events == ["database ready", "license", "seed data"]

    assert events == ["database ready", "license", "seed data", "database closed"]
