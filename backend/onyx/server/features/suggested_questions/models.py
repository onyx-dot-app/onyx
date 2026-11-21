from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.server.features.suggested_questions.config import (
    SQ_QUESTION_ID_MAX_BYTES,
    SQ_QUESTION_MAX_AGE_DAYS,
)


class QuestionKind(StrEnum):
    # A connector document: a row in the `document` table.
    DOCUMENT = "document"
    # A chat or project upload: a row in the `user_file` table.
    USER_FILE = "user_file"


class UseCase(StrEnum):
    HR = "hr"
    ENGINEERING = "engineering"
    SUPPORT = "support"
    SALES = "sales"
    OTHER = "other"


class RefreshReason(StrEnum):
    """Why a pool run was requested, for the logs."""

    # The company never had a pool run and its first documents arrived.
    FIRST_RUN = "first_run"
    # A person who opened the chat is short of shared questions.
    PERSON_SHORT = "person_short"


class RunDecision(BaseModel):
    """Whether a pool run should call the models, and why."""

    run: bool
    reason: str


class CandidateDocument(BaseModel):
    """A document a run may write a question about."""

    document_id: str
    kind: QuestionKind
    # The people whose private bucket chose it. Empty for a shared document.
    # A run puts the document's question on each of their private shelves.
    owner_ids: list[UUID] = Field(default_factory=list)


class WrittenQuestion(BaseModel):
    """One question as the writing call returns it, before any check."""

    # 1-based number of the passage it was written from.
    passage: int
    question: str
    # None fits every use case: "any", a missing value, or a value the model
    # made up. A bad value never fails the whole output.
    best_for: UseCase | None = None

    @field_validator("best_for", mode="before")
    @classmethod
    def unknown_use_case_fits_everyone(cls, value: object) -> UseCase | None:
        try:
            use_case = UseCase(str(value).strip().lower())
        except ValueError:
            return None
        return None if use_case == UseCase.OTHER else use_case


class WritingOutput(BaseModel):
    """The JSON object the writing call returns."""

    questions: list[WrittenQuestion]


class DraftQuestion(BaseModel):
    """A question the writing call wrote, before the search test."""

    text: str
    # The chunk it was written from; its document is the one the search test
    # must find.
    chunk: InferenceChunk
    best_for: UseCase | None


class PoolQuestion(BaseModel):
    """A question that passed the search test. It stores the document it came
    from, never who may see it: access is checked when a person opens the chat."""

    id: str
    text: str
    kind: QuestionKind
    document_id: str
    # DocumentSource.USER_FILE for uploads.
    source_type: DocumentSource
    # Position of the source document in the search test, 0 is first.
    search_position: int = Field(ge=0)
    # The use case the question fits; None fits every use case.
    best_for: UseCase | None
    created_at: datetime

    def is_fresh(self, now: datetime) -> bool:
        """Young enough to show. A document whose question expired may get a
        new one."""
        return now - self.created_at < timedelta(days=SQ_QUESTION_MAX_AGE_DAYS)


class QuestionPool(BaseModel):
    """One per company, in the KV store. Its questions are the shared shelf:
    questions about documents everyone in the company can see."""

    version: int = 1
    # Start times of recent pool runs, oldest first, for the rate limits.
    runs: list[datetime] = Field(default_factory=list)
    # Indexed documents counted at the start of the last run.
    docs_at_last_run: int = 0
    questions: list[PoolQuestion] = Field(default_factory=list)

    @property
    def document_ids(self) -> set[str]:
        return {question.document_id for question in self.questions}

    def last_run_at(self) -> datetime | None:
        return self.runs[-1] if self.runs else None

    def runs_since(self, since: datetime) -> int:
        return sum(1 for run in self.runs if run >= since)

    def record_run(
        self, started_at: datetime, docs_at_last_run: int, window: timedelta
    ) -> "QuestionPool":
        """Return a copy with the run recorded and runs older than the
        rate-limit window dropped. The caller saves it."""
        runs = [run for run in self.runs if run >= started_at - window]
        return self.model_copy(
            update={
                "runs": [*runs, started_at],
                "docs_at_last_run": docs_at_last_run,
            }
        )


class UserRecord(BaseModel):
    """One per person, in the KV store."""

    # Ids of questions the person clicked, oldest first.
    used: list[str] = Field(default_factory=list)
    # The last time the person opened the chat, with any agent.
    last_seen_at: datetime | None = None
    # Start times of recent top-up runs for this person, oldest first.
    topups: list[datetime] = Field(default_factory=list)
    # The private shelf: questions about documents granted to this person.
    questions: list[PoolQuestion] = Field(default_factory=list)
    # When a chat open last asked for a run for this person.
    requested_at: datetime | None = None

    def record_topup(self, started_at: datetime, window: timedelta) -> "UserRecord":
        """Return a copy with the top-up recorded and top-ups older than the
        rate-limit window dropped. The caller saves it."""
        topups = [topup for topup in self.topups if topup >= started_at - window]
        return self.model_copy(update={"topups": [*topups, started_at]})


class SuggestionsState(StrEnum):
    READY = "ready"
    # A run for this person was asked for moments ago: check again soon.
    PREPARING = "preparing"
    # The person cannot open any indexed document yet.
    NO_DOCUMENTS = "no_documents"


class ShownQuestion(BaseModel):
    id: str
    # Named like StarterMessage.message, so the chat page renders it the same.
    message: str
    # From the person's private shelf, for analytics; it looks the same.
    private: bool


class PersonSuggestions(BaseModel):
    questions: list[ShownQuestion]
    state: SuggestionsState


class MarkUsedRequest(BaseModel):
    """A click on a suggested question. The id comes from the browser, so its
    size is checked before it is stored in the person's record."""

    question_id: str

    @field_validator("question_id")
    @classmethod
    def fits_in_the_record(cls, value: str) -> str:
        if len(value.encode()) > SQ_QUESTION_ID_MAX_BYTES:
            raise ValueError(f"question_id is over {SQ_QUESTION_ID_MAX_BYTES} bytes")
        return value
