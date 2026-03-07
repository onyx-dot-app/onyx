"""Rotate encryption key for all encrypted columns.

Dynamically discovers all columns using EncryptedString / EncryptedJson,
decrypts each value with the old key, and re-encrypts with the current
ENCRYPTION_KEY_SECRET.

The operation is idempotent: rows already encrypted with the current key
are skipped. Commits are made in batches so a crash mid-rotation can be
safely resumed by re-running.
"""

import json
from typing import Any

from sqlalchemy import LargeBinary
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.db.models import Base
from onyx.db.models import EncryptedJson
from onyx.db.models import EncryptedString
from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.logger import setup_logger

logger = setup_logger()

_BATCH_SIZE = 500


def _can_decrypt_with_current_key(data: bytes) -> bool:
    """Check if data is already encrypted with the current key.

    Passes the key explicitly so the fallback-to-raw-decode path in
    _decrypt_bytes is NOT triggered — a clean success/failure signal.
    """
    try:
        decrypt_bytes_to_string(data, key=ENCRYPTION_KEY_SECRET)
        return True
    except Exception:
        return False


def _discover_encrypted_columns() -> list[tuple[type, str, list[str], bool]]:
    """Walk all ORM models and find columns using EncryptedString/EncryptedJson.

    Returns list of (ModelClass, column_attr_name, [pk_attr_names], is_json).
    """
    results: list[tuple[type, str, list[str], bool]] = []

    for mapper in Base.registry.mappers:
        model_cls = mapper.class_
        pk_names = [col.key for col in mapper.primary_key]

        for prop in mapper.column_attrs:
            for col in prop.columns:
                if isinstance(col.type, EncryptedJson):
                    results.append((model_cls, prop.key, pk_names, True))
                elif isinstance(col.type, EncryptedString):
                    results.append((model_cls, prop.key, pk_names, False))

    return results


def rotate_encryption_key(
    db_session: Session,
    old_key: str | None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Decrypt all encrypted columns with old_key and re-encrypt with the current key.

    Args:
        db_session: Active database session.
        old_key: The previous encryption key. Pass None or "" if values were
                 not previously encrypted with a key.
        dry_run: If True, count rows that need rotation without modifying data.

    Returns:
        Dict of "table.column" -> number of rows re-encrypted (or would be).

    Commits every _BATCH_SIZE rows so that locks are held briefly and progress
    is preserved on crash. Already-rotated rows are detected and skipped,
    making the operation safe to re-run.
    """
    if not ENCRYPTION_KEY_SECRET:
        raise RuntimeError(
            "ENCRYPTION_KEY_SECRET is not set — cannot rotate. "
            "Set the target encryption key in the environment before running."
        )

    encrypted_columns = _discover_encrypted_columns()
    totals: dict[str, int] = {}

    for model_cls, col_name, pk_names, is_json in encrypted_columns:
        table_name: str = model_cls.__tablename__  # type: ignore[attr-defined]
        col_attr = getattr(model_cls, col_name)
        pk_attrs = [getattr(model_cls, pk) for pk in pk_names]

        # Read raw bytes directly, bypassing the TypeDecorator
        raw_col = col_attr.property.columns[0]

        stmt = select(*pk_attrs, raw_col.cast(LargeBinary)).where(col_attr.is_not(None))
        rows = db_session.execute(stmt).all()

        reencrypted = 0
        batch_pending = 0
        for row in rows:
            raw_bytes: bytes | None = row[-1]
            if raw_bytes is None:
                continue

            if _can_decrypt_with_current_key(raw_bytes):
                continue

            try:
                if not old_key:
                    decrypted_str = raw_bytes.decode("utf-8")
                else:
                    decrypted_str = decrypt_bytes_to_string(raw_bytes, key=old_key)
            except (ValueError, UnicodeDecodeError) as e:
                pk_vals = [row[i] for i in range(len(pk_names))]
                logger.warning(
                    f"Could not decrypt {table_name}.{col_name} "
                    f"row {pk_vals} — skipping: {e}"
                )
                continue

            if not dry_run:
                # For EncryptedJson, parse back to dict so the TypeDecorator
                # can json.dumps() it cleanly (avoids double-encoding).
                value: Any = json.loads(decrypted_str) if is_json else decrypted_str

                pk_filters = [pk_attr == row[i] for i, pk_attr in enumerate(pk_attrs)]
                update_stmt = (
                    update(model_cls).where(*pk_filters).values({col_name: value})
                )
                db_session.execute(update_stmt)
                batch_pending += 1

                if batch_pending >= _BATCH_SIZE:
                    db_session.commit()
                    batch_pending = 0
            reencrypted += 1

        # Flush remaining rows in this column
        if batch_pending > 0:
            db_session.commit()

        if reencrypted > 0:
            totals[f"{table_name}.{col_name}"] = reencrypted
            logger.info(
                f"{'[DRY RUN] Would re-encrypt' if dry_run else 'Re-encrypted'} "
                f"{reencrypted} value(s) in {table_name}.{col_name}"
            )

    return totals
