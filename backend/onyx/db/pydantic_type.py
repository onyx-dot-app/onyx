import json
from typing import Any, Optional

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator
from typing_extensions import TypeForm

from onyx.utils.postgres_sanitization import sanitize_json_like


class PydanticType(TypeDecorator):
    impl = JSONB
    # The model class and serialization options are stable for each column.
    cache_ok = True

    def __init__(
        self,
        pydantic_model: TypeForm[BaseModel],
        sanitize_strings: bool = False,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_model = pydantic_model
        self._adapter = TypeAdapter[BaseModel](pydantic_model)
        self.sanitize_strings = sanitize_strings

    def process_bind_param(
        self,
        value: Optional[BaseModel],
        dialect: Any,  # noqa: ARG002
    ) -> Optional[dict]:
        if value is not None:
            if self.sanitize_strings:
                return sanitize_json_like(value.model_dump(mode="json"))
            return json.loads(value.model_dump_json())
        return None

    def process_result_value(
        self,
        value: Optional[dict],
        dialect: Any,  # noqa: ARG002
    ) -> Optional[BaseModel]:
        if value is not None:
            return self._adapter.validate_python(value)
        return None


class PydanticListType(TypeDecorator):
    impl = JSONB
    # The only state is the item type, so statements stay cacheable.
    cache_ok = True

    def __init__(
        self, pydantic_model: TypeForm[BaseModel], *args: Any, **kwargs: Any
    ) -> None:
        """``pydantic_model`` is a model or a union of models, such as a
        discriminated union."""
        super().__init__(*args, **kwargs)
        self.pydantic_model = pydantic_model
        self._adapter = TypeAdapter[BaseModel](pydantic_model)

    def process_bind_param(
        self,
        value: Optional[list[BaseModel]],
        dialect: Any,  # noqa: ARG002
    ) -> Optional[list[dict]]:
        if value is not None:
            return [json.loads(item.model_dump_json()) for item in value]
        return None

    def process_result_value(
        self,
        value: Optional[list[dict]],
        dialect: Any,  # noqa: ARG002
    ) -> Optional[list[BaseModel]]:
        if value is not None:
            return [self._adapter.validate_python(item) for item in value]
        return None
