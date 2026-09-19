from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from onyx.kg.utils.extraction_utils import (
    KG_DOCUMENT_PROCESSING_TRACE_NAME,
    kg_deep_extraction,
)
from onyx.tracing.framework.traces import TraceContentMode

_EXTRACTION_UTILS = "onyx.kg.utils.extraction_utils"


def test_kg_deep_extraction_owns_document_trace() -> None:
    expected_result = MagicMock()
    with (
        patch(
            f"{_EXTRACTION_UTILS}._kg_deep_extraction",
            return_value=expected_result,
        ),
        patch(
            f"{_EXTRACTION_UTILS}.ensure_trace", return_value=nullcontext()
        ) as ensure,
    ):
        result = kg_deep_extraction(
            document_id="document",
            metadata=MagicMock(),
            implied_extraction=MagicMock(),
            tenant_id="tenant",
            index_name="index",
            kg_config_settings=MagicMock(),
        )

    assert result is expected_result
    ensure.assert_called_once_with(
        KG_DOCUMENT_PROCESSING_TRACE_NAME,
        content_mode=TraceContentMode.METADATA_ONLY,
    )
