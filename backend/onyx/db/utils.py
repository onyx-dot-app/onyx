import re
from typing import Any

from sqlalchemy import inspect

from onyx.db.models import Base


SCHEMA_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def is_valid_schema_name(name: str) -> bool:
    return SCHEMA_NAME_REGEX.match(name) is not None


def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.key: getattr(model, c.key) for c in inspect(model).mapper.column_attrs}  # type: ignore
