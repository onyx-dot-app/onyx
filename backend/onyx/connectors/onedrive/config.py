from typing import Annotated

from pydantic import field_validator

from onyx.connectors.connector_config import ConnectorConfig, field_format_error
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeInclude,
)
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding
from onyx.connectors.onedrive.scope import normalized_user_email

USER_EMAIL_FORMAT_ERROR = "Enter email addresses, e.g. jane@acme.com."


class OneDriveConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    users: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    excluded_paths: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    # Changes the access list of indexed documents.
    treat_organization_link_as_public: Annotated[
        bool, FieldPolicy(FieldClass.BEHAVIOR)
    ] = False

    # Blank entries are skipped. A list of only blanks fails the "Find
    # selected users" check, as the design's row says.
    @field_validator("users")
    @classmethod
    def _users_are_emails(cls, value: list[str] | None) -> list[str] | None:
        if any(
            entry.strip() and normalized_user_email(entry) is None
            for entry in value or []
        ):
            raise field_format_error(USER_EMAIL_FORMAT_ERROR)
        return value
