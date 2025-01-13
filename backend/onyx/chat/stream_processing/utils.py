from collections.abc import Sequence

from pydantic import BaseModel

from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceChunk


class DocumentIdOrderMapping(BaseModel):
    order_mapping: dict[str, int]


def map_document_id_order(
    chunks: Sequence[InferenceChunk | LlmDoc], one_indexed: bool = True
) -> DocumentIdOrderMapping:
    order_mapping = {}
    current = 1 if one_indexed else 0
    for chunk in chunks:
        if chunk.document_id not in order_mapping:
            order_mapping[chunk.document_id] = current
            current += 1

    return DocumentIdOrderMapping(order_mapping=order_mapping)
