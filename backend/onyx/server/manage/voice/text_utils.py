from markdown_it import MarkdownIt
from markdown_it.token import Token

_md = MarkdownIt("commonmark")


def _render(tokens: list[Token]) -> str:
    out: list[str] = []
    for tok in tokens:
        if tok.type == "inline":
            out.append(_render(tok.children or []))
        elif tok.type in ("text", "code_inline"):
            out.append(tok.content)
        elif tok.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif tok.type.endswith("_close") and tok.block:
            # Block boundary (paragraph, heading, list item, ...) -> a space.
            out.append(" ")
    return "".join(out)


def strip_markdown_for_tts(text: str) -> str:
    """Reduce markdown to plain text so TTS does not read markup aloud.

    Parses with markdown-it (CommonMark) and keeps only readable text: emphasis,
    headers and links are unwrapped, code fences are dropped, and whitespace is
    collapsed. Applied server-side as a version-independent safety net, since the
    web bundle may lag the backend and not every TTS entry point strips on the
    client.
    """
    return " ".join(_render(_md.parse(text)).split())
