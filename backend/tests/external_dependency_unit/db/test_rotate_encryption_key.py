"""Key rotation against real Postgres: conversion, concurrency, resumption,
verification, and physical coverage across shards.

Every test works in a scratch schema that holds foreign-key-free copies of the
real tables, so a run never rewrites rows the test did not insert. Keyrings are
built explicitly: OLD is the legacy secret alone, NEW adds an envelope key and
writes under it, RETIRED has dropped the legacy secret.

Run with::

    uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/db/test_rotate_encryption_key.py
"""

import base64
import json
import threading
import uuid
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from scripts.reencrypt_secrets import main as reencrypt_main
from sqlalchemy import LargeBinary, Table, bindparam, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, CreateTable, DropSchema, DropTable

from ee.onyx.db import rotate_encryption_key as rotation
from ee.onyx.db.rotate_encryption_key import (
    SANDBOX_DAEMON_KEY_COLUMN,
    EncryptedColumn,
    RotationMode,
    ValueOutcome,
    discover_encrypted_columns,
    rotate_encryption_key,
    rotate_schema,
)
from ee.onyx.utils.encryption import (
    ENVELOPE_MAGIC,
    LEGACY_KEY_ID,
    Keyring,
    build_keyring,
    decrypt_with_keyring,
    encrypt_with_keyring,
    is_current_ciphertext,
)
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import DocumentSource
from onyx.db.engine import shard_registry, tenant_utils
from onyx.db.engine.shard_registry import get_default_shard_name, get_engine_for_shard
from onyx.db.engine.sql_engine import SqlEngine, get_session_for_schema_on_shard
from onyx.db.enums import SandboxStatus
from onyx.db.models import Credential, InternetSearchProvider, Sandbox
from onyx.microvm.registry import get_sandbox_daemon_key, set_sandbox_daemon_key
from shared_configs.configs import TENANT_TEMPLATE_SCHEMA
from tests.external_dependency_unit.db.shard_test_utils import DEFAULT_SHARD

EE_MODULE = "ee.onyx.utils.encryption"
ROTATION_MODULE = "ee.onyx.db.rotate_encryption_key"

LEGACY_SECRET = "o" * 16
NEW_KEYS = json.dumps({"k2026": base64.b64encode(b"n" * 32).decode()})
OLD = build_keyring(LEGACY_SECRET, "", "")
NEW = build_keyring(LEGACY_SECRET, NEW_KEYS, "k2026")
RETIRED = build_keyring("", NEW_KEYS, "k2026")
NONE = build_keyring("", "", "")

CREDENTIAL_TABLE = cast(Table, Credential.__table__)
PROVIDER_TABLE = cast(Table, InternetSearchProvider.__table__)
SANDBOX_TABLE = cast(Table, Sandbox.__table__)
SCRATCH_TABLES = (CREDENTIAL_TABLE, PROVIDER_TABLE, SANDBOX_TABLE)
CREDENTIAL_JSON = '{"api_key": "sk-test-1234",  "endpoint": "https://example.com"}'


def _column(table: Table, name: str) -> EncryptedColumn:
    return EncryptedColumn(
        table=table,
        column=table.c[name],
        primary_key=next(iter(table.primary_key.columns)),
        is_json=name == "credential_json",
    )


CREDENTIAL_COLUMN = _column(CREDENTIAL_TABLE, "credential_json")
PROVIDER_COLUMN = _column(PROVIDER_TABLE, "api_key")
SCRATCH_COLUMNS = [CREDENTIAL_COLUMN, PROVIDER_COLUMN]


@pytest.fixture(autouse=True)
def _engine(enable_ee: None) -> None:  # noqa: ARG001
    SqlEngine.init_engine(pool_size=10, max_overflow=5)


@contextmanager
def scratch_schema(engine: Engine, schema_name: str) -> Iterator[str]:
    """A schema with copies of the tables under test, minus foreign keys, so rows
    need no users or connectors and nothing outside the schema is touched."""
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema_name))
        translated = connection.execution_options(
            schema_translate_map={None: schema_name}
        )
        for table in SCRATCH_TABLES:
            translated.execute(CreateTable(table, include_foreign_key_constraints=()))
    try:
        yield schema_name
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema_name, cascade=True))


@pytest.fixture
def schema() -> Generator[str, None, None]:
    with scratch_schema(
        get_engine_for_shard(get_default_shard_name()), f"tenant_{uuid.uuid4()}"
    ) as name:
        yield name


@contextmanager
def session_on(schema_name: str, shard_name: str | None = None) -> Iterator[Session]:
    with get_session_for_schema_on_shard(
        shard_name=shard_name or get_default_shard_name(), schema_name=schema_name
    ) as db_session:
        yield db_session


def _raw(value: bytes) -> Any:
    # Typed as bytes so the encrypted column's type decorator does not run.
    return bindparam(None, value, type_=LargeBinary)


# Core statements only: `schema_translate_map` rewrites Table constructs, never
# `text()`, so a raw string would reach the shared public schema.
def insert_credential(db_session: Session, raw: bytes) -> int:
    credential_id = db_session.execute(
        CREDENTIAL_TABLE.insert()
        .values(
            source=DocumentSource.INGESTION_API,
            credential_json=_raw(raw),
            admin_public=True,
            curator_public=False,
        )
        .returning(CREDENTIAL_TABLE.c.id)
    ).scalar_one()
    db_session.commit()
    return credential_id


def insert_provider(db_session: Session, raw: bytes) -> int:
    provider_id = db_session.execute(
        PROVIDER_TABLE.insert()
        .values(
            name=f"rotation-{uuid.uuid4().hex[:8]}",
            provider_type="test",
            api_key=_raw(raw),
            is_active=False,
        )
        .returning(PROVIDER_TABLE.c.id)
    ).scalar_one()
    db_session.commit()
    return provider_id


def set_credential_raw(db_session: Session, credential_id: int, raw: bytes) -> None:
    db_session.execute(
        CREDENTIAL_TABLE.update()
        .where(CREDENTIAL_TABLE.c.id == credential_id)
        .values(credential_json=_raw(raw), time_updated=CREDENTIAL_TABLE.c.time_updated)
    )


def delete_credential(db_session: Session, credential_id: int) -> None:
    db_session.execute(
        CREDENTIAL_TABLE.delete().where(CREDENTIAL_TABLE.c.id == credential_id)
    )


def credential_timestamps(db_session: Session) -> list[tuple[Any, Any]]:
    return [
        (row.id, row.time_updated)
        for row in db_session.execute(
            select(CREDENTIAL_TABLE.c.id, CREDENTIAL_TABLE.c.time_updated).order_by(
                CREDENTIAL_TABLE.c.id
            )
        )
    ]


def raw_credential(db_session: Session, credential_id: int) -> bytes | None:
    stored = db_session.execute(
        select(CREDENTIAL_TABLE.c.credential_json.cast(LargeBinary)).where(
            CREDENTIAL_TABLE.c.id == credential_id
        )
    ).scalar()
    return None if stored is None else bytes(stored)


def raw_provider(db_session: Session, provider_id: int) -> bytes:
    return bytes(
        db_session.execute(
            select(PROVIDER_TABLE.c.api_key.cast(LargeBinary)).where(
                PROVIDER_TABLE.c.id == provider_id
            )
        ).scalar_one()
    )


def counts(reports: list[rotation.ColumnReport], name: str) -> dict[ValueOutcome, int]:
    return next(report.counts for report in reports if report.name == name)


def run(
    schema_name: str, keyring: Keyring, mode: RotationMode
) -> list[rotation.ColumnReport]:
    with session_on(schema_name) as db_session:
        reports, absent = rotate_schema(
            db_session, schema_name, keyring, SCRATCH_COLUMNS, mode, None
        )
    assert absent == []
    return reports


class TestDiscovery:
    def test_finds_every_encrypted_column_once(self) -> None:
        names = [column.name for column in discover_encrypted_columns()]
        assert names == sorted(set(names))
        assert "credential.credential_json" in names
        assert "internet_search_provider.api_key" in names
        assert "sandbox.encrypted_pat" in names
        assert "slack_bot.bot_token" in names

    def test_json_columns_are_marked(self) -> None:
        by_name = {column.name: column for column in discover_encrypted_columns()}
        assert by_name["credential.credential_json"].is_json
        assert not by_name["internet_search_provider.api_key"].is_json
        assert by_name["credential.credential_json"].primary_key.name == "id"


class TestConversion:
    def test_legacy_and_plain_values_become_envelopes_with_bytes_preserved(
        self, schema: str
    ) -> None:
        with session_on(schema) as db_session:
            legacy_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON)
            )
            plain_id = insert_credential(db_session, CREDENTIAL_JSON.encode())
            provider_id = insert_provider(db_session, encrypt_with_keyring(OLD, "sk-1"))
            before = credential_timestamps(db_session)

        reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONVERTED: 2
        }
        assert counts(reports, "internet_search_provider.api_key") == {
            ValueOutcome.CONVERTED: 1
        }
        with session_on(schema) as db_session:
            for credential_id in (legacy_id, plain_id):
                raw = raw_credential(db_session, credential_id)
                assert raw is not None and is_current_ciphertext(NEW, raw)
                # The same string, spacing included: a JSON column is not re-dumped.
                assert decrypt_with_keyring(RETIRED, raw).plaintext == CREDENTIAL_JSON
            assert (
                decrypt_with_keyring(
                    RETIRED, raw_provider(db_session, provider_id)
                ).plaintext
                == "sk-1"
            )
            after = credential_timestamps(db_session)
        assert after == before, "onupdate timestamps must not move"

    def test_rerun_is_idempotent(self, schema: str) -> None:
        with session_on(schema) as db_session:
            insert_credential(db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON))
        run(schema, NEW, RotationMode.EXECUTE)

        reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CURRENT: 1
        }

    def test_dry_run_classifies_and_writes_nothing(self, schema: str) -> None:
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON)
            )
            before = raw_credential(db_session, credential_id)

        reports = run(schema, NEW, RotationMode.DRY_RUN)

        assert counts(reports, "credential.credential_json") == {ValueOutcome.STALE: 1}
        with session_on(schema) as db_session:
            assert raw_credential(db_session, credential_id) == before

    def test_dry_run_decrypts_values_already_under_the_write_key(
        self, schema: str
    ) -> None:
        """A current-looking envelope with a broken tag must fail the dry run, not
        wait for the verify step."""
        tampered = bytearray(encrypt_with_keyring(NEW, CREDENTIAL_JSON))
        tampered[-1] ^= 1
        with session_on(schema) as db_session:
            insert_credential(db_session, encrypt_with_keyring(NEW, CREDENTIAL_JSON))
            insert_credential(db_session, bytes(tampered))
            insert_credential(db_session, encrypt_with_keyring(NEW, "not json"))

        reports = run(schema, NEW, RotationMode.DRY_RUN)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CURRENT: 1,
            ValueOutcome.UNREADABLE: 2,
        }

    def test_same_key_material_moves_to_the_envelope_format(self, schema: str) -> None:
        same_material = build_keyring(LEGACY_SECRET, "", LEGACY_KEY_ID)
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON)
            )

        reports = run(schema, same_material, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONVERTED: 1
        }
        with session_on(schema) as db_session:
            raw = raw_credential(db_session, credential_id)
        assert raw is not None and raw.startswith(ENVELOPE_MAGIC)
        assert decrypt_with_keyring(OLD, raw).plaintext == CREDENTIAL_JSON

    def test_envelope_under_an_older_key_is_converted(self, schema: str) -> None:
        next_keys = json.dumps(
            {
                "k2026": base64.b64encode(b"n" * 32).decode(),
                "k2027": base64.b64encode(b"m" * 32).decode(),
            }
        )
        next_keyring = build_keyring("", next_keys, "k2027")
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(RETIRED, CREDENTIAL_JSON)
            )

        reports = run(schema, next_keyring, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONVERTED: 1
        }
        with session_on(schema) as db_session:
            raw = raw_credential(db_session, credential_id)
        assert raw is not None and is_current_ciphertext(next_keyring, raw)


class TestVerification:
    def test_verify_decrypts_current_values_and_passes(self, schema: str) -> None:
        with session_on(schema) as db_session:
            insert_credential(db_session, encrypt_with_keyring(NEW, CREDENTIAL_JSON))

        reports = run(schema, RETIRED, RotationMode.VERIFY)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CURRENT: 1
        }

    def test_verify_reports_each_failure_kind(self, schema: str) -> None:
        tampered = bytearray(encrypt_with_keyring(NEW, CREDENTIAL_JSON))
        tampered[-1] ^= 1
        other_key = build_keyring(
            "", json.dumps({"k9": base64.b64encode(b"z" * 32).decode()}), "k9"
        )
        with session_on(schema) as db_session:
            insert_credential(db_session, encrypt_with_keyring(NEW, CREDENTIAL_JSON))
            insert_credential(db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON))
            insert_credential(db_session, bytes(tampered))
            insert_credential(db_session, b"\xff\xfe not utf-8 \x80")
            insert_credential(db_session, encrypt_with_keyring(NEW, "not json"))
            insert_credential(
                db_session, encrypt_with_keyring(other_key, CREDENTIAL_JSON)
            )

        reports = run(schema, NEW, RotationMode.VERIFY)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CURRENT: 1,
            ValueOutcome.STALE: 1,
            ValueOutcome.UNREADABLE: 3,
            ValueOutcome.UNSUPPORTED: 1,
        }

    def test_execute_leaves_unreadable_rows_and_reports_them(self, schema: str) -> None:
        with session_on(schema) as db_session:
            bad_id = insert_credential(db_session, b"\xff\xfe not utf-8 \x80")
            insert_credential(db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON))

        reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONVERTED: 1,
            ValueOutcome.UNREADABLE: 1,
        }
        with session_on(schema) as db_session:
            assert raw_credential(db_session, bad_id) == b"\xff\xfe not utf-8 \x80"


def _concurrent_writer(
    schema_name: str, write: Callable[[Session], None], times: int | None = None
) -> Callable[[Keyring, str], bytes]:
    """Stands in for `encrypt_with_keyring` inside the rotation: before the swap
    that follows the read, another session commits a write. `times=None` writes
    on every call, like a legacy pod that keeps saving."""
    calls = 0

    def encrypt_then_write(keyring: Keyring, plaintext: str) -> bytes:
        nonlocal calls
        calls += 1
        if times is None or calls <= times:
            with session_on(schema_name) as other:
                write(other)
                other.commit()
        return encrypt_with_keyring(keyring, plaintext)

    return encrypt_then_write


def _set_credential(credential_id: int, raw: bytes) -> Callable[[Session], None]:
    def write(db_session: Session) -> None:
        set_credential_raw(db_session, credential_id, raw)

    return write


class TestPartialSchemas:
    def test_a_missing_table_is_reported_and_the_rest_is_converted(
        self, schema: str
    ) -> None:
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON)
            )
            # The session's schema map sends the DDL to the scratch schema.
            db_session.execute(DropTable(PROVIDER_TABLE))
            db_session.commit()
            reports, absent = rotate_schema(
                db_session, schema, NEW, SCRATCH_COLUMNS, RotationMode.EXECUTE, None
            )

        assert absent == ["internet_search_provider.api_key"]
        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONVERTED: 1
        }
        with session_on(schema) as db_session:
            raw = raw_credential(db_session, credential_id)
        assert raw is not None and is_current_ciphertext(NEW, raw)

    def test_a_table_the_role_cannot_read_fails_instead_of_being_skipped(
        self, schema: str
    ) -> None:
        """A missing privilege must not look like a missing table."""
        role = f"rotation_test_{uuid.uuid4().hex[:8]}"
        engine = get_engine_for_shard(get_default_shard_name())
        with engine.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{role}"'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            connection.execute(
                text(f'GRANT SELECT ON "{schema}".credential TO "{role}"')
            )
        try:
            with session_on(schema) as db_session:
                insert_provider(db_session, encrypt_with_keyring(OLD, "sk-1"))
                db_session.execute(text(f'SET LOCAL ROLE "{role}"'))
                with pytest.raises(ProgrammingError, match="permission denied"):
                    rotate_schema(
                        db_session,
                        schema,
                        NEW,
                        SCRATCH_COLUMNS,
                        RotationMode.VERIFY,
                        None,
                    )
                db_session.rollback()
        finally:
            with engine.begin() as connection:
                connection.execute(text(f'DROP OWNED BY "{role}"'))
                connection.execute(text(f'DROP ROLE "{role}"'))

    def test_an_empty_schema_completes_every_mode(self) -> None:
        engine = get_engine_for_shard(get_default_shard_name())
        empty = f"tenant_{uuid.uuid4()}"
        with engine.begin() as connection:
            connection.execute(CreateSchema(empty))
        try:
            with (
                patch(
                    f"{ROTATION_MODULE}.get_tenant_ids_by_shard",
                    return_value={get_default_shard_name(): [empty]},
                ),
                patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW),
                patch(f"{ROTATION_MODULE}.get_cache_backend", return_value=None),
                patch(f"{ROTATION_MODULE}.MULTI_TENANT", False),
            ):
                for mode in RotationMode:
                    report = rotate_encryption_key(mode)
                    assert report.incomplete_reasons() == [], mode
                    assert len(report.schemas[0].absent_columns) == len(
                        discover_encrypted_columns()
                    )
        finally:
            with engine.begin() as connection:
                connection.execute(DropSchema(empty, cascade=True))


class TestConcurrentWriters:
    def test_update_by_a_legacy_writer_after_the_read_survives(
        self, schema: str
    ) -> None:
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, '{"v": "old"}')
            )
        newer = encrypt_with_keyring(OLD, '{"v": "newer"}')

        with patch(
            f"{ROTATION_MODULE}.encrypt_with_keyring",
            _concurrent_writer(schema, _set_credential(credential_id, newer), times=1),
        ):
            reports = run(schema, NEW, RotationMode.EXECUTE)

        # The first swap lost; the revisit converted the writer's value.
        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONVERTED: 1
        }
        with session_on(schema) as db_session:
            raw = raw_credential(db_session, credential_id)
        assert raw is not None and is_current_ciphertext(NEW, raw)
        assert decrypt_with_keyring(NEW, raw).plaintext == '{"v": "newer"}'

    def test_update_by_an_envelope_writer_after_the_read_survives(
        self, schema: str
    ) -> None:
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, '{"v": "old"}')
            )
        newer = encrypt_with_keyring(NEW, '{"v": "newer"}')

        with patch(
            f"{ROTATION_MODULE}.encrypt_with_keyring",
            _concurrent_writer(schema, _set_credential(credential_id, newer), times=1),
        ):
            reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CURRENT: 1
        }
        with session_on(schema) as db_session:
            assert raw_credential(db_session, credential_id) == newer

    def test_delete_after_the_read_is_not_resurrected(self, schema: str) -> None:
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, '{"v": "old"}')
            )

        def delete(db_session: Session) -> None:
            delete_credential(db_session, credential_id)

        with patch(
            f"{ROTATION_MODULE}.encrypt_with_keyring",
            _concurrent_writer(schema, delete, times=1),
        ):
            reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {}
        with session_on(schema) as db_session:
            assert raw_credential(db_session, credential_id) is None

    def test_a_writer_that_never_stops_is_reported_not_overwritten(
        self, schema: str
    ) -> None:
        """The lost-update case: the rotation must never write a plaintext it read
        before another writer saved a newer one."""
        with session_on(schema) as db_session:
            credential_id = insert_credential(
                db_session, encrypt_with_keyring(OLD, '{"v": 0}')
            )
        versions = iter(range(1, 100))

        def write_next_version(db_session: Session) -> None:
            _set_credential(
                credential_id,
                encrypt_with_keyring(OLD, json.dumps({"v": next(versions)})),
            )(db_session)

        with patch(
            f"{ROTATION_MODULE}.encrypt_with_keyring",
            _concurrent_writer(schema, write_next_version),
        ):
            reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CONFLICTED: 1
        }
        with session_on(schema) as db_session:
            raw = raw_credential(db_session, credential_id)
        assert raw is not None
        assert json.loads(decrypt_with_keyring(NEW, raw).plaintext) == {
            "v": 1 + rotation._CONFLICT_PASSES
        }


class TestOverlappingRunners:
    def test_two_runners_converge_without_losing_a_value(self, schema: str) -> None:
        total = 2 * rotation._BATCH_SIZE + 50
        with session_on(schema) as db_session:
            for index in range(total):
                insert_credential(
                    db_session, encrypt_with_keyring(OLD, json.dumps({"i": index}))
                )
        results: dict[str, list[rotation.ColumnReport]] = {}

        def runner(name: str) -> None:
            results[name] = run(schema, NEW, RotationMode.EXECUTE)

        threads = [threading.Thread(target=runner, args=(name,)) for name in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        converted = sum(
            counts(results[name], "credential.credential_json").get(
                ValueOutcome.CONVERTED, 0
            )
            for name in ("a", "b")
        )
        assert converted == total
        for name in ("a", "b"):
            assert (
                counts(results[name], "credential.credential_json").get(
                    ValueOutcome.CONFLICTED, 0
                )
                == 0
            )
        with session_on(schema) as db_session:
            rows = db_session.execute(
                select(CREDENTIAL_TABLE.c.credential_json.cast(LargeBinary))
            ).scalars()
            values = sorted(
                json.loads(decrypt_with_keyring(RETIRED, bytes(raw)).plaintext)["i"]
                for raw in rows
            )
        assert values == list(range(total))


class TestInterruptedRun:
    def test_a_crash_keeps_committed_batches_and_the_rerun_finishes(
        self, schema: str
    ) -> None:
        total = 2 * rotation._BATCH_SIZE + 50
        with session_on(schema) as db_session:
            for index in range(total):
                insert_credential(
                    db_session, encrypt_with_keyring(OLD, json.dumps({"i": index}))
                )
        swaps = 0
        real_swap = rotation._swap_ciphertext

        def crash_in_second_batch(*args: Any, **kwargs: Any) -> bool:
            nonlocal swaps
            swaps += 1
            if swaps == rotation._BATCH_SIZE + 10:
                raise RuntimeError("simulated crash")
            return real_swap(*args, **kwargs)

        with (
            patch(f"{ROTATION_MODULE}._swap_ciphertext", crash_in_second_batch),
            pytest.raises(RuntimeError, match="simulated crash"),
        ):
            run(schema, NEW, RotationMode.EXECUTE)

        with session_on(schema) as db_session:
            rows = [
                bytes(raw)
                for raw in db_session.execute(
                    select(CREDENTIAL_TABLE.c.credential_json.cast(LargeBinary))
                ).scalars()
            ]
        current = sum(is_current_ciphertext(NEW, raw) for raw in rows)
        assert current == rotation._BATCH_SIZE, (
            "one batch committed, the next rolled back"
        )

        reports = run(schema, NEW, RotationMode.EXECUTE)

        assert counts(reports, "credential.credential_json") == {
            ValueOutcome.CURRENT: rotation._BATCH_SIZE,
            ValueOutcome.CONVERTED: total - rotation._BATCH_SIZE,
        }


class TestSandboxDaemonKeys:
    @pytest.fixture
    def tenant_cache(self, schema: str) -> Generator[Any, None, None]:
        cache = get_cache_backend(tenant_id=schema)
        try:
            yield cache
        finally:
            cache.delete_prefix("sandbox_fc:")

    def test_daemon_key_is_re_encrypted_in_place(
        self, schema: str, tenant_cache: Any
    ) -> None:
        sandbox_id = uuid.uuid4()
        with session_on(schema) as db_session:
            db_session.execute(
                SANDBOX_TABLE.insert().values(
                    id=sandbox_id, user_id=uuid.uuid4(), status=SandboxStatus.RUNNING
                )
            )
            db_session.commit()
        with patch(f"{EE_MODULE}.get_keyring", return_value=OLD):
            set_sandbox_daemon_key(
                tenant_cache, sandbox_id, attempt=1, key=SecretStr("daemon-secret")
            )

        with session_on(schema) as db_session:
            reports, _ = rotate_schema(
                db_session,
                schema,
                NEW,
                SCRATCH_COLUMNS,
                RotationMode.EXECUTE,
                tenant_cache,
            )

        assert counts(reports, SANDBOX_DAEMON_KEY_COLUMN) == {ValueOutcome.CONVERTED: 1}
        with patch(f"{EE_MODULE}.get_keyring", return_value=RETIRED):
            key = get_sandbox_daemon_key(tenant_cache, sandbox_id, attempt=1)
        assert key is not None and key.get_secret_value() == "daemon-secret"
        with session_on(schema) as db_session:
            reports, _ = rotate_schema(
                db_session,
                schema,
                RETIRED,
                SCRATCH_COLUMNS,
                RotationMode.VERIFY,
                tenant_cache,
            )
        assert counts(reports, SANDBOX_DAEMON_KEY_COLUMN) == {ValueOutcome.CURRENT: 1}


SECOND_SHARD = "shard-rotation-b"


@pytest.fixture
def two_shards(
    second_database: str, monkeypatch: pytest.MonkeyPatch
) -> Generator[dict[str, Any], None, None]:
    """One tenant present on both shards, as it is mid-move, and a template on
    each shard, each holding one legacy credential."""
    monkeypatch.setattr(
        shard_registry,
        "ONYX_DB_SHARDS_JSON",
        f'{{"{SECOND_SHARD}": {{"db": "{second_database}"}}}}',
    )
    monkeypatch.setattr(shard_registry, "ONYX_DB_DEFAULT_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(shard_registry, "ONYX_DB_CATALOG_SHARD", DEFAULT_SHARD)
    monkeypatch.setattr(tenant_utils, "MULTI_TENANT", True)
    monkeypatch.setattr(rotation, "MULTI_TENANT", True)
    shard_registry.reset_shard_specs()

    # The template name is fixed, so this suite must not run alongside another
    # test that builds `tenant_template` on the same database.
    tenant = f"tenant_{uuid.uuid4()}"
    placed: dict[str, list[str]] = {
        DEFAULT_SHARD: [tenant, TENANT_TEMPLATE_SCHEMA],
        SECOND_SHARD: [tenant, TENANT_TEMPLATE_SCHEMA],
    }
    credential_ids: dict[tuple[str, str], int] = {}
    stack: list[Any] = []
    try:
        for shard_name, schema_names in placed.items():
            engine = get_engine_for_shard(shard_name)
            for schema_name in schema_names:
                context = scratch_schema(engine, schema_name)
                context.__enter__()
                stack.append(context)
                with session_on(schema_name, shard_name) as db_session:
                    credential_ids[(shard_name, schema_name)] = insert_credential(
                        db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON)
                    )
        refresh = MagicMock()
        with (
            patch(f"{ROTATION_MODULE}.get_tenant_ids_by_shard", return_value=placed),
            patch(
                f"{ROTATION_MODULE}.discover_encrypted_columns",
                return_value=SCRATCH_COLUMNS,
            ),
            patch(f"{ROTATION_MODULE}.get_head_revision", return_value="head-rev"),
            patch(f"{ROTATION_MODULE}.get_cache_backend", return_value=None),
            patch(f"{ROTATION_MODULE}.refresh_template_snapshot", refresh),
            patch(f"{ROTATION_MODULE}.require_pg_dump"),
        ):
            yield {
                "tenant": tenant,
                "placed": placed,
                "credential_ids": credential_ids,
                "refresh": refresh,
            }
    finally:
        for context in reversed(stack):
            context.__exit__(None, None, None)
        shard_registry.reset_shard_specs()


class TestPhysicalCoverage:
    def test_every_copy_on_every_shard_is_converted_and_snapshots_refreshed(
        self, two_shards: dict[str, Any]
    ) -> None:
        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            report = rotate_encryption_key(RotationMode.EXECUTE)

        assert report.incomplete_reasons() == []
        assert sorted((s.shard_name, s.schema_name) for s in report.schemas) == sorted(
            (shard, schema)
            for shard, schemas in two_shards["placed"].items()
            for schema in schemas
        )
        for (shard_name, schema_name), credential_id in two_shards[
            "credential_ids"
        ].items():
            with session_on(schema_name, shard_name) as db_session:
                raw = raw_credential(db_session, credential_id)
            assert raw is not None and is_current_ciphertext(NEW, raw), (
                shard_name,
                schema_name,
            )
        refresh: MagicMock = two_shards["refresh"]
        assert sorted(call.args for call in refresh.call_args_list) == [
            (DEFAULT_SHARD, "head-rev"),
            (SECOND_SHARD, "head-rev"),
        ]

    def test_snapshot_is_refreshed_on_every_execute_pass_over_the_template(
        self, two_shards: dict[str, Any]
    ) -> None:
        """A refresh that failed once must get another chance, so the re-dump does
        not depend on this run converting a row."""
        refresh: MagicMock = two_shards["refresh"]
        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            rotate_encryption_key(
                RotationMode.EXECUTE, only_schema=TENANT_TEMPLATE_SCHEMA
            )
        assert refresh.call_count == 2
        refresh.reset_mock()

        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            report = rotate_encryption_key(RotationMode.EXECUTE)

        assert report.incomplete_reasons() == []
        assert sorted(call.args for call in refresh.call_args_list) == [
            (DEFAULT_SHARD, "head-rev"),
            (SECOND_SHARD, "head-rev"),
        ]
        # The template goes first on each shard, before the tenant.
        assert [s.schema_name for s in report.schemas][:2] == [
            TENANT_TEMPLATE_SCHEMA,
            two_shards["tenant"],
        ]

    @pytest.mark.usefixtures("two_shards")
    def test_an_unknown_schema_name_is_an_error(self) -> None:
        with (
            patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW),
            pytest.raises(RuntimeError, match="No shard holds"),
        ):
            rotate_encryption_key(RotationMode.DRY_RUN, only_schema="tenant_missing")

    def test_only_schema_limits_the_run_to_that_schema_on_every_shard(
        self, two_shards: dict[str, Any]
    ) -> None:
        tenant = two_shards["tenant"]
        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            report = rotate_encryption_key(RotationMode.EXECUTE, only_schema=tenant)

        assert sorted((s.shard_name, s.schema_name) for s in report.schemas) == [
            (DEFAULT_SHARD, tenant),
            (SECOND_SHARD, tenant),
        ]
        for shard_name in (DEFAULT_SHARD, SECOND_SHARD):
            credential_id = two_shards["credential_ids"][
                (shard_name, TENANT_TEMPLATE_SCHEMA)
            ]
            with session_on(TENANT_TEMPLATE_SCHEMA, shard_name) as db_session:
                raw = raw_credential(db_session, credential_id)
            assert raw is not None and not is_current_ciphertext(NEW, raw)

    @pytest.mark.usefixtures("two_shards")
    def test_verify_reads_the_snapshot_a_new_tenant_would_be_cloned_from(
        self,
    ) -> None:
        """A stored dump still carrying legacy ciphertext fails verification even
        after every live schema is current."""
        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            rotate_encryption_key(RotationMode.EXECUTE)
        legacy_hex = encrypt_with_keyring(OLD, CREDENTIAL_JSON).hex()
        ddl = "".join(
            str(
                CreateTable(table, include_foreign_key_constraints=()).compile(
                    dialect=postgresql.dialect(),
                    schema_translate_map={None: TENANT_TEMPLATE_SCHEMA},
                    render_schema_translate=True,
                )
            ).strip()
            + ";\n"
            for table in (CREDENTIAL_TABLE, PROVIDER_TABLE)
        )
        stale_dump = ddl + (
            "INSERT INTO tenant_template.credential "
            "(source, credential_json, admin_public, curator_public) "
            f"VALUES ('ingestion_api', '\\x{legacy_hex}', true, false);\n"
        )
        current_hex = encrypt_with_keyring(NEW, CREDENTIAL_JSON).hex()
        fresh_dump = stale_dump.replace(legacy_hex, current_hex)

        with (
            patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW),
            patch(f"{ROTATION_MODULE}.get_snapshot", return_value=stale_dump),
        ):
            stale_report = rotate_encryption_key(RotationMode.VERIFY)
        with (
            patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW),
            patch(f"{ROTATION_MODULE}.get_snapshot", return_value=fresh_dump),
        ):
            fresh_report = rotate_encryption_key(RotationMode.VERIFY)

        snapshot_reports = [
            s for s in stale_report.schemas if s.schema_name == "snapshot@head-rev"
        ]
        assert [s.shard_name for s in snapshot_reports] == [DEFAULT_SHARD, SECOND_SHARD]
        assert all(
            s.total(ValueOutcome.STALE) == 1 and s.error is None
            for s in snapshot_reports
        )
        assert stale_report.incomplete_reasons() == ["2 value(s) stale"]
        assert fresh_report.incomplete_reasons() == []

    def test_execute_without_pg_dump_stops_before_any_row_changes(
        self, two_shards: dict[str, Any]
    ) -> None:
        with (
            patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW),
            patch(
                f"{ROTATION_MODULE}.require_pg_dump",
                side_effect=RuntimeError("pg_dump is not installed"),
            ),
            pytest.raises(RuntimeError, match="pg_dump"),
        ):
            rotate_encryption_key(RotationMode.EXECUTE)

        for (shard_name, schema_name), credential_id in two_shards[
            "credential_ids"
        ].items():
            with session_on(schema_name, shard_name) as db_session:
                raw = raw_credential(db_session, credential_id)
            assert raw is not None and not is_current_ciphertext(NEW, raw)

    @pytest.mark.usefixtures("two_shards")
    def test_a_missing_snapshot_fails_verification(self) -> None:
        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            rotate_encryption_key(RotationMode.EXECUTE)
        with (
            patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW),
            patch(f"{ROTATION_MODULE}.get_snapshot", return_value=None),
        ):
            report = rotate_encryption_key(RotationMode.VERIFY)

        assert report.incomplete_reasons() == [
            f"{DEFAULT_SHARD}/snapshot@head-rev failed: RuntimeError",
            f"{SECOND_SHARD}/snapshot@head-rev failed: RuntimeError",
        ]


@contextmanager
def _keep_engine(**_: Any) -> Iterator[None]:
    yield


class TestScript:
    @pytest.fixture
    def single_schema(self, schema: str) -> Generator[str, None, None]:
        with (
            patch(
                f"{ROTATION_MODULE}.get_tenant_ids_by_shard",
                return_value={get_default_shard_name(): [schema]},
            ),
            patch(
                f"{ROTATION_MODULE}.discover_encrypted_columns",
                return_value=SCRATCH_COLUMNS,
            ),
            patch(f"{ROTATION_MODULE}.get_cache_backend", return_value=None),
            patch(f"{ROTATION_MODULE}.MULTI_TENANT", False),
            # The script scopes its own engine; the test keeps the fixture's.
            patch("scripts.reencrypt_secrets.SqlEngine.scoped_engine", _keep_engine),
        ):
            yield schema

    def test_exit_status_follows_the_report(
        self, single_schema: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with session_on(single_schema) as db_session:
            insert_credential(db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON))
            bad_id = insert_credential(db_session, b"\xff\xfe not utf-8 \x80")

        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=OLD):
            assert reencrypt_main(["--dry-run"]) == 1
        assert "unreadable=1" in capsys.readouterr().out

        with session_on(single_schema) as db_session:
            delete_credential(db_session, bad_id)
            db_session.commit()

        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=OLD):
            assert reencrypt_main(["--dry-run"]) == 0
        assert "Complete." in capsys.readouterr().out

    def test_execute_then_verify_passes_and_reports_counts(
        self, single_schema: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with session_on(single_schema) as db_session:
            insert_credential(db_session, encrypt_with_keyring(OLD, CREDENTIAL_JSON))
            insert_provider(db_session, b"plain-key")

        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=NEW):
            assert reencrypt_main(["--verify"]) == 1
            out = capsys.readouterr().out
            assert "stale=1" in out and "INCOMPLETE" in out
            assert reencrypt_main([]) == 0
            out = capsys.readouterr().out
            assert "credential.credential_json: converted=1" in out
            assert "internet_search_provider.api_key: converted=1" in out
        with patch(f"{ROTATION_MODULE}.get_keyring", return_value=RETIRED):
            assert reencrypt_main(["--verify"]) == 0
        assert "Complete." in capsys.readouterr().out

    @pytest.mark.usefixtures("single_schema")
    def test_verify_without_a_write_key_is_refused(self) -> None:
        with (
            patch(f"{ROTATION_MODULE}.get_keyring", return_value=OLD),
            pytest.raises(RuntimeError, match="ENCRYPTION_WRITE_KEY_ID"),
        ):
            reencrypt_main(["--verify"])
