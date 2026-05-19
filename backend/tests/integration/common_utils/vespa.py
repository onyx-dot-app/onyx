from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from onyx.configs.app_configs import OPENSEARCH_ADMIN_PASSWORD
from onyx.configs.app_configs import OPENSEARCH_ADMIN_USERNAME
from onyx.configs.app_configs import OPENSEARCH_HOST
from onyx.configs.app_configs import OPENSEARCH_REST_API_PORT
from onyx.configs.app_configs import OPENSEARCH_USE_SSL


class vespa_fixture:
    """Test fixture for inspecting the document index.

    Kept named ``vespa_fixture`` for backwards compatibility with the many
    existing integration tests that take it as a parameter. Internally it is
    now backed by OpenSearch, and it reshapes hits into the dict-of-keys
    layout that the legacy Vespa assertions expect (``access_control_list``
    and ``document_sets`` as dicts; ``image_file_name`` mirrored from
    OpenSearch's ``image_file_id``; the ``public`` boolean folded back into
    the ACL as the ``"PUBLIC"`` entry).
    """

    def __init__(self, index_name: str) -> None:
        self.index_name = index_name
        self._client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_REST_API_PORT}],
            http_auth=(OPENSEARCH_ADMIN_USERNAME, OPENSEARCH_ADMIN_PASSWORD),
            use_ssl=OPENSEARCH_USE_SSL,
            verify_certs=False,
            ssl_show_warn=False,
        )

    def get_documents_by_id(
        self, document_ids: list[str], wanted_doc_count: int = 1_000
    ) -> dict[str, Any]:
        # Refresh first so chunks indexed just before the call are visible.
        try:
            self._client.indices.refresh(index=self.index_name)
        except NotFoundError:
            return {"documents": []}

        body: dict[str, Any] = {
            "size": wanted_doc_count,
            "query": {"terms": {"document_id": document_ids}},
        }
        try:
            result = self._client.search(index=self.index_name, body=body)
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
