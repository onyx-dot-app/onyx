from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from onyx.agents.v2.models import HarnessPolicy, ToolOutput

MAX_NAME_CHARS = 128
MAX_OBJECTIVE_CHARS = 1000
MAX_RECEIPT_JSON_CHARS = 6000
MAX_READ_CHARS = 20000
COMPACT_NAVIGATION_GUIDANCE = (
    "inspect a promising handle with internal_search(objective=missing fact, "
    "candidate_handle=handle, offset=0). Alternatives are retrieved leads, not "
    "verified answers or citations. Compare the exact entity, event date, version, "
    "and requested quantity before relying on a candidate."
)


class ContextBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class _StoredResult:
    ref: str
    tool_name: str
    objective: str
    output: ToolOutput
    body_hash: str
    duplicate_of: str | None
    stored_bytes: int
    truncated: bool


class ContextState:
    def __init__(
        self,
        policy: HarnessPolicy,
        token_counter: Callable[[str], int],
    ) -> None:
        self._policy = policy
        self._token_counter = token_counter
        self._results: list[_StoredResult] = []
        self._by_ref: dict[str, _StoredResult] = {}
        self._body_hash_to_ref: dict[str, str] = {}
        self._stored_bytes = 0

    @property
    def citation_mapping(self) -> dict[int, str]:
        return {
            number: document_id
            for result in self._results
            for number, document_id in result.output.citation_mapping.items()
        }

    @property
    def receipts(self) -> list[dict[str, Any]]:
        return [self._receipt(result) for result in self._results]

    def add(self, tool_name: str, objective: str, output: ToolOutput) -> str:
        ref = f"result_{len(self._results) + 1:04d}"
        clean_tool_name = _limit_text(tool_name, MAX_NAME_CHARS)
        clean_objective = _limit_text(objective, MAX_OBJECTIVE_CHARS)
        body_hash = _hash_text(output.content)
        duplicate_of = self._body_hash_to_ref.get(body_hash)
        stored_output, stored_bytes, truncated = self._bounded_output(output)

        result = _StoredResult(
            ref=ref,
            tool_name=clean_tool_name,
            objective=clean_objective,
            output=stored_output,
            body_hash=body_hash,
            duplicate_of=duplicate_of,
            stored_bytes=stored_bytes,
            truncated=truncated,
        )
        self._results.append(result)
        self._by_ref[ref] = result
        self._stored_bytes += stored_bytes

        if duplicate_of is None:
            self._body_hash_to_ref[body_hash] = ref

        return ref

    def render(self, max_tokens: int) -> str:
        if self._policy.preserve_search_evidence:
            return self._render_balanced(max_tokens)
        if self._policy.search_feedback == "visibility":
            return self._render_with_visibility(max_tokens)
        payload: dict[str, Any] = {
            "receipts": self.receipts,
            "results": [],
        }
        if self._count(payload) > max_tokens:
            return self._render_minimal_markers(
                list(reversed(self._results)), max_tokens
            )

        for result in reversed(self._results):
            entry: dict[str, Any] = {
                "result_ref": result.ref,
                "tool_name": result.tool_name,
                "status": result.output.status,
            }
            payload["results"].append(entry)

            if result.output.answer:
                self._fit_field(
                    payload, entry, "answer", result.output.answer, max_tokens
                )

            content = result.output.content
            if not content:
                continue

            preview = self._largest_fit(
                payload=payload,
                entry=entry,
                field="content_preview",
                text=content,
                max_tokens=max_tokens,
            )
            if preview < len(content):
                entry["content_truncated"] = True
                entry["read_more"] = {
                    "result_ref": result.ref,
                    "offset": preview,
                }
                if self._count(payload) > max_tokens:
                    del entry["content_truncated"]
                    del entry["read_more"]

        return _json(payload)

    def _render_balanced(self, max_tokens: int) -> str:
        """Share constrained context across results; never silently erase markers.

        This retains prefixes, not semantic summaries. The read offset always
        addresses the original stored text and citations are never renumbered.
        """
        results = list(reversed(self._results))

        def payload(limit: int) -> dict[str, Any]:
            entries = []
            for result in results:
                content = result.output.content
                shown = min(limit, len(content))
                entry: dict[str, Any] = {
                    "result_ref": result.ref,
                    "tool_name": result.tool_name,
                    "status": result.output.status,
                    "content_preview": content[:shown],
                    "content_truncated": shown < len(content),
                    "read_more": {"result_ref": result.ref, "offset": shown}
                    if shown < len(content)
                    else None,
                }
                if result.output.answer:
                    entry["answer"] = result.output.answer[:limit]
                entries.append(entry)
            return {"receipts": self.receipts, "results": entries}

        if self._count(payload(0)) > max_tokens:
            return self._render_minimal_markers(results, max_tokens)
        low, high = (
            0,
            max(
                (
                    max(len(r.output.content), len(r.output.answer or ""))
                    for r in results
                ),
                default=0,
            ),
        )
        full = payload(high)
        if self._count(full) <= max_tokens:
            return _json(full)
        best = payload(0)
        while low <= high:
            middle = (low + high) // 2
            candidate = payload(middle)
            if self._count(candidate) <= max_tokens:
                best, low = candidate, middle + 1
            else:
                high = middle - 1
        return _json(best)

    def _render_minimal_markers(
        self, results: list[_StoredResult], max_tokens: int
    ) -> str:
        entries = [
            {
                "result_ref": result.ref,
                "status": result.output.status,
                "content_truncated": bool(result.output.content),
                "read_more": {"result_ref": result.ref, "offset": 0}
                if result.output.content
                else None,
            }
            for result in results
        ]
        payload = {"receipts": [], "results": entries}
        if self._count(payload) > max_tokens:
            raise ContextBudgetExceeded(
                "Evidence visibility markers exceed context budget"
            )
        return _json(payload)

    def _render_with_visibility(self, max_tokens: int) -> str:
        payload: dict[str, Any] = {"receipts": self.receipts, "results": []}
        for result in reversed(self._results):
            payload["results"].append(
                {
                    "result_ref": result.ref,
                    "tool_name": result.tool_name,
                    "status": result.output.status,
                    "visibility": {
                        "stored_chars": len(result.output.content),
                        "shown_chars": 0,
                        "omitted_stored_chars": len(result.output.content),
                        "store_truncated": result.truncated,
                        "source_completeness": "unknown",
                    },
                    "content_truncated": bool(result.output.content),
                    "read_more": {"result_ref": result.ref, "offset": 0}
                    if result.output.content
                    else None,
                }
            )
        # Reserve every marker before fitting evidence, including older results.
        if self._count(payload) > max_tokens:
            raise ContextBudgetExceeded(
                "Receipts and visibility markers exceed the context budget"
            )
        for result, entry in zip(
            reversed(self._results), payload["results"], strict=False
        ):
            if result.output.answer:
                self._fit_field(
                    payload, entry, "answer", result.output.answer, max_tokens
                )
            content = result.output.content

            def set_preview(
                length: int,
                entry: dict[str, Any] = entry,
                content: str = content,
                result: _StoredResult = result,
            ) -> None:
                entry["content_preview"] = content[:length]
                entry["content_truncated"] = length < len(content)
                entry["read_more"] = (
                    {"result_ref": result.ref, "offset": length}
                    if length < len(content)
                    else None
                )
                entry["visibility"]["shown_chars"] = length
                entry["visibility"]["omitted_stored_chars"] = len(content) - length

            set_preview(len(content))
            if self._count(payload) <= max_tokens:
                continue
            low, high, best = 0, len(content), 0
            while low <= high:
                mid = (low + high) // 2
                set_preview(mid)
                if self._count(payload) <= max_tokens:
                    best, low = mid, mid + 1
                else:
                    high = mid - 1
            set_preview(best)
            if self._count(payload) > max_tokens:
                entry.pop("content_preview")
            if self._count(payload) > max_tokens:
                raise ContextBudgetExceeded(
                    "Visibility markers exceed the context budget"
                )
        return _json(payload)

    def read(
        self,
        result_ref: str,
        offset: int = 0,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        result = self._by_ref.get(result_ref)
        if result is None:
            raise KeyError(f"Unknown result_ref: {result_ref}")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        bounded_max_chars = min(max(max_chars, 0), MAX_READ_CHARS)
        content = result.output.content
        next_offset = min(offset + bounded_max_chars, len(content))
        response = {
            "result_ref": result.ref,
            "tool_name": result.tool_name,
            "status": result.output.status,
            "offset": offset,
            "content": content[offset:next_offset],
            "next_offset": next_offset,
            "has_more": next_offset < len(content),
        }
        if self._policy.search_feedback == "visibility":
            response["store_truncated"] = result.truncated
            response["source_completeness"] = "unknown"
        return response

    def output(self, result_ref: str) -> ToolOutput:
        result = self._by_ref.get(result_ref)
        if result is None:
            raise KeyError(f"Unknown result_ref: {result_ref}")
        return result.output.model_copy(deep=True)

    def _bounded_output(self, output: ToolOutput) -> tuple[ToolOutput, int, bool]:
        budget = self._policy.max_store_bytes - self._stored_bytes
        if budget <= 0:
            raise ContextBudgetExceeded("Result store budget is exhausted")

        receipt = _bounded_receipt(output.receipt)
        answer = output.answer or ""
        content = output.content
        base = ToolOutput(
            status=output.status,
            content="",
            answer=answer or None,
            receipt=receipt,
            document_ids=list(output.document_ids),
            citation_mapping=dict(output.citation_mapping),
        )
        base_bytes = _stored_size(base)
        remaining = max(
            self._policy.max_store_bytes - self._stored_bytes - base_bytes, 0
        )
        clipped_content, content_truncated = _clip_to_bytes(content, remaining)

        stored = base.model_copy(update={"content": clipped_content})
        stored_bytes = _stored_size(stored)
        if stored_bytes <= self._policy.max_store_bytes - self._stored_bytes:
            return stored, stored_bytes, content_truncated

        fallback = ToolOutput(
            status=output.status,
            content="",
            answer=None,
            receipt={
                "truncated": True,
                "truncated_note": "Output exceeded the harness result store budget.",
            },
            document_ids=[],
            citation_mapping={},
        )
        fallback_bytes = _stored_size(fallback)
        if fallback_bytes > budget:
            raise ContextBudgetExceeded(
                "Result metadata exceeds the remaining store budget"
            )

        answer_budget = budget - fallback_bytes
        clipped_answer, _ = _clip_to_bytes(answer, answer_budget)
        stored = ToolOutput(
            status=output.status,
            content="",
            answer=clipped_answer or None,
            receipt=fallback.receipt,
            document_ids=[],
            citation_mapping={},
        )
        stored_bytes = _stored_size(stored)
        if stored_bytes > budget:
            stored = fallback
            stored_bytes = fallback_bytes
        return stored, stored_bytes, True

    def _receipt(self, result: _StoredResult) -> dict[str, Any]:
        receipt = {
            "result_ref": result.ref,
            "tool_name": result.tool_name,
            "objective": result.objective,
            "status": result.output.status,
            "document_ids": result.output.document_ids,
            "citation_count": len(result.output.citation_mapping),
            "answer_present": result.output.answer is not None,
            "body_sha256": result.body_hash,
            "exact_duplicate": result.duplicate_of is not None,
            "duplicate_of": result.duplicate_of,
            "stored_bytes": result.stored_bytes,
            "truncated": result.truncated,
            "tool_receipt": result.output.receipt,
        }
        return receipt

    def _fit_field(
        self,
        payload: dict[str, Any],
        entry: dict[str, Any],
        field: str,
        text: str,
        max_tokens: int,
    ) -> None:
        entry[field] = text
        if self._count(payload) <= max_tokens:
            return
        del entry[field]

    def _largest_fit(
        self,
        *,
        payload: dict[str, Any],
        entry: dict[str, Any],
        field: str,
        text: str,
        max_tokens: int,
    ) -> int:
        low = 0
        high = len(text)
        best = 0
        while low <= high:
            mid = (low + high) // 2
            entry[field] = text[:mid]
            if self._count(payload) <= max_tokens:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        if best:
            entry[field] = text[:best]
        else:
            entry.pop(field, None)
        return best

    def _count(self, payload: dict[str, Any]) -> int:
        return self._token_counter(_json(payload))


def _bounded_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    safe_receipt = copy.deepcopy(receipt)
    if len(_json(safe_receipt)) <= MAX_RECEIPT_JSON_CHARS:
        return safe_receipt

    compact = {
        "truncated": True,
        "truncated_note": "Tool receipt exceeded the harness receipt budget.",
    }
    for key in (
        "query",
        "objective",
        "selection_question",
        "search_type",
        "tool",
        "status",
    ):
        value = safe_receipt.get(key)
        if isinstance(value, str):
            compact[key] = _limit_text(value, 500)
    for key in (
        "retrieved_document_count",
        "evidence_document_count",
        "duration_ms",
    ):
        value = safe_receipt.get(key)
        if isinstance(value, int | float | bool):
            compact[key] = value
    compact_navigation = _compact_navigation_receipt(safe_receipt.get("navigation"))
    if compact_navigation:
        compact["navigation"] = compact_navigation
    return compact


def _compact_navigation_receipt(value: Any) -> dict[str, Any] | None:  # noqa: C901
    if not isinstance(value, dict):
        return None

    compact: dict[str, Any] = {}
    diagnostics_available = value.get("diagnostics_available")
    if isinstance(diagnostics_available, bool):
        compact["diagnostics_available"] = diagnostics_available

    queries = []
    raw_queries = value.get("queries")
    if isinstance(raw_queries, list):
        for raw_query in raw_queries[:8]:
            if not isinstance(raw_query, dict):
                continue
            query: dict[str, Any] = {}
            for key in (
                "query_id",
                "returned_documents",
                "unique_to_this_query",
                "new_documents_this_task",
                "hybrid_alpha",
            ):
                query_value = raw_query.get(key)
                if isinstance(query_value, int | float | bool):
                    query[key] = query_value
            query_text = raw_query.get("query")
            if isinstance(query_text, str):
                query["query"] = _limit_text(query_text, 160)
            evidence_citations = raw_query.get("evidence_citations")
            if isinstance(evidence_citations, list):
                query["evidence_citations"] = evidence_citations[:20]
            if query:
                queries.append(query)
    if queries:
        compact["queries"] = queries

    stages = value.get("stages")
    if isinstance(stages, dict):
        compact["stages"] = {
            key: count
            for key, count in stages.items()
            if isinstance(key, str) and isinstance(count, int | float | bool)
        }

    alternatives = []
    raw_alternatives = value.get("alternatives")
    if isinstance(raw_alternatives, list):
        for raw_alternative in raw_alternatives[:3]:
            if not isinstance(raw_alternative, dict):
                continue
            alternative: dict[str, Any] = {}
            for key in (
                "handle",
                "document_id",
                "chunk_id",
                "title",
                "stage",
            ):
                alternative_value = raw_alternative.get(key)
                if isinstance(alternative_value, str):
                    alternative[key] = _limit_text(alternative_value, 180)
            for key in (
                "query_id",
                "rank",
                "available_chars",
                "source_chunk_chars",
            ):
                alternative_value = raw_alternative.get(key)
                if isinstance(alternative_value, int | float | bool):
                    alternative[key] = alternative_value
            excerpt = raw_alternative.get("excerpt")
            if isinstance(excerpt, str):
                alternative["excerpt"] = _limit_text(excerpt, 360)
            if alternative:
                alternatives.append(alternative)
    if alternatives:
        compact["alternatives"] = alternatives

    for key in ("repeated_candidate_documents", "new_candidate_documents"):
        count = value.get(key)
        if isinstance(count, int | float | bool):
            compact[key] = count

    guidance = value.get("guidance")
    if isinstance(guidance, str):
        compact_guidance = _limit_text(guidance, 900)
        compact["guidance"] = (
            compact_guidance
            if "inspect" in compact_guidance.lower()
            else COMPACT_NAVIGATION_GUIDANCE
        )

    return compact or None


def _limit_text(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[: max_chars - 3] + "..."


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clip_to_bytes(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    if max_bytes <= 0:
        return "", bool(value)
    clipped = encoded[:max_bytes]
    return clipped.decode("utf-8", errors="ignore"), True


def _stored_size(output: ToolOutput) -> int:
    return len(output.model_dump_json().encode("utf-8"))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
