"""Tests for rotate_encryption_key against real Postgres.

Uses real ORM models (Credential, InternetSearchProvider) and the actual
Postgres database. Discovery is mocked in rotation tests to scope mutations
to only the test rows — the real _discover_encrypted_columns walk is tested
separately in TestDiscoverEncryptedColumns.

Requires a running Postgres instance. Run with::

    python -m dotenv -f .vscode/.env run -- pytest tests/external_dependency_unit/db/test_rotate_encryption_key.py
"""

import json
from collections.abc import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import LargeBinary
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from ee.onyx.utils.encryption import _decrypt_bytes
from ee.onyx.utils.encryption import _encrypt_string
from ee.onyx.utils.encryption import _get_trimmed_key
from onyx.configs.constants import DocumentSource
from onyx.db.models import Credential
from onyx.db.models import EncryptedJson
from onyx.db.models import EncryptedString
from onyx.db.models import InternetSearchProvider
from onyx.db.rotate_encryption_key import _discover_encrypted_columns
from onyx.db.rotate_encryption_key import rotate_encryption_key
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version

EE_MODULE = "ee.onyx.utils.encryption"
ROTATE_MODULE = "onyx.db.rotate_encryption_key"

OLD_KEY = "o" * 16
NEW_KEY = "n" * 16


@pytest.fixture(autouse=True)
def _enable_ee() -> Generator[None, None, None]:
    prev = global_version._is_ee
    global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    yield
    global_version._is_ee = prev
    fetch_versioned_implementation.cache_clear()


@pytest.fixture(autouse=True)
def _clear_key_cache() -> None:
    _get_trimmed_key.cache_clear()


def _raw_credential_bytes(db_session: Session, credential_id: int) -> bytes | None:
    """Read raw bytes from credential_json, bypassing the TypeDecorator."""
    col = Credential.__table__.c.credential_json
    stmt = select(col.cast(LargeBinary)).where(
        Credential.__table__.c.id == credential_id
    )
    return db_session.execute(stmt).scalar()


def _raw_isp_bytes(db_session: Session, isp_id: int) -> bytes | None:
    """Read raw bytes from InternetSearchProvider.api_key."""
    col = InternetSearchProvider.__table__.c.api_key
    stmt = select(col.cast(LargeBinary)).where(
        InternetSearchProvider.__table__.c.id == isp_id
    )
    return db_session.execute(stmt).scalar()


class TestDiscoverEncryptedColumns:
    """Verify _discover_encrypted_columns finds real production models."""

    def test_discovers_credential_json(self) -> None:
        results = _discover_encrypted_columns()
        found = {
            (model_cls.__tablename__, col_name, is_json)  # type: ignore[attr-defined]
            for model_cls, col_name, _, is_json in results
        }
        assert ("credential", "credential_json", True) in found

    def test_discovers_internet_search_provider_api_key(self) -> None:
        results = _discover_encrypted_columns()
        found = {
            (model_cls.__tablename__, col_name, is_json)  # type: ignore[attr-defined]
            for model_cls, col_name, _, is_json in results
        }
        assert ("internet_search_provider", "api_key", False) in found

    def test_all_encrypted_string_columns_are_not_json(self) -> None:
        results = _discover_encrypted_columns()
        for model_cls, col_name, _, is_json in results:
            col = getattr(model_cls, col_name).property.columns[0]
            if isinstance(col.type, EncryptedString):
                assert not is_json, (
                    f"{model_cls.__tablename__}.{col_name} is EncryptedString "  # type: ignore[attr-defined]
                    f"but is_json={is_json}"
                )

    def test_all_encrypted_json_columns_are_json(self) -> None:
        results = _discover_encrypted_columns()
        for model_cls, col_name, _, is_json in results:
            col = getattr(model_cls, col_name).property.columns[0]
            if isinstance(col.type, EncryptedJson):
                assert is_json, (
                    f"{model_cls.__tablename__}.{col_name} is EncryptedJson "  # type: ignore[attr-defined]
                    f"but is_json={is_json}"
                )


class TestRotateCredential:
    """Test rotation against the real Credential table (EncryptedJson).

    Discovery is scoped to only the Credential model to avoid mutating
    other tables in the test database.
    """

    @pytest.fixture(autouse=True)
    def _limit_discovery(self) -> Generator[None, None, None]:
        with patch(
            f"{ROTATE_MODULE}._discover_encrypted_columns",
            return_value=[(Credential, "credential_json", ["id"], True)],
        ):
            yield

    @pytest.fixture()
    def credential_id(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> Generator[int, None, None]:
        """Insert a Credential row with raw encrypted bytes, clean up after."""
        config = {"api_key": "sk-test-1234", "endpoint": "https://example.com"}
        encrypted = _encrypt_string(json.dumps(config), key=OLD_KEY)

        result = db_session.execute(
            text(
                "INSERT INTO credential "
                "(source, credential_json, admin_public, curator_public) "
                "VALUES (:source, :cred_json, true, false) "
                "RETURNING id"
            ),
            {"source": DocumentSource.INGESTION_API.value, "cred_json": encrypted},
        )
        cred_id = result.scalar_one()
        db_session.commit()

        yield cred_id

        db_session.execute(
            text("DELETE FROM credential WHERE id = :id"), {"id": cred_id}
        )
        db_session.commit()

    def test_rotates_credential_json(
        self, db_session: Session, credential_id: int
    ) -> None:
        with (
            patch(f"{ROTATE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
            patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
        ):
            totals = rotate_encryption_key(db_session, old_key=OLD_KEY)

        assert totals.get("credential.credential_json", 0) >= 1

        raw = _raw_credential_bytes(db_session, credential_id)
        assert raw is not None
        decrypted = json.loads(_decrypt_bytes(raw, key=NEW_KEY))
        assert decrypted["api_key"] == "sk-test-1234"
        assert decrypted["endpoint"] == "https://example.com"

    def test_skips_already_rotated(
        self, db_session: Session, credential_id: int
    ) -> None:
        with (
            patch(f"{ROTATE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
            patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
        ):
            rotate_encryption_key(db_session, old_key=OLD_KEY)
            _ = rotate_encryption_key(db_session, old_key=OLD_KEY)

        raw = _raw_credential_bytes(db_session, credential_id)
        assert raw is not None
        decrypted = json.loads(_decrypt_bytes(raw, key=NEW_KEY))
        assert decrypted["api_key"] == "sk-test-1234"

    def test_dry_run_does_not_modify(
        self, db_session: Session, credential_id: int
    ) -> None:
        original = _raw_credential_bytes(db_session, credential_id)

        with (
            patch(f"{ROTATE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
            patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
        ):
            totals = rotate_encryption_key(db_session, old_key=OLD_KEY, dry_run=True)

        assert totals.get("credential.credential_json", 0) >= 1

        raw_after = _raw_credential_bytes(db_session, credential_id)
        assert raw_after == original


class TestRotateInternetSearchProvider:
    """Test rotation against the real InternetSearchProvider table (EncryptedString).

    Discovery is scoped to only the InternetSearchProvider model to avoid
    mutating other tables in the test database.
    """

    @pytest.fixture(autouse=True)
    def _limit_discovery(self) -> Generator[None, None, None]:
        with patch(
            f"{ROTATE_MODULE}._discover_encrypted_columns",
            return_value=[
                (InternetSearchProvider, "api_key", ["id"], False),
            ],
        ):
            yield

    @pytest.fixture()
    def isp_id(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> Generator[int, None, None]:
        """Insert an InternetSearchProvider row with raw encrypted bytes."""
        encrypted = _encrypt_string("sk-secret-api-key", key=OLD_KEY)

        result = db_session.execute(
            text(
                "INSERT INTO internet_search_provider "
                "(name, provider_type, api_key, is_active) "
                "VALUES (:name, :ptype, :api_key, false) "
                "RETURNING id"
            ),
            {
                "name": f"test-rotation-{id(self)}",
                "ptype": "test",
                "api_key": encrypted,
            },
        )
        isp_id = result.scalar_one()
        db_session.commit()

        yield isp_id

        db_session.execute(
            text("DELETE FROM internet_search_provider WHERE id = :id"),
            {"id": isp_id},
        )
        db_session.commit()

    def test_rotates_api_key(self, db_session: Session, isp_id: int) -> None:
        with (
            patch(f"{ROTATE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
            patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
        ):
            totals = rotate_encryption_key(db_session, old_key=OLD_KEY)

        assert totals.get("internet_search_provider.api_key", 0) >= 1

        raw = _raw_isp_bytes(db_session, isp_id)
        assert raw is not None
        assert _decrypt_bytes(raw, key=NEW_KEY) == "sk-secret-api-key"

    def test_rotates_from_unencrypted(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Test rotating data that was stored without any encryption key."""
        result = db_session.execute(
            text(
                "INSERT INTO internet_search_provider "
                "(name, provider_type, api_key, is_active) "
                "VALUES (:name, :ptype, :api_key, false) "
                "RETURNING id"
            ),
            {
                "name": f"test-raw-{id(self)}",
                "ptype": "test",
                "api_key": b"raw-api-key",
            },
        )
        isp_id = result.scalar_one()
        db_session.commit()

        try:
            with (
                patch(f"{ROTATE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
                patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", NEW_KEY),
            ):
                totals = rotate_encryption_key(db_session, old_key=None)

            assert totals.get("internet_search_provider.api_key", 0) >= 1

            raw = _raw_isp_bytes(db_session, isp_id)
            assert raw is not None
            assert _decrypt_bytes(raw, key=NEW_KEY) == "raw-api-key"
        finally:
            db_session.execute(
                text("DELETE FROM internet_search_provider WHERE id = :id"),
                {"id": isp_id},
            )
            db_session.commit()
