from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk


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


class CandidateDocument(BaseModel):
    """A document a run may write a question about."""

    document_id: str
    kind: QuestionKind


class TriagedChunk(BaseModel):
    """A chunk with the decision model's answers about it."""

    chunk: InferenceChunk
    # Expected usable score, 0 (useless) to 3 (excellent).
    usable: float
    # Probability that it reveals private information.
    sensitive: float
    # None when the model refused or the rules-only fallback scored it.
    topic: UseCase | None
    # Probability that it states a number, date, name or short list.
    has_fact: float


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


class QuestionPool(BaseModel):
    """One per company, in the KV store."""

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

    def record_topup(self, started_at: datetime, window: timedelta) -> "UserRecord":
        """Return a copy with the top-up recorded and top-ups older than the
        rate-limit window dropped. The caller saves it."""
        topups = [topup for topup in self.topups if topup >= started_at - window]
        return self.model_copy(update={"topups": [*topups, started_at]})
