# Legacy KG-Vespa Code

This directory contains the original Vespa-backed Knowledge Graph (KG) modules,
preserved verbatim from before the Vespa removal in May 2026.

KG is currently **disabled** (`KG_ENABLED=False`). The code here is NOT imported
by any active code path — its `from onyx.document_index.vespa...` imports will
fail at import time because the `document_index/vespa/` package was deleted.

## Files

- `vespa_interactions.py` — chunk read path (`get_document_vespa_contents`),
  originally at `backend/onyx/kg/vespa/vespa_interactions.py`.
- `reset_vespa.py` — KG field reset path (`reset_vespa_kg_index`,
  `_reset_vespa_for_doc`), originally at `backend/onyx/kg/resets/reset_vespa.py`.
- `kg_interactions.py` — chunk write path (`update_kg_chunks_vespa_info`,
  `get_kg_vespa_info_update_requests_for_document`), originally at
  `backend/onyx/document_index/vespa/kg_interactions.py`.

## Active call sites that were rewired during quarantine

- `kg/resets/reset_source.py` (reset path)
- `kg/utils/extraction_utils.py` (extraction read path)
- `kg/clustering/clustering.py` (clustering write path)

## To re-enable KG on OpenSearch

1. Port `vespa_interactions.py` to a `kg/opensearch/opensearch_interactions.py`
   that uses `OpenSearchDocumentIndex` instead of `VespaDocumentIndex`.
2. Add `kg_entities`, `kg_relationships`, and `kg_terms` fields to
   `backend/onyx/document_index/opensearch/schema.py`.
3. Port `reset_vespa.py` to `kg/resets/reset_opensearch.py`.
4. Port the two helpers in `kg_interactions.py` to use OpenSearch update calls.
5. Rewire the three call sites listed above.
