from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from onyx.configs.app_configs import OPENSEARCH_ADMIN_PASSWORD
from onyx.configs.app_configs import OPENSEARCH_ADMIN_USERNAME
from onyx.configs.app_configs import OPENSEARCH_HOST
from onyx.configs.app_configs import OPENSEARCH_REST_API_PORT
from onyx.configs.app_configs import OPENSEARCH_USE_SSL
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings


class vespa_fixture:
    """Test fixture for inspecting the document index.

    Kept named ``vespa_fixture`` for backwards compatibility with the many
    existing integration tests that take it as a parameter. Internally it is now
    backed by OpenSearch, and it reshapes hits into the dict-of-keys layout that
    the legacy Vespa assertions expect (``access_control_list`` and
    ``document_sets`` as dicts; ``image_file_name`` mirrored from OpenSearch's
    ``image_file_id``; the ``public`` boolean folded back into the ACL as the
    ``"PUBLIC"`` entry).

    The current index name is resolved lazily on each call rather than at
    construction time. The docprocessing worker performs an in-flight swap from
    ``danswer_chunk`` to ``danswer_chunk_<model>`` the first time it indexes
    after a Postgres reset; resolving the name eagerly in the fixture would
    cache the pre-swap value and query a non-existent index.
    """

    def __init__(self, index_name: str | None = None) -> None:
        # index_name is accepted for backwards compat with the prior Vespa
        # fixture signature but ignored — see class docstring.
        del index_name
        self._client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_REST_API_PORT}],
            http_auth=(OPENSEARCH_ADMIN_USERNAME, OPENSEARCH_ADMIN_PASSWORD),
            use_ssl=OPENSEARCH_USE_SSL,
            verify_certs=False,
            ssl_show_warn=False,
        )

    @property
    def index_name(self) -> str:
        with get_session_with_current_tenant() as db_session:
            return get_current_search_settings(db_session).index_name

    def get_documents_by_id(
        self, document_ids: list[str], wanted_doc_count: int = 1_000
    ) -> dict[str, Any]:
        index_name = self.index_name
        # Refresh first so chunks indexed just before the call are visible.
        try:
            self._client.indices.refresh(index=index_name)
        except NotFoundError:
            return {"documents": []}

        body: dict[str, Any] = {
            "size": wanted_doc_count,
            "query": {"terms": {"document_id": document_ids}},
        }
        try:
            result = self._client.search(index=index_name, body=body)
        except NotFoundError:
            return {"documents": []}

        hits = result.get("hits", {}).get("hits", [])
        documents: list[dict[str, Any]] = []
        for hit in hits:
            source: dict[str, Any] = dict(hit.get("_source", {}))

            acl_entries: set[str] = set(source.get("access_control_list") or [])
            if source.get("public"):
                acl_entries.add("PUBLIC")
            source["access_control_list"] = {entry: 1 for entry in acl_entries}

            source["document_sets"] = {
                entry: 1 for entry in (source.get("document_sets") or [])
            }

            if "image_file_id" in source:
                source["image_file_name"] = source["image_file_id"]

            documents.append({"fields": source})
        return {"documents": documents}
