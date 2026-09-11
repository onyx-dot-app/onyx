"""Small, independent checkpoint for the frequent model streaming callbacks."""

from typing import Any

from pydantic import BaseModel

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.chat.pi.host_state import CitationSnapshot, PresentationSnapshot
from onyx.chat.pi.presentation import ChatPresentation


class ProjectionSnapshot(BaseModel):
    presentation: PresentationSnapshot
    citations: CitationSnapshot
    answer: str | None
    reasoning: str | None
    processing_seconds: float | None
    emitted_citations: set[int]
    request_params: dict[str, Any] | None

    @classmethod
    def capture(cls, presenter: ChatPresentation) -> "ProjectionSnapshot":
        return cls(
            presentation=presenter.snapshot(),
            citations=CitationSnapshot.capture(presenter.citations),
            answer=presenter.state.get_answer_tokens(),
            reasoning=presenter.state.get_reasoning_tokens(),
            processing_seconds=presenter.state.get_pre_answer_processing_time(),
            emitted_citations=presenter.state.get_emitted_citations(),
            request_params=presenter.state.get_request_params(),
        )

    def restore(self, emitter: Emitter, state: ChatStateContainer) -> ChatPresentation:
        state.set_request_params(self.request_params)
        state.set_answer_tokens(self.answer)
        state.set_reasoning_tokens(self.reasoning)
        state.set_pre_answer_processing_time(self.processing_seconds)
        for citation in self.emitted_citations:
            state.add_emitted_citation(citation)
        citations = self.citations.restore()
        state.set_citation_mapping(citations.citation_to_doc)
        return ChatPresentation.restore(self.presentation, emitter, state, citations)
