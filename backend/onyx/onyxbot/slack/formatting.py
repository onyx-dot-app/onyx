import re
from typing import Any

from mistune import create_markdown
from mistune import HTMLRenderer

# Tags that should be replaced with a newline (line-break and block-level elements)
_HTML_NEWLINE_TAG_PATTERN = re.compile(
    r"<br\s*/?>|</(?:p|div|li|h[1-6]|tr|blockquote|section|article)>",
    re.IGNORECASE,
)

# Strips any remaining HTML tag (opening, closing, or self-closing)
_HTML_TAG_PATTERN = re.compile(r"</?[a-zA-Z][^>]*>")

# Matches inline citation hyperlinks: [[1]](url), [[2]](url), etc.
# Uses balanced-paren matching to handle URLs with parentheses.
_INLINE_CITATION_LINK_PATTERN = re.compile(r"\[\[(\d+)\]\]\((?:[^()]*|\([^()]*\))*\)")


def _sanitize_for_slack(message: str) -> str:
    """Pre-process LLM output before markdown rendering for Slack compatibility.

    Handles two issues that cause broken Slack formatting regardless of source:
    1. HTML tags from documentation sources (SharePoint, Confluence, Google Drive,
       etc.) that would appear as literal escaped text in Slack after rendering.
       Block-level closing tags and <br> are converted to newlines; all other tags
       are stripped.
    2. Inline citation hyperlinks [[n]](url) where URLs with special characters
       (parentheses, pipes, spaces) break markdown link parsing, producing
       truncated 404 links. The bottom Sources section provides working links.
    """
    # First pass: convert line-break/block-closing tags to newlines
    message = _HTML_NEWLINE_TAG_PATTERN.sub("\n", message)
    # Second pass: strip all remaining HTML tags
    message = _HTML_TAG_PATTERN.sub("", message)
    # Strip citation hyperlinks, keeping plain [n] markers
    message = _INLINE_CITATION_LINK_PATTERN.sub(r"[\1]", message)
    return message


def format_slack_message(message: str | None) -> str:
    if message is None:
        return ""
    message = _sanitize_for_slack(message)
    md = create_markdown(renderer=SlackRenderer(), plugins=["strikethrough"])
    result = md(message)
    # With HTMLRenderer, result is always str (not AST list)
    assert isinstance(result, str)
    return result


class SlackRenderer(HTMLRenderer):
    """Renders markdown as Slack mrkdwn format instead of HTML.

    Overrides all HTMLRenderer methods that produce HTML tags to ensure
    no raw HTML ever appears in Slack messages.
    """

    SPECIALS: dict[str, str] = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}

    def escape_special(self, text: str) -> str:
        for special, replacement in self.SPECIALS.items():
            text = text.replace(special, replacement)
        return text

    def heading(self, text: str, level: int, **attrs: Any) -> str:  # noqa: ARG002
        return f"*{text}*\n"

    def emphasis(self, text: str) -> str:
        return f"_{text}_"

    def strong(self, text: str) -> str:
        return f"*{text}*"

    def strikethrough(self, text: str) -> str:
        return f"~{text}~"

    def list(self, text: str, ordered: bool, **attrs: Any) -> str:  # noqa: ARG002
        lines = text.split("\n")
        count = 0
        for i, line in enumerate(lines):
            if line.startswith("li: "):
                count += 1
                prefix = f"{count}. " if ordered else "• "
                lines[i] = f"{prefix}{line[4:]}"
        return "\n".join(lines)

    def list_item(self, text: str) -> str:
        return f"li: {text}\n"

    def link(self, text: str, url: str, title: str | None = None) -> str:
        escaped_url = self.escape_special(url)
        if text:
            return f"<{escaped_url}|{text}>"
        if title:
            return f"<{escaped_url}|{title}>"
        return f"<{escaped_url}>"

    def image(self, text: str, url: str, title: str | None = None) -> str:
        escaped_url = self.escape_special(url)
        display_text = title or text
        return f"<{escaped_url}|{display_text}>" if display_text else f"<{escaped_url}>"

    def codespan(self, text: str) -> str:
        return f"`{text}`"

    def block_code(self, code: str, info: str | None = None) -> str:  # noqa: ARG002
        return f"```\n{code}\n```\n"

    def linebreak(self) -> str:
        return "\n"

    def thematic_break(self) -> str:
        return "---\n"

    def block_quote(self, text: str) -> str:
        lines = text.strip().split("\n")
        quoted = "\n".join(f">{line}" for line in lines)
        return quoted + "\n"

    def block_html(self, html: str) -> str:
        return html + "\n"

    def block_error(self, text: str) -> str:
        return f"```\n{text}\n```\n"

    def paragraph(self, text: str) -> str:
        return f"{text}\n"
