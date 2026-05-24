from typing import Any
from typing import TypeVar

from pydantic import BaseModel
from pydantic import TypeAdapter
from pydantic import ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

T = TypeVar("T")


def shallow_model_dump(model_instance: BaseModel) -> dict[str, Any]:
    """Like model_dump(), but returns references to field values instead of
    deep copies. Use with model_construct() to avoid unnecessary memory
    duplication when building subclass instances."""
    return {
        field_name: getattr(model_instance, field_name)
        for field_name in model_instance.__class__.model_fields
    }


def parse_json_form_field(raw: str, adapter: TypeAdapter[T], field_name: str) -> T:
    """Parse a JSON-encoded multipart form field into a validated value.

    Multipart endpoints carry structured fields (lists, objects) as JSON
    strings. This validates ``raw`` against ``adapter`` (e.g. a module-level
    ``TypeAdapter(list[str])``) and raises ``OnyxError(INVALID_INPUT)`` naming
    the field on malformed input — covering both bad JSON and wrong shape —
    rather than leaking a pydantic ``ValidationError`` to the client."""
    try:
        return adapter.validate_json(raw)
    except ValidationError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{field_name} is not valid JSON of the expected shape.",
        ) from e
