"""Unit tests for DocMost ProseMirror -> plaintext extraction.

These run without a live DocMost instance.
"""

from onyx.connectors.docmost.prosemirror import prosemirror_to_text


def _doc(*content: dict) -> dict:
    return {"type": "doc", "content": list(content)}


def test_empty_inputs() -> None:
    assert prosemirror_to_text(None) == ""
    assert prosemirror_to_text("") == ""
    assert prosemirror_to_text({}) == ""


def test_raw_string_fallback() -> None:
    assert prosemirror_to_text("plain text") == "plain text"


def test_heading_and_paragraph() -> None:
    doc = _doc(
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Title"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "Body."}]},
    )
    out = prosemirror_to_text(doc)
    assert "## Title" in out
    assert "Body." in out


def test_link_url_preserved() -> None:
    doc = _doc(
        {"type": "paragraph", "content": [
            {"type": "text", "text": "click",
             "marks": [{"type": "link", "attrs": {"href": "https://x.test"}}]},
        ]}
    )
    assert "https://x.test" in prosemirror_to_text(doc)


def test_list_items_become_bullets() -> None:
    doc = _doc(
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]},
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "two"}]}]},
        ]}
    )
    out = prosemirror_to_text(doc)
    assert "- one" in out and "- two" in out


def test_code_block_kept_verbatim() -> None:
    doc = _doc({"type": "codeBlock",
                "content": [{"type": "text", "text": "x = 1"}]})
    assert "x = 1" in prosemirror_to_text(doc)


def test_mermaid_and_math_dropped() -> None:
    doc = _doc(
        {"type": "mermaid", "content": [{"type": "text", "text": "graph TD; A-->B"}]},
        {"type": "mathBlock", "content": [{"type": "text", "text": "E=mc^2"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "kept"}]},
    )
    out = prosemirror_to_text(doc)
    assert "graph TD" not in out
    assert "E=mc^2" not in out
    assert "kept" in out


def test_json_string_input() -> None:
    import json
    doc = _doc({"type": "paragraph", "content": [{"type": "text", "text": "hi"}]})
    assert prosemirror_to_text(json.dumps(doc)) == "hi"
