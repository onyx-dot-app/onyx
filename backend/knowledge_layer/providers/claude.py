# knowledge_layer/providers/claude.py
from __future__ import annotations

import json
import os

import anthropic

from knowledge_layer.providers.base import (
    CrossRefProposal,
    IngestResult,
    LLMProvider,
    QueryResult,
    WikiPageDraft,
)

_INGEST_SYSTEM = """\
You are a wiki synthesis engine. Given a raw source document and the existing \
wiki pages for a topic, produce structured wiki pages that compile the knowledge.

Respond ONLY with valid JSON in this exact shape:
{
  "wiki_pages": [
    {"slug": "kebab-case-slug", "title": "Human Readable Title", "content": "Markdown content"}
  ],
  "cross_refs": [
    {"from_slug": "slug-a", "to_slug": "slug-b", "link_type": "see-also"}
  ]
}

link_type must be one of: extends, contradicts, see-also, prerequisite.
slug must be lowercase kebab-case, unique within the topic.
"""

_QUERY_SYSTEM = """\
You are a wiki query engine. Given wiki pages and a question, answer concisely \
using only the provided wiki content.

Respond ONLY with valid JSON in this exact shape:
{
  "answer": "Your answer here.",
  "citations": ["slug-of-page-used", "another-slug"]
}
"""


class ClaudeProvider(LLMProvider):
    MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    def ingest_call(
        self,
        raw_content: str,
        existing_pages: list[WikiPageDraft],
        topic_name: str,
    ) -> IngestResult:
        existing_summary = "\n\n".join(
            f"# {p.title} ({p.slug})\n{p.content[:500]}" for p in existing_pages
        ) or "(none)"

        user_msg = (
            f"Topic: {topic_name}\n\n"
            f"Existing wiki pages:\n{existing_summary}\n\n"
            f"New raw document to synthesise:\n{raw_content}"
        )

        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=4096,
            system=_INGEST_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_msg,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        )

        data = json.loads(response.content[0].text)
        return IngestResult(
            wiki_pages=[WikiPageDraft(**p) for p in data["wiki_pages"]],
            cross_refs=[CrossRefProposal(**r) for r in data.get("cross_refs", [])],
        )

    def query_call(
        self,
        question: str,
        wiki_pages: list[WikiPageDraft],
    ) -> QueryResult:
        context = "\n\n".join(
            f"# {p.title} (slug: {p.slug})\n{p.content}" for p in wiki_pages
        ) or "(no wiki pages available)"

        user_msg = f"Wiki pages:\n{context}\n\nQuestion: {question}"

        response = self._client.messages.create(
            model=self.MODEL,
            max_tokens=2048,
            system=_QUERY_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_msg,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        )

        data = json.loads(response.content[0].text)
        return QueryResult(answer=data["answer"], citations=data.get("citations", []))
