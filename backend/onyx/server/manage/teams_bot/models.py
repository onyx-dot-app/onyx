from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from onyx.utils.encryption import is_masked_credential


class TeamsBotConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    persona_id: int | None = Field(ge=0)
    client_secret: SecretStr | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("client_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            secret = value.get_secret_value()
            if not secret.strip() or is_masked_credential(secret):
                raise ValueError("Supply the actual client secret.")
        return value


class TeamsBotConfigCreate(TeamsBotConfigUpdate):
    enabled: bool = False
    persona_id: int | None = Field(default=None, ge=0)
    app_id: UUID
    directory_id: UUID
    client_secret: SecretStr = Field(min_length=1, max_length=4096)


class TeamsBotConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    app_id: UUID
    directory_id: UUID
    enabled: bool
    persona_id: int | None
