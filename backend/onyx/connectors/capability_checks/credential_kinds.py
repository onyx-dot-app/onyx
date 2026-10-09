"""Credential kinds: the forms of one source's credential that need different
checks, such as a Google service account and a Google OAuth token.

A source that tells kinds apart registers a resolver here. It reads the kind
from the keys of the credential JSON (in the source's own keys), never from the
secret values. Checks declare the kinds they apply to with
``CapabilityCheck(credential_kinds=...)``; a check of another kind is not
applicable.
"""

from collections.abc import Callable
from typing import Any

from onyx.configs.constants import DocumentSource

CredentialKindResolver = Callable[[dict[str, Any]], str | None]

# Per-connector work registers resolvers here.
_CREDENTIAL_KIND_RESOLVERS: dict[DocumentSource, CredentialKindResolver] = {}


def resolve_credential_kind(
    source: DocumentSource, credential_json: dict[str, Any]
) -> str | None:
    """The kind of a credential of ``source``, or None when the source has no
    kinds or the credential matches none."""
    resolver = _CREDENTIAL_KIND_RESOLVERS.get(source)
    return resolver(credential_json) if resolver is not None else None
