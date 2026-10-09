"""The credential named by a connector form's request: a saved one
(``credential_id``), or a new account the form typed (``credential_json``).

A new account is saved as a draft (``Credential.is_draft``), which only its
owner can see, and the response returns its id. Later requests name the draft
by that id, and send ``credential_json`` again only when the values changed.
Creating the connector promotes the draft to a saved credential."""

from typing import Any

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.credentials import (
    create_draft_credential,
    credential_usable_for_source,
    fetch_credential_by_id_for_user,
    update_draft_credential_json,
)
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.models import NAMES_A_CREDENTIAL
from onyx.utils.encryption import reject_masked_credentials


def resolve_form_credential(
    *,
    credential_id: int | None,
    credential_json: dict[str, Any] | None,
    source: DocumentSource,
    user: User,
    db_session: Session,
) -> Credential:
    """The request's credential, for a ``source`` connector form:

    - ``credential_json`` alone saves a new draft;
    - both update the user's draft ``credential_id``; when that draft is gone
      (deleted as stale, or already promoted), a new draft is saved instead;
    - ``credential_id`` alone is a saved credential the user can see, or the
      user's own draft.

    Raises:
        OnyxError: CREDENTIAL_NOT_FOUND when ``credential_id`` alone names
            nothing the user can see; INVALID_INPUT for values a save rejects,
            values sent for a saved credential, or a credential ``source``
            cannot use.
    """
    if credential_json is not None:
        try:
            reject_masked_credentials(credential_json)
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    credential = (
        fetch_credential_by_id_for_user(
            credential_id, user, db_session, include_own_drafts=True
        )
        if credential_id is not None
        else None
    )
    if credential_id is not None and credential is None and credential_json is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or is not accessible.",
        )
    if credential is not None and credential_json is not None:
        if not credential.is_draft:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Credential {credential.id} is saved; edit it from its "
                "connector, not with a new account's values.",
            )
        if credential.source != source:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Credential {credential.id} is a {credential.source.value} "
                f"draft, not {source.value}.",
            )

    try:
        if credential_json is not None:
            if credential is None:
                # A new draft, or a lost draft made again.
                return create_draft_credential(
                    source, credential_json, user, db_session
                )
            update_draft_credential_json(
                credential, source, credential_json, db_session
            )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    if credential is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, NAMES_A_CREDENTIAL)

    if not credential_usable_for_source(credential, source):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Credential {credential.id} cannot be used by a {source.value} connector.",
        )
    return credential
