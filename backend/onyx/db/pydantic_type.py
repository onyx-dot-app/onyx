import json
from typing import Any
from typing import Optional
from typing import Type

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator


class PydanticType(TypeDecorator):
    impl = JSONB

    def __init__(
        self, pydantic_model: Type[BaseModel], *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_model = pydantic_model

    def process_bind_param(
        self, value: Optional[BaseModel], dialect: Any
    ) -> Optional[dict]:
        if value is not None:
            return json.loads(value.json())
        return None

    def process_result_value(
        self, value: Optional[dict], dialect: Any
    ) -> Optional[BaseModel]:
        if value is not None:
            return self.pydantic_model.parse_obj(value)
        return None


class PydanticListType(TypeDecorator):
    impl = JSONB

    def __init__(
        self, pydantic_model: Type[BaseModel], *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.pydantic_model = pydantic_model

    def process_bind_param(
        self, value: Optional[list[BaseModel]], dialect: Any
    ) -> Optional[list[dict]]:
        if value is not None:
            return [json.loads(item.model_dump_json()) for item in value]
        return None

    def process_result_value(
        self, value: Optional[list[dict]], dialect: Any
    ) -> Optional[list[BaseModel]]:
        if value is not None:
            return [self.pydantic_model.model_validate(item) for item in value]
        return None
