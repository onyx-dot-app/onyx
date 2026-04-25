# knowledge_layer/providers/base.py
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class WikiPageDraft:
    slug: str
    title: str
    content: str


@dataclass
class CrossRefProposal:
    from_slug: str
    to_slug: str
    link_type: str  # "extends" | "contradicts" | "see-also" | "prerequisite"


@dataclass
class IngestResult:
    wiki_pages: list[WikiPageDraft]
    cross_refs: list[CrossRefProposal] = field(default_factory=list)


@dataclass
class QueryResult:
    answer: str
    citations: list[str]  # wiki page slugs


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def ingest_call(
        self,
        raw_content: str,
        existing_pages: list[WikiPageDraft],
        topic_name: str,
    ) -> IngestResult:
        """Synthesise wiki pages from a raw document."""

    @abc.abstractmethod
    def query_call(
        self,
        question: str,
        wiki_pages: list[WikiPageDraft],
    ) -> QueryResult:
        """Answer a question from wiki page content."""
