from pydantic import BaseModel
from pydantic import field_validator
from pydantic import ValidationInfo

from onyx.auth.schemas import ApiKeyType
from onyx.auth.schemas import UserRole


class CreateAPIKeyArgs(BaseModel):
    """Arguments for creating a new API key.
    - type: Required to specify PAT or Service Account
    - role: Required for Service Accounts, omitted for PATs (validated at runtime)
    - name: Optional display name
    """

    type: ApiKeyType  # Always required for creation
    name: str | None = None
    role: UserRole | None = None

    @field_validator("role")
    @classmethod
    def validate_role_requirement(
        cls, role: UserRole | None, info: ValidationInfo
    ) -> UserRole | None:
        key_type = info.data.get("type")
        if key_type == ApiKeyType.SERVICE_ACCOUNT and role is None:
            raise ValueError("Service account keys require a role")
        if key_type == ApiKeyType.PERSONAL_ACCESS_TOKEN and role is not None:
            raise ValueError("Personal access tokens should not have a role")
        return role


class UpdateAPIKeyArgs(BaseModel):
    """Arguments for updating an existing API key.
    - name: Optional, can be updated for both PATs and Service Accounts
    - role: Optional, only valid for Service Accounts (validated by backend based on existing key type)
    """

    name: str | None = None
    role: UserRole | None = None  # Backend validates based on existing key type
