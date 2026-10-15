from typing import Any

from pydantic import BaseModel
from pydantic import Field


class CanvasQuizAnswer(BaseModel):
    id: int | None = None
    text: str | None = None
    html: str | None = None
    weight: float | None = None
    comments: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "CanvasQuizAnswer":
        return cls(
            id=payload.get("id"),
            text=payload.get("text"),
            html=payload.get("html"),
            weight=payload.get("weight"),
            comments=payload.get("comments"),
        )


class CanvasQuizQuestion(BaseModel):
    id: int
    position: int | None = None
    question_name: str | None = None
    question_type: str | None = None
    question_text: str | None = None
    answers: list[CanvasQuizAnswer] = Field(default_factory=list)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "CanvasQuizQuestion":
        return cls(
            id=payload["id"],
            position=payload.get("position"),
            question_name=payload.get("question_name"),
            question_type=payload.get("question_type"),
            question_text=payload.get("question_text"),
            answers=[
                CanvasQuizAnswer.from_api(answer)
                for answer in (payload.get("answers") or [])
                if isinstance(answer, dict)
            ],
        )


class CanvasNewQuiz(BaseModel):
    id: int
    title: str
    instructions: str | None = None
    published: bool | None = None
    unlock_at: str | None = None
    lock_at: str | None = None
    course_id: int

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasNewQuiz":
        return cls(
            id=int(payload["id"]),
            title=payload.get("title", ""),
            instructions=payload.get("instructions"),
            published=payload.get("published"),
            unlock_at=payload.get("unlock_at"),
            lock_at=payload.get("lock_at"),
            course_id=course_id,
        )


class CanvasNewQuizItem(BaseModel):
    id: str
    position: int | None = None
    entry_type: str
    entry: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "CanvasNewQuizItem":
        entry = payload.get("entry")
        return cls(
            id=str(payload["id"]),
            position=payload.get("position"),
            entry_type=payload.get("entry_type", ""),
            entry=entry if isinstance(entry, dict) else {},
        )
