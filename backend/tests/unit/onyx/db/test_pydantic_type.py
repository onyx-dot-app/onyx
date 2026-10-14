"""Compiled statements preserve each JSON column's sanitization setting."""

import pytest
from pydantic import BaseModel
from sqlalchemy import bindparam, create_engine, select

from onyx.db.pydantic_type import PydanticType


class Payload(BaseModel):
    text: str


@pytest.mark.parametrize("sanitize_first", [False, True])
def test_cached_statements_keep_distinct_sanitization(sanitize_first: bool) -> None:
    engine = create_engine("sqlite://")
    payload = Payload(text="before\x00after")
    try:
        with engine.connect() as connection:
            for sanitize in (sanitize_first, not sanitize_first, sanitize_first):
                statement = select(
                    bindparam(
                        "payload",
                        type_=PydanticType(Payload, sanitize_strings=sanitize),
                    )
                )
                result = connection.execute(
                    statement, {"payload": payload}
                ).scalar_one()
                assert isinstance(result, Payload)
                assert result.text == ("beforeafter" if sanitize else payload.text)
    finally:
        engine.dispose()
