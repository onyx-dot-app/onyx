"""The Microsoft credential family: one Entra app registration shared by
SharePoint, OneDrive, Outlook, and Teams.

Each source prefixes the same credential keys (``sp_client_id``,
``teams_client_id``, ...), so a codec maps its prefix to the family fields. The
app still needs each source's Graph permissions, which capability checks report.
"""

from typing import Any

from pydantic import ConfigDict

from onyx.connectors.credential_family_base import (
    CredentialFamily,
    FamilyCredential,
    FamilyCredentialCodec,
)

_AUTHENTICATION_METHOD_KEY = "authentication_method"
_ONEDRIVE_AUTHENTICATION_METHOD_KEY = "onedrive_authentication_method"
_AUTHENTICATION_METHOD_KEYS = (
    _AUTHENTICATION_METHOD_KEY,
    _ONEDRIVE_AUTHENTICATION_METHOD_KEY,
)


class MicrosoftCredential(FamilyCredential):
    # The API has always accepted any keys for these sources, so keep them.
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)

    client_id: str
    directory_id: str
    client_secret: str | None = None
    # Base64 PFX data and its password, for certificate authentication.
    private_key: str | None = None
    certificate_password: str | None = None
    # "client_secret" or "certificate"; the connectors parse and validate it.
    authentication_method: str | None = None


# The fields every source stores under its own prefix.
_PREFIXED_FIELDS = (
    "client_id",
    "directory_id",
    "client_secret",
    "private_key",
    "certificate_password",
)
SHAREPOINT_KEY_PREFIX = "sp"
ONEDRIVE_KEY_PREFIX = "onedrive"
OUTLOOK_KEY_PREFIX = "outlook"
TEAMS_KEY_PREFIX = "teams"
_KEY_PREFIXES = (
    SHAREPOINT_KEY_PREFIX,
    ONEDRIVE_KEY_PREFIX,
    OUTLOOK_KEY_PREFIX,
    TEAMS_KEY_PREFIX,
)


class MicrosoftCredentialCodec(FamilyCredentialCodec[MicrosoftCredential]):
    family = CredentialFamily.MICROSOFT
    family_model = MicrosoftCredential

    def __init__(self, key_prefix: str) -> None:
        self._key_prefix = key_prefix

    def to_family(self, source_json: dict[str, Any]) -> MicrosoftCredential:
        # Another source's key would override the mapped value when the
        # credential is used by that source.
        foreign_keys = sorted(
            key
            for key in source_json
            for prefix in _KEY_PREFIXES
            if prefix != self._key_prefix
            and key in {f"{prefix}_{field}" for field in _PREFIXED_FIELDS}
        )
        if foreign_keys:
            raise ValueError(
                f"Keys of another Microsoft source: {', '.join(foreign_keys)}."
            )
        prefixed_keys = {f"{self._key_prefix}_{field}" for field in _PREFIXED_FIELDS}
        # OneDrive also reads a prefixed authentication method.
        authentication_method = source_json.get(
            _AUTHENTICATION_METHOD_KEY,
            source_json.get(_ONEDRIVE_AUTHENTICATION_METHOD_KEY),
        )
        other_keys = {
            key: value
            for key, value in source_json.items()
            if key not in prefixed_keys and key not in _AUTHENTICATION_METHOD_KEYS
        }
        return MicrosoftCredential.model_validate(
            {
                **other_keys,
                **{
                    field: source_json[f"{self._key_prefix}_{field}"]
                    for field in _PREFIXED_FIELDS
                    if f"{self._key_prefix}_{field}" in source_json
                },
                "authentication_method": authentication_method,
            }
        )

    def from_family(self, family_credential: MicrosoftCredential) -> dict[str, Any]:
        # Absent stays absent: the connectors read these keys with .get().
        values = family_credential.model_dump(exclude_none=True)
        authentication_method = values.pop("authentication_method", None)
        source_json = {
            f"{self._key_prefix}_{key}" if key in _PREFIXED_FIELDS else key: value
            for key, value in values.items()
        }
        if authentication_method is not None:
            source_json[_AUTHENTICATION_METHOD_KEY] = authentication_method
            # OneDrive also has its own key for it; keep both so its round
            # trip loses nothing.
            if self._key_prefix == ONEDRIVE_KEY_PREFIX:
                source_json[_ONEDRIVE_AUTHENTICATION_METHOD_KEY] = authentication_method
        return source_json
