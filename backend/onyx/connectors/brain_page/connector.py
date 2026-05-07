"""Brain Page connector — passive registration only.

Brain pages are produced by the operator-brain layer (per-operator markdown
corpus of compiled-truth + timeline pages on people, companies, projects,
meetings, etc.) and pushed into Onyx via the Ingestion API
(``POST /onyx-api/ingestion``) — there is no remote source to poll.

This connector exists solely so ``DocumentSource.BRAIN_PAGE`` is registered
in the connector factory and can be associated with a credential + CC-pair
via the standard admin endpoints. Once associated, brain_page appears as
a real source in the chat UI's source-filter list (the filter only shows
sources backed by a registered connector class), and per-operator brain
pages become searchable from the chat.

Mirrors the role ``IngestionAPI`` plays for the legacy ingestion path:
the factory's ``validate_ccpair_for_user`` short-circuits validation for
both sources (``factory.py``), so this class is never instantiated at
runtime — it only needs to exist as a target for the registry lookup.
"""

from typing import Any

from onyx.connectors.interfaces import BaseConnector


class BrainPageConnector(BaseConnector):
    """No-op connector for ingestion-API-only brain pages.

    The ingestion path is the operator-brain layer's
    ``OnyxClient.ingest_document`` (POST /onyx-api/ingestion). There is no
    polling, no fetching, no remote state. This class is a registration
    placeholder; ``factory.validate_ccpair_for_user`` skips instantiation
    for ``DocumentSource.BRAIN_PAGE`` the same way it skips
    ``DocumentSource.INGESTION_API``.
    """

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # No external credentials — brain pages are pushed via the
        # Ingestion API using the operator's API key.
        return None

    def validate_connector_settings(self) -> None:
        # No remote source to validate against.
        return None
