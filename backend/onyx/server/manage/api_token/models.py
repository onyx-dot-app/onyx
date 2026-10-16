from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field


class NewApiToken(BaseModel):
    """A key typed into the field. Saving it creates a token row."""

    type: Literal["new"] = "new"
    value: str


class ExistingApiToken(BaseModel):
    """A saved token picked from the list, or kept unchanged on an edit."""

    type: Literal["existing"] = "existing"
    id: int


def _plain_string_is_new(value: Any) -> Any:
    # Clients that send the key as a plain string (Terraform, older scripts)
    # keep working: the string is a new key.
    if isinstance(value, str):
        return {"type": "new", "value": value}
    return value


ApiTokenInput = Annotated[
    NewApiToken | ExistingApiToken,
    Field(discriminator="type"),
    BeforeValidator(_plain_string_is_new),
]


def keep_omitted_api_token(
    value: NewApiToken | ExistingApiToken | None,
    *,
    was_sent: bool,
    current_token_id: int | None,
) -> NewApiToken | ExistingApiToken | None:
    """An update that leaves the key field out keeps the current key; only an
    explicit null clears it. Clients that send write-only keys (Terraform)
    leave the field out when the key has not changed."""
    if was_sent or current_token_id is None:
        return value
    return ExistingApiToken(id=current_token_id)


class ApiTokenUsage(BaseModel):
    """One place that uses a token, e.g. kind "llm_provider", name "OpenAI"."""

    kind: str
    name: str


class ApiTokenView(BaseModel):
    id: int
    platform: str
    masked_value: str
    usages: list[ApiTokenUsage]


class ApiTokenRotateRequest(BaseModel):
    value: str
