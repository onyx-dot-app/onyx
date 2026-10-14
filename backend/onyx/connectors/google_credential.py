"""The Google credential family: Gmail and Google Drive share one account.

Both sources already use the same credential keys, so the family shape is those
keys. Scopes still differ: a token consented for one source may lack the other's
scopes, which capability checks report.
"""

from typing import Any

from pydantic import ConfigDict

from onyx.connectors.credential_family_base import (
    CredentialFamily,
    FamilyCredential,
    FamilyCredentialCodec,
)
from onyx.connectors.google_utils.shared_constants import (
    GoogleOAuthAuthenticationMethod,
)


class GoogleCredential(FamilyCredential):
    # The API has always accepted any keys for these sources, so keep them.
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)

    # JSON strings, as the Google auth helpers read them.
    google_tokens: str | None = None
    google_service_account_key: str | None = None
    # The OAuth app credential, {"web": {...}}, or that dict as a JSON string
    # (the legacy form, which _load_google_json still reads).
    google_app_credential: dict[str, Any] | str | None = None
    google_primary_admin: str | None = None
    authentication_method: GoogleOAuthAuthenticationMethod | None = None


class GoogleCredentialCodec(FamilyCredentialCodec[GoogleCredential]):
    family = CredentialFamily.GOOGLE
    family_model = GoogleCredential

    def to_family(self, source_json: dict[str, Any]) -> GoogleCredential:
        return GoogleCredential.model_validate(source_json)

    def from_family(self, family_credential: GoogleCredential) -> dict[str, Any]:
        # The Google auth helpers branch on which keys are present.
        return family_credential.model_dump(mode="json", exclude_none=True)
