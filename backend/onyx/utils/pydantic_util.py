from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

T = TypeVar("T")


def shallow_model_dump(model_instance: BaseModel) -> dict[str, Any]:
    """Like model_dump(), but returns references to field values instead of
    deep copies. Use with model_construct() to avoid unnecessary memory
    duplication when building subclass instances."""
    return {
        field_name: getattr(model_instance, field_name)  # ods: ignore[getattr]
        for field_name in model_instance.__class__.model_fields
    }


def as_base[B: BaseModel](model: B, base: type[B]) -> B:
    """`model` as an instance of `base`, one of its classes; subclass fields are
    dropped. Returns `model` when it already is exactly a `base`."""
    if type(model) is base:
        return model
    fields = shallow_model_dump(model)
    return base(**{name: fields[name] for name in base.model_fields})


def parse_json_form_field(raw: str, adapter: TypeAdapter[T], field_name: str) -> T:
    """Parse a JSON-encoded multipart form field, validating against ``adapter``.
    Raises ``OnyxError(INVALID_INPUT)`` naming the field on bad JSON or wrong
    shape instead of leaking a pydantic ``ValidationError``."""
    try:
        return adapter.validate_json(raw)
    except ValidationError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{field_name} is not valid JSON of the expected shape.",
        ) from e
