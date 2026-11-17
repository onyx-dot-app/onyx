"""Re-encrypt every stored secret under the keyring's write key while the
application keeps running.

Every encrypted column is discovered from the ORM models and read in primary-key
order, a batch at a time, as raw bytes. Each value is classified against the
process keyring and, in execute mode, rewritten with a compare-and-swap on the
raw bytes: a row that another writer changed or deleted meanwhile is left alone,
counted as a conflict, and revisited. The plaintext is re-encrypted as the same
string, so a JSON value keeps its bytes, and `onupdate` timestamps are pinned to
their current value.

Coverage is physical: every schema present on every shard, which includes the
template and both copies of a tenant mid-move. Sandbox daemon keys in the tenant
cache are rewritten the same way. After the template of a shard changes, its
stored snapshot is re-dumped so a tenant cloned later carries the new format.

The run is idempotent and commits per batch, so an interrupted run resumes by
running again. Two overlapping runs are safe: the swap lets only one rewrite a
row, and the other counts a conflict.
"""

import json
from collections import Counter
from collections.abc import Iterator, Sequence
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, LargeBinary, Table, bindparam, select, update
from sqlalchemy.orm import Session

from ee.onyx.db.tenant_snapshot import (
    cloned_snapshot,
    get_head_revision,
    get_snapshot,
    refresh_template_snapshot,
)
from ee.onyx.utils.encryption import (
    ENVELOPE_VERSION,
    DecryptionError,
    Keyring,
    decrypt_with_keyring,
    encrypt_with_keyring,
    get_keyring,
    parse_envelope_header,
)
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_for_schema_on_shard
from onyx.db.engine.tenant_utils import get_tenant_ids_by_shard
from onyx.db.models import Base, EncryptedJson, EncryptedString, Sandbox
from onyx.microvm.registry import (
    read_sandbox_daemon_key_ciphertext,
    replace_sandbox_daemon_key_ciphertext,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT, TENANT_TEMPLATE_SCHEMA

logger = setup_logger()

_BATCH_SIZE = 200
_CONFLICT_PASSES = 3
SANDBOX_DAEMON_KEY_COLUMN = "cache.sandbox_daemon_key"


class RotationMode(str, Enum):
    # Classify every value; write nothing.
    DRY_RUN = "dry-run"
    # Rewrite every stale value.
    EXECUTE = "execute"
    # Decrypt every value, including current ones; write nothing.
    VERIFY = "verify"


class ValueOutcome(str, Enum):
    CURRENT = "current"
    CONVERTED = "converted"
    # Readable but not under the write key. Converted in execute mode.
    STALE = "stale"
    # Changed or deleted between the read and the swap, in every revisit pass.
    CONFLICTED = "conflicted"
    # Failed the header, the authentication tag, UTF-8, or the JSON structure.
    UNREADABLE = "unreadable"
    # An envelope under a version or key id this keyring does not have.
    UNSUPPORTED = "unsupported"


class EncryptedColumn(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    table: Table
    column: Column
    # Every encrypted table has a single-column key; discovery refuses another.
    primary_key: Column
    is_json: bool

    @property
    def name(self) -> str:
        return f"{self.table.name}.{self.column.name}"


class ColumnReport(BaseModel):
    name: str
    counts: dict[ValueOutcome, int]


class SchemaReport(BaseModel):
    shard_name: str
    schema_name: str
    columns: list[ColumnReport] = []
    # The exception type when the schema could not be processed. Never a message:
    # a database error can quote the statement and its bound ciphertext.
    error: str | None = None

    def total(self, outcome: ValueOutcome) -> int:
        return sum(column.counts.get(outcome, 0) for column in self.columns)


class RotationReport(BaseModel):
    mode: RotationMode
    schemas: list[SchemaReport] = []

    def total(self, outcome: ValueOutcome) -> int:
        return sum(schema.total(outcome) for schema in self.schemas)

    def incomplete_reasons(self) -> list[str]:
        """Empty when the run reached its goal. A dry run only needs every value
        readable; execute also needs no conflicts left; verify needs every value
        current."""
        reasons = [
            f"{schema.shard_name}/{schema.schema_name} failed: {schema.error}"
            for schema in self.schemas
            if schema.error is not None
        ]
        blocking = [ValueOutcome.UNREADABLE, ValueOutcome.UNSUPPORTED]
        if self.mode == RotationMode.EXECUTE:
            blocking += [ValueOutcome.CONFLICTED, ValueOutcome.STALE]
        if self.mode == RotationMode.VERIFY:
            blocking += [
                ValueOutcome.CONFLICTED,
                ValueOutcome.STALE,
                ValueOutcome.CONVERTED,
            ]
        for outcome in blocking:
            count = self.total(outcome)
            if count:
                reasons.append(f"{count} value(s) {outcome.value}")
        return reasons


def discover_encrypted_columns() -> list[EncryptedColumn]:
    """Every column stored through EncryptedString or EncryptedJson, from the ORM
    registry, so a new encrypted column is covered without a change here."""
    found: dict[str, EncryptedColumn] = {}
    for mapper in Base.registry.mappers:
        for prop in mapper.column_attrs:
            for column in prop.columns:
                table = column.table
                if not isinstance(column.type, (EncryptedString, EncryptedJson)):
                    continue
                if not isinstance(table, Table):
                    raise AssertionError("mapped columns belong to tables")
                primary_key = list(table.primary_key.columns)
                if len(primary_key) != 1:
                    raise RuntimeError(
                        f"{table.name} has {len(primary_key)} primary key columns; "
                        "key rotation pages by a single-column key"
                    )
                encrypted = EncryptedColumn(
                    table=table,
                    column=column,
                    primary_key=primary_key[0],
                    is_json=isinstance(column.type, EncryptedJson),
                )
                found.setdefault(encrypted.name, encrypted)
    return [found[name] for name in sorted(found)]


class _ClassifiedValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: ValueOutcome
    # Set for a stale value, which is what a conversion re-encrypts.
    plaintext: str | None = None


def classify_value(
    keyring: Keyring, raw: bytes, is_json: bool, decrypt_current: bool
) -> _ClassifiedValue:
    """Where one stored value stands against the keyring. A current value is
    decrypted only when asked, which verification does and conversion skips."""
    try:
        parsed = parse_envelope_header(raw)
    except DecryptionError:
        return _ClassifiedValue(outcome=ValueOutcome.UNREADABLE)
    current = False
    if parsed is not None:
        header, _ = parsed
        if header.version != ENVELOPE_VERSION or header.key_id not in keyring.keys:
            return _ClassifiedValue(outcome=ValueOutcome.UNSUPPORTED)
        current = header.key_id == keyring.write_key_id
    if current and not decrypt_current:
        return _ClassifiedValue(outcome=ValueOutcome.CURRENT)

    try:
        plaintext = decrypt_with_keyring(keyring, raw).plaintext
    except DecryptionError:
        return _ClassifiedValue(outcome=ValueOutcome.UNREADABLE)
    if is_json:
        try:
            json.loads(plaintext)
        except ValueError:
            return _ClassifiedValue(outcome=ValueOutcome.UNREADABLE)
    if current:
        return _ClassifiedValue(outcome=ValueOutcome.CURRENT)
    return _ClassifiedValue(outcome=ValueOutcome.STALE, plaintext=plaintext)


def _raw_values_select(encrypted: EncryptedColumn) -> Any:
    # The cast reads the stored bytes past the type decorator.
    return (
        select(encrypted.primary_key, encrypted.column.cast(LargeBinary))
        .where(encrypted.column.is_not(None))
        .order_by(encrypted.primary_key)
    )


def _batches(
    db_session: Session, encrypted: EncryptedColumn
) -> Iterator[list[tuple[Any, bytes]]]:
    """Rows as (primary key, raw bytes), in key order, one bounded batch per
    transaction. Keyset pagination keeps a batch cheap on a large table and
    independent of rows that change between batches."""
    last: Any = None
    while True:
        stmt = _raw_values_select(encrypted).limit(_BATCH_SIZE)
        if last is not None:
            stmt = stmt.where(encrypted.primary_key > last)
        rows = [(row[0], bytes(row[1])) for row in db_session.execute(stmt)]
        if not rows:
            return
        yield rows
        last = rows[-1][0]


def _swap_ciphertext(
    db_session: Session,
    encrypted: EncryptedColumn,
    key: Any,
    expected: bytes,
    replacement: bytes,
) -> bool:
    """Replace the stored bytes only while they still equal `expected`. The
    typed parameters bypass the type decorator, and every `onupdate` column is
    set to itself so the row's timestamps do not move."""
    pinned = {
        column: column
        for column in encrypted.table.columns
        if column.onupdate is not None
    }
    stmt = (
        update(encrypted.table)
        .where(encrypted.primary_key == key)
        .where(encrypted.column == bindparam("expected", type_=LargeBinary))
        .values(
            {encrypted.column: bindparam("replacement", type_=LargeBinary), **pinned}
        )
    )
    result = db_session.execute(
        stmt, {"expected": expected, "replacement": replacement}
    )
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


def _process_rows(
    db_session: Session,
    keyring: Keyring,
    encrypted: EncryptedColumn,
    rows: Sequence[tuple[Any, bytes]],
    mode: RotationMode,
    counts: Counter[ValueOutcome],
) -> list[Any]:
    """Classify and, in execute mode, convert the rows. Returns the keys whose swap
    lost to another writer."""
    conflicted: list[Any] = []
    for key, raw in rows:
        classified = classify_value(
            keyring, raw, encrypted.is_json, decrypt_current=mode == RotationMode.VERIFY
        )
        if classified.outcome != ValueOutcome.STALE or mode != RotationMode.EXECUTE:
            counts[classified.outcome] += 1
            continue
        if classified.plaintext is None:
            raise AssertionError("a stale value carries its plaintext")
        replacement = encrypt_with_keyring(keyring, classified.plaintext)
        if _swap_ciphertext(db_session, encrypted, key, raw, replacement):
            counts[ValueOutcome.CONVERTED] += 1
        else:
            conflicted.append(key)
    db_session.commit()
    return conflicted


def rotate_column(
    db_session: Session,
    keyring: Keyring,
    encrypted: EncryptedColumn,
    mode: RotationMode,
) -> ColumnReport:
    counts: Counter[ValueOutcome] = Counter()
    conflicted: list[Any] = []
    for rows in _batches(db_session, encrypted):
        conflicted += _process_rows(db_session, keyring, encrypted, rows, mode, counts)

    # A conflicted row was rewritten by another writer. Read it again: a new-format
    # writer left it current, a legacy writer left it stale, a delete left nothing.
    for _ in range(_CONFLICT_PASSES):
        if not conflicted:
            break
        revisit, conflicted = conflicted, []
        for start in range(0, len(revisit), _BATCH_SIZE):
            chunk = revisit[start : start + _BATCH_SIZE]
            stmt = _raw_values_select(encrypted).where(encrypted.primary_key.in_(chunk))
            rows = [(row[0], bytes(row[1])) for row in db_session.execute(stmt)]
            conflicted += _process_rows(
                db_session, keyring, encrypted, rows, mode, counts
            )
    if conflicted:
        counts[ValueOutcome.CONFLICTED] += len(conflicted)
    return ColumnReport(name=encrypted.name, counts=dict(counts))


def rotate_sandbox_daemon_keys(
    db_session: Session,
    tenant_cache: CacheBackend,
    keyring: Keyring,
    mode: RotationMode,
) -> ColumnReport:
    """The guest daemon keys of this tenant's sandboxes, held in the cache with no
    TTL. Sandbox ids come from the table, since the cache cannot be listed."""
    counts: Counter[ValueOutcome] = Counter()
    last: Any = None
    while True:
        stmt = select(Sandbox.id).order_by(Sandbox.id).limit(_BATCH_SIZE)
        if last is not None:
            stmt = stmt.where(Sandbox.id > last)
        sandbox_ids = list(db_session.scalars(stmt))
        if not sandbox_ids:
            break
        for sandbox_id in sandbox_ids:
            stored = read_sandbox_daemon_key_ciphertext(tenant_cache, sandbox_id)
            if stored is None:
                continue
            classified = classify_value(
                keyring,
                stored.ciphertext,
                is_json=False,
                decrypt_current=mode == RotationMode.VERIFY,
            )
            if classified.outcome != ValueOutcome.STALE or mode != RotationMode.EXECUTE:
                counts[classified.outcome] += 1
                continue
            if classified.plaintext is None:
                raise AssertionError("a stale value carries its plaintext")
            replacement = encrypt_with_keyring(keyring, classified.plaintext)
            if replace_sandbox_daemon_key_ciphertext(
                tenant_cache, sandbox_id, stored, replacement
            ):
                counts[ValueOutcome.CONVERTED] += 1
            else:
                # The sandbox claimed or replaced its key meanwhile, under the write
                # key. The next run confirms it.
                counts[ValueOutcome.CONFLICTED] += 1
        last = sandbox_ids[-1]
    return ColumnReport(name=SANDBOX_DAEMON_KEY_COLUMN, counts=dict(counts))


def rotate_schema(
    db_session: Session,
    keyring: Keyring,
    columns: Sequence[EncryptedColumn],
    mode: RotationMode,
    tenant_cache: CacheBackend | None,
) -> list[ColumnReport]:
    reports = [rotate_column(db_session, keyring, column, mode) for column in columns]
    if tenant_cache is not None:
        reports.append(
            rotate_sandbox_daemon_keys(db_session, tenant_cache, keyring, mode)
        )
    return reports


def _is_workspace(schema_name: str) -> bool:
    """A tenant's own schema, as opposed to the template and its scratch copies,
    which hold no sandboxes and have no cache."""
    return not schema_name.startswith(TENANT_TEMPLATE_SCHEMA)


def _run_on_schema(
    shard_name: str,
    schema_name: str,
    keyring: Keyring,
    columns: Sequence[EncryptedColumn],
    mode: RotationMode,
    tenant_cache: CacheBackend | None,
) -> SchemaReport:
    report = SchemaReport(shard_name=shard_name, schema_name=schema_name)
    try:
        with get_session_for_schema_on_shard(
            shard_name=shard_name, schema_name=schema_name
        ) as db_session:
            report.columns = rotate_schema(
                db_session, keyring, columns, mode, tenant_cache
            )
    except Exception as e:
        logger.error(
            "Key rotation failed on %s/%s: %s", shard_name, schema_name, _cause(e)
        )
        report.error = type(e).__name__
    return report


def _cause(error: Exception) -> str:
    """The first line of an error: a database error quotes the statement and its
    bound ciphertext on the lines after it."""
    first_line = str(error).splitlines()[:1]
    return f"{type(error).__name__}: {first_line[0] if first_line else ''}"


def _verify_snapshot(
    shard_name: str,
    head_revision: str,
    keyring: Keyring,
    columns: Sequence[EncryptedColumn],
) -> SchemaReport:
    """What a tenant cloned right now would hold: the head snapshot, built into a
    scratch schema and read like any other."""
    label = f"snapshot@{head_revision}"
    report = SchemaReport(shard_name=shard_name, schema_name=label)
    try:
        dump = get_snapshot(shard_name, head_revision)
        if dump is None:
            raise RuntimeError("no snapshot stored for the head revision")
        with cloned_snapshot(shard_name, dump) as scratch:
            with get_session_for_schema_on_shard(
                shard_name=shard_name, schema_name=scratch
            ) as db_session:
                report.columns = rotate_schema(
                    db_session, keyring, columns, RotationMode.VERIFY, None
                )
    except Exception as e:
        logger.error("Snapshot check failed on %s: %s", shard_name, _cause(e))
        report.error = type(e).__name__
    return report


def _template_first(schema_names: Sequence[str]) -> list[str]:
    """The template before the tenants: its snapshot is re-dumped as soon as it
    is converted, so a tenant cloned during the long tail gets the new format."""
    return sorted(schema_names, key=lambda name: (name != TENANT_TEMPLATE_SCHEMA, name))


def rotate_encryption_key(
    mode: RotationMode, only_schema: str | None = None
) -> RotationReport:
    """Run one mode over every physical schema on every shard, or over one schema
    wherever it exists. Execute and verify need a write key; a dry run reports
    what is readable without one."""
    keyring = get_keyring()
    if mode != RotationMode.DRY_RUN and keyring.write_key_id is None:
        raise RuntimeError(
            f"ENCRYPTION_WRITE_KEY_ID is not set, so there is no target to {mode.value}"
        )
    columns = discover_encrypted_columns()
    head_revision = get_head_revision() if MULTI_TENANT else None
    if MULTI_TENANT and head_revision is None:
        raise RuntimeError("Could not determine the head revision")

    report = RotationReport(mode=mode)
    # A tenant mid-move has a schema on two shards but one cache; sweep it once.
    swept_caches: set[str] = set()
    for shard_name, schema_names in get_tenant_ids_by_shard().items():
        for schema_name in _template_first(schema_names):
            if only_schema is not None and schema_name != only_schema:
                continue
            tenant_cache = None
            if _is_workspace(schema_name) and schema_name not in swept_caches:
                swept_caches.add(schema_name)
                tenant_cache = get_cache_backend(tenant_id=schema_name)
            schema_report = _run_on_schema(
                shard_name, schema_name, keyring, columns, mode, tenant_cache
            )
            report.schemas.append(schema_report)
            logger.info(
                "Key rotation (%s) %s/%s: %s",
                mode.value,
                shard_name,
                schema_name,
                schema_report.error
                or {
                    outcome.value: schema_report.total(outcome)
                    for outcome in ValueOutcome
                },
            )
            # Re-dumped after every clean pass, not only after a conversion: a
            # refresh that failed in an earlier run must get another chance.
            if (
                MULTI_TENANT
                and head_revision is not None
                and schema_name == TENANT_TEMPLATE_SCHEMA
                and mode == RotationMode.EXECUTE
                and schema_report.error is None
            ):
                try:
                    refresh_template_snapshot(shard_name, head_revision)
                except Exception as e:
                    logger.error(
                        "Snapshot refresh failed on %s: %s", shard_name, _cause(e)
                    )
                    schema_report.error = type(e).__name__
        if MULTI_TENANT and head_revision is not None and mode == RotationMode.VERIFY:
            if only_schema is None or only_schema == TENANT_TEMPLATE_SCHEMA:
                report.schemas.append(
                    _verify_snapshot(shard_name, head_revision, keyring, columns)
                )
    if only_schema is not None and not report.schemas:
        raise RuntimeError(f"No shard holds a schema named {only_schema!r}")
    return report
