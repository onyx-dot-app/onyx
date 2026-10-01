"""Credential families: one account shared by related sources.

A family credential is stored in the family's shape (a ``FamilyCredential``
model) plus a ``CREDENTIAL_FAMILY_KEY`` marker. Each member source has a
``FamilyCredentialCodec`` that converts between the family shape and the
source's own keys, so connectors keep reading their own keys. Credentials
created before their source joined a family keep their source's shape and stay
usable by that source only.
"""

from typing import Any

import pydantic

from onyx.configs.constants import DocumentSource
from onyx.connectors.atlassian_credential import (
    ConfluenceCredentialCodec,
    JiraCredentialCodec,
)
from onyx.connectors.credential_family_base import (
    CREDENTIAL_FAMILY_KEY,
    CredentialFamily,
    FamilyCredential,
    FamilyCredentialCodec,
)
from onyx.connectors.google_credential import GoogleCredentialCodec
from onyx.connectors.microsoft_credential import (
    ONEDRIVE_KEY_PREFIX,
    OUTLOOK_KEY_PREFIX,
    SHAREPOINT_KEY_PREFIX,
    TEAMS_KEY_PREFIX,
    MicrosoftCredentialCodec,
)

FAMILY_CREDENTIAL_CODECS: dict[DocumentSource, FamilyCredentialCodec[Any]] = {
    DocumentSource.CONFLUENCE: ConfluenceCredentialCodec(),
    DocumentSource.JIRA: JiraCredentialCodec(),
    DocumentSource.GMAIL: GoogleCredentialCodec(),
    DocumentSource.GOOGLE_DRIVE: GoogleCredentialCodec(),
    DocumentSource.SHAREPOINT: MicrosoftCredentialCodec(SHAREPOINT_KEY_PREFIX),
    DocumentSource.ONEDRIVE: MicrosoftCredentialCodec(ONEDRIVE_KEY_PREFIX),
    DocumentSource.OUTLOOK: MicrosoftCredentialCodec(OUTLOOK_KEY_PREFIX),
    DocumentSource.TEAMS: MicrosoftCredentialCodec(TEAMS_KEY_PREFIX),
}


def credential_family_for_source(source: DocumentSource) -> CredentialFamily | None:
    codec = FAMILY_CREDENTIAL_CODECS.get(source)
    return codec.family if codec else None


def family_sources(family: CredentialFamily) -> list[DocumentSource]:
    return [
        source
        for source, codec in FAMILY_CREDENTIAL_CODECS.items()
        if codec.family == family
    ]


def stored_credential_family(stored_json: dict[str, Any]) -> CredentialFamily | None:
    marker = stored_json.get(CREDENTIAL_FAMILY_KEY)
    return CredentialFamily(marker) if marker is not None else None


def _family_credential(
    codec: FamilyCredentialCodec[Any], stored_json: dict[str, Any]
) -> FamilyCredential:
    family_json = {k: v for k, v in stored_json.items() if k != CREDENTIAL_FAMILY_KEY}
    return codec.family_model.model_validate(family_json)


def is_credential_usable_for_source(
    credential_source: DocumentSource | None,
    stored_json: dict[str, Any],
    target_source: DocumentSource,
) -> bool:
    if credential_source == target_source:
        return True
    family = stored_credential_family(stored_json)
    codec = FAMILY_CREDENTIAL_CODECS.get(target_source)
    if family is None or codec is None or codec.family != family:
        return False
    try:
        return codec.accepts(_family_credential(codec, stored_json))
    except pydantic.ValidationError:
        return False


def to_source_credential_json(
    source: DocumentSource, stored_json: dict[str, Any]
) -> dict[str, Any]:
    """The credential JSON in ``source``'s own keys, for the connector (or a
    response) of that source."""
    family = stored_credential_family(stored_json)
    if family is None:
        return stored_json
    codec = FAMILY_CREDENTIAL_CODECS.get(source)
    if codec is None or codec.family != family:
        raise ValueError(
            f"A {family.value} credential cannot be used by the {source.value} source."
        )
    family_credential = _family_credential(codec, stored_json)
    if not codec.accepts(family_credential):
        raise ValueError(
            f"This {family.value} credential cannot be used by the {source.value} source."
        )
    return codec.from_family(family_credential)


def to_stored_credential_json(
    source: DocumentSource,
    source_json: dict[str, Any],
    current_stored_json: dict[str, Any] | None,
) -> dict[str, Any]:
    """The JSON to store when ``source`` writes ``source_json``.

    ``current_stored_json`` is ``None`` for a new credential. A new credential of
    a family source is stored in the family's shape. An existing credential keeps
    the shape it has.
    """
    if CREDENTIAL_FAMILY_KEY in source_json:
        raise ValueError(f"'{CREDENTIAL_FAMILY_KEY}' is a reserved credential key.")
    codec = FAMILY_CREDENTIAL_CODECS.get(source)
    current_family = (
        stored_credential_family(current_stored_json)
        if current_stored_json is not None
        else None
    )
    if current_family is not None:
        if (
            codec is None
            or codec.family != current_family
            or current_stored_json is None
            or not is_credential_usable_for_source(None, current_stored_json, source)
        ):
            raise ValueError(
                f"The {source.value} source cannot write this "
                f"{current_family.value} credential."
            )
    elif codec is None or current_stored_json is not None:
        return source_json
    try:
        family_credential = codec.to_family(source_json)
    except (KeyError, pydantic.ValidationError) as e:
        # A KeyError names the missing key only, and family models hide input
        # values, so no secret reaches the message.
        raise ValueError(f"This is not a valid {source.value} credential: {e}") from e
    _reject_dropped_keys(source, source_json, codec.from_family(family_credential))
    return {
        **family_credential.model_dump(mode="json"),
        CREDENTIAL_FAMILY_KEY: codec.family.value,
    }


def _reject_dropped_keys(
    source: DocumentSource,
    source_json: dict[str, Any],
    round_tripped_json: dict[str, Any],
) -> None:
    """Raises ``ValueError`` if a key with a value does not survive the round
    trip through the family shape, e.g. another source's keys sent to this
    source. Storing it would silently drop the value. Names keys only, never
    values."""
    dropped = sorted(
        key
        for key, value in source_json.items()
        if value not in (None, "") and key not in round_tripped_json
    )
    if dropped:
        raise ValueError(f"Not {source.value} credential keys: {', '.join(dropped)}.")
