from dataclasses import dataclass
from enum import Enum
from typing import Any

from psycopg2 import errorcodes
from psycopg2 import OperationalError
from sqlalchemy import ColumnElement
from sqlalchemy import inspect

from onyx.db.models import Base
from onyx.db.models import Document
from onyx.db.models import DocumentColumns


def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.key: getattr(model, c.key) for c in inspect(model).mapper.column_attrs}  # type: ignore


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


class FilterOperation(str, Enum):
    LIKE = "like"
    JSON_CONTAINS = "json_contains"  # Check if JSON field contains a key-value pair


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


@dataclass
class DocumentFilter:
    field: DocumentColumns
    operation: FilterOperation
    value: Any = None
    # For JSON operations, specify the JSON key to check
    json_key: str | None = None


def build_where_clause_from_filter(
    filter: DocumentFilter,
) -> ColumnElement[bool] | None:
    """Convert a DocumentFilter object into a SQLAlchemy where clause.

    Args:
        filter: DocumentFilter object

    Returns:
        SQLAlchemy ColumnElement representing the where clause, or None if no filter
    """

    # Get the column attribute from the Document model
    column = getattr(Document, filter.field)

    if filter.operation == FilterOperation.LIKE:
        return column.like(filter.value)
    elif filter.operation == FilterOperation.JSON_CONTAINS:
        if filter.json_key is None:
            raise ValueError("json_key is required for JSON_CONTAINS operation")
        # For PostgreSQL JSONB, use the ->> operator to extract and compare
        return column.op("->>")(filter.json_key) == filter.value
    else:
        raise ValueError(f"Unsupported operation: {filter.operation}")

    return None
