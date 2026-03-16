from typing import Any

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


class DocumentIngestionSpec(HookPointSpec):
    """Hook point that runs during document ingestion.

    # TODO(@Bo-Onyx): define call site, input/output schema, and timeout budget.
    """

    hook_point = HookPoint.DOCUMENT_INGESTION
    display_name = "Document Ingestion"
    description = "Runs during document ingestion. Allows filtering or transforming documents before indexing."
    default_timeout_seconds = 30.0
    fail_hard_description = "The document will not be indexed."
    default_fail_strategy = HookFailStrategy.HARD

    @property
    def input_schema(self) -> dict[str, Any]:
        # TODO(@Bo-Onyx): define input schema
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        # TODO(@Bo-Onyx): define output schema
        return {"type": "object", "properties": {}}
