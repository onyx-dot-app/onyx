from pydantic import BaseModel


class TargetDocument(BaseModel):
    """Schema for documents in target_docs.jsonl."""

    document_id: str  # Hash ID
    semantic_identifier: str | None = None
    title: str | None
    content: str
    source_type: str | None = None
    filename: str | None = None  # Human-readable filename
    url: str | None = None
    metadata: dict | None = None


class TargetQuestionDocSource(BaseModel):
    """Document source reference in question metadata."""

    # For file-based sources
    source: str | None = None
    source_hash: str | None = None

    # For Slack messages
    channel: str | None = None
    message_count: int | None = None
    source_type: str | None = None
    thread_ts: str | None = None
    workspace: str | None = None


class TargetQuestionMetadata(BaseModel):
    """Metadata for target questions."""

    question_type: str
    doc_source: list[TargetQuestionDocSource]


class TargetQuestion(BaseModel):
    """Schema for questions in target_questions.jsonl."""

    uid: str
    question: str
    ground_truth_answers: list[str]
    ground_truth_context: list[str]
    metadata: TargetQuestionMetadata
