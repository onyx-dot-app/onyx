"""A new credential named in a request, which is not saved until its connector
is created: values typed into the form (``credential_json``), or an OAuth
sign-in's tokens that the server sealed (``draft_credential``)."""

from typing import Any

from onyx.auth.sealed import (
    DraftCredential,
    seal_draft_credential,
    unseal_draft_credential,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credential_families import (
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.encryption import reject_masked_credentials

EXACTLY_ONE_CREDENTIAL = (
    "Give exactly one of credential_id, credential_json and draft_credential."
)


def names_exactly_one_credential(
    credential_id: int | None,
    credential_json: dict[str, Any] | None,
    draft_credential: str | None,
) -> bool:
    return (
        sum(
            value is not None
            for value in (credential_id, credential_json, draft_credential)
        )
        == 1
    )


def resolve_draft_credential(
    *,
    credential_json: dict[str, Any] | None,
    draft_credential: str | None,
    source: DocumentSource,
    user: User,
) -> tuple[DraftCredential, str] | None:
    """The request's new credential, and its sealed form for a task message;
    None when the request names a saved credential instead.

    Typed values are checked as a save would check them. A sealed draft must
    belong to ``user`` and to ``source``.
    """
    if draft_credential is not None:
        draft = unseal_draft_credential(draft_credential, user_id=user.id)
        if draft.source != source:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"This draft credential is for {draft.source.value}, not "
                f"{source.value}.",
            )
        return draft, draft_credential
    if credential_json is not None:
        try:
            reject_masked_credentials(credential_json)
            # Validates the values as a save would, without saving them, and
            # gives them the shape the connector reads after a save.
            source_json = to_source_credential_json(
                source, to_stored_credential_json(source, credential_json, None)
            )
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
        sealed = seal_draft_credential(source_json, user_id=user.id, source=source)
        return unseal_draft_credential(sealed, user_id=user.id), sealed
    return None
