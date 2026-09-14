from types import SimpleNamespace

from onyx.tools.tool_implementations.search.candidate_preparation import (
    bounded_selection_prompt,
    distinct_document_sections,
    focused_excerpt,
)


def test_document_breadth_before_cap():
    sections = [
        SimpleNamespace(center_chunk=SimpleNamespace(document_id=doc))
        for doc in ["a", "a", "a", "b", "c"]
    ]
    assert [
        s.center_chunk.document_id
        for s in distinct_document_sections(sections, 3)  # ty: ignore[invalid-argument-type] Minimal section doubles exercise ordering only.
    ] == ["a", "b", "c"]


def test_excerpt_preserves_exact_late_matching_text():
    text = (
        "unrelated material " * 200
        + "The Optimize 1.3 legacy_hint field was removed in February."
    )
    result = focused_excerpt(text, "Optimize 1.3 legacy_hint February", 200)
    assert "legacy_hint" in result
    assert len(result) <= 200
    assert all(fragment in text for fragment in result.split(" ... "))


def test_budget_includes_wrapping_and_preserves_breadth():
    cards = [
        {
            "section_id": i,
            "title": str(i),
            "content": "long unrelated text " * 400,
            "metadata": "x" * 10000,
        }
        for i in range(20)
    ]
    prompt, diagnostics = bounded_selection_prompt(
        cards, "target", lambda s: "instructions " * 40 + s, len, 8000
    )
    assert len(prompt) <= 8000
    assert diagnostics["included_section_ids"] == list(range(20))
    assert diagnostics["omitted_section_ids"] == []
    assert diagnostics["excerpt_chars"] < 1600


def test_explicit_omission_when_even_tiny_cards_cannot_fit():
    cards = [
        {"section_id": i, "title": "a" * 256, "content": "x" * 100} for i in range(20)
    ]
    prompt, diagnostics = bounded_selection_prompt(
        cards, "target", lambda s: s, len, 1000
    )
    assert len(prompt) <= 1000
    assert diagnostics["omitted_section_ids"]
    assert diagnostics["included_section_ids"] + diagnostics[
        "omitted_section_ids"
    ] == list(range(20))


def test_priority_excerpt_space_and_opaque_title_compression():
    import json

    cards = [
        {
            "section_id": i,
            "title": "a" * 32 + "-useful-title",
            "content": "source text " * 800,
        }
        for i in range(40)
    ]
    prompt, diagnostics = bounded_selection_prompt(
        cards, "source", lambda s: s, len, 15000
    )
    payload = json.loads(prompt)
    assert payload[0]["title"].endswith("-useful-title")
    assert "a" * 32 not in payload[0]["title"]
    assert len(payload[0]["content"]) > len(payload[-1]["content"])
    assert diagnostics["included_section_ids"] == list(range(40))
