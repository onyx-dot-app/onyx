from enum import Enum
from typing import Any
from typing import Final
from typing import TypeGuard
from typing import TypeVar

from psycopg2 import errorcodes
from psycopg2 import OperationalError
from psycopg2.errors import ForeignKeyViolation
from psycopg2.errors import UniqueViolation
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from onyx.db.models import Base

_T = TypeVar("_T")


class UnsetType:
    """Sentinel distinguishing 'not provided' from None/falsy in patch helpers.

    Use as the default for optional parameters whose caller might legitimately
    want to set the column to `None`. Typed as a dedicated class so unions
    like `str | UnsetType` survive type checking — `str | Any` would collapse
    to `Any` and silently disable enforcement at the call site.
    """


UNSET: Final[UnsetType] = UnsetType()


def is_set(value: _T | UnsetType) -> TypeGuard[_T]:
    """True if a patch field was provided. Narrows away ``UnsetType`` so the
    value can be assigned in the guarded branch."""
    return not isinstance(value, UnsetType)


def none_as_unset(value: _T | None) -> _T | UnsetType:
    """Map a request field's ``None`` (omitted) to ``UNSET`` for a patch helper.

    ONLY for non-nullable patch fields. If the column is nullable — i.e. ``None``
    is a legitimate "clear to NULL" value — this silently turns that clear into a
    no-op; use ``model_fields_set`` to tell omitted from explicit null instead.
    """
    return UNSET if value is None else value


def is_unique_violation(exc: IntegrityError, constraint: str) -> bool:
    """True iff the IntegrityError came from the named unique constraint/index.

    Postgres surfaces the violated constraint via `diag.constraint_name` on
    the underlying psycopg2 error. Callers can use this to translate the
    specific collision into a structured `OnyxError(DUPLICATE_RESOURCE)` while
    letting unrelated integrity errors (FK violations, NOT NULL, etc.) bubble
    up unchanged.
    """
    orig = exc.orig
    return (
        isinstance(orig, UniqueViolation)
        and getattr(orig.diag, "constraint_name", None) == constraint
    )


def is_fk_violation(exc: IntegrityError) -> bool:
    """True iff the IntegrityError is a foreign-key violation."""
    return isinstance(exc.orig, ForeignKeyViolation)


def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.key: getattr(model, c.key) for c in inspect(model).mapper.column_attrs}


RETRYABLE_PG_CODES = {
    errorcodes.SERIALIZATION_FAILURE,  # '40001'
    errorcodes.DEADLOCK_DETECTED,  # '40P01'
    errorcodes.CONNECTION_EXCEPTION,  # '08000'
    errorcodes.CONNECTION_DOES_NOT_EXIST,  # '08003'
    errorcodes.CONNECTION_FAILURE,  # '08006'
    errorcodes.TRANSACTION_ROLLBACK,  # '40000'
}


def is_retryable_sqlalchemy_error(exc: BaseException) -> bool:
    """Helper function for use with tenacity's retry_if_exception as the callback"""
    if isinstance(exc, OperationalError):
        pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
        return pgcode in RETRYABLE_PG_CODES
    return False


class DocumentRow(BaseModel):
    id: str
    doc_metadata: dict[str, Any]
    external_user_group_ids: list[str]


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class DiscordChannelView(BaseModel):
    channel_id: int
    channel_name: str
    channel_type: str = "text"  # text, forum
    is_private: bool = False  # True if @everyone cannot view the channel
