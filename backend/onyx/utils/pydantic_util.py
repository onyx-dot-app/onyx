from typing import Any

from pydantic import BaseModel


def shallow_model_dump(model_instance: BaseModel) -> dict[str, Any]:
    """Like model_dump(), but returns references to field values instead of
    deep copies. Use with model_construct() to avoid unnecessary memory
    duplication when building subclass instances."""
    return {
        field_name: getattr(model_instance, field_name)
        for field_name in model_instance.__class__.model_fields
    }
