from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection


class BasicSearchProcessedStreamResults(BaseModel):
    ai_message_chunk: AIMessageChunk = AIMessageChunk(content="")
    full_answer: str | None = None
    cited_references: list[InferenceSection] = []
    retrieved_documents: list[LlmDoc] = []
