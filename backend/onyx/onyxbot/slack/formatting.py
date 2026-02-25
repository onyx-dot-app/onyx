import re
from typing import Any

from mistune import create_markdown
from mistune import HTMLRenderer

# Tags that should be replaced with a newline (line-break and block-level elements)
_HTML_NEWLINE_TAG_PATTERN = re.compile(
    r"<br\s*/?>|</(?:p|div|li|h[1-6]|tr|blockquote|section|article)>",
    re.IGNORECASE,
)

# Strips HTML tags but excludes autolinks like <https://...> and <mailto:...>
_HTML_TAG_PATTERN = re.compile(
    r"<(?!https?://|mailto:)/?[a-zA-Z][^>]*>",
)

# Matches fenced code blocks (``` ... ```) so we can skip sanitization inside them
_FENCED_CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")

# Matches the start of any markdown link: [text]( or [[n]](
# The inner group handles nested brackets for citation links like [[1]](.
_MARKDOWN_LINK_PATTERN = re.compile(r"\[(?:[^\[\]]|\[[^\]]*\])*\]\(")


def _sanitize_html(text: str) -> str:
    """Strip HTML tags from a text fragment.

    Block-level closing tags and <br> are converted to newlines.
    All other HTML tags are removed. Autolinks (<https://...>) are preserved.
    """
    text = _HTML_NEWLINE_TAG_PATTERN.sub("\n", text)
    text = _HTML_TAG_PATTERN.sub("", text)
    return text


def _sanitize_for_slack(message: str) -> str:
    """Pre-process LLM output before markdown rendering for Slack compatibility.

    Strips HTML tags from documentation sources (SharePoint, Confluence, Google
    Drive, etc.) that would otherwise appear as literal escaped text in Slack.
    Code blocks are preserved intact to avoid mangling code samples containing HTML.
    """
    parts = _FENCED_CODE_BLOCK_PATTERN.split(message)
    code_blocks = _FENCED_CODE_BLOCK_PATTERN.findall(message)

    sanitized: list[str] = []
    for i, part in enumerate(parts):
        sanitized.append(_sanitize_html(part))
        if i < len(code_blocks):
            sanitized.append(code_blocks[i])

    return "".join(sanitized)


def _extract_link_destination(message: str, start_idx: int) -> tuple[str, int | None]:
    """Extract markdown link destination, allowing nested parentheses in the URL."""
    depth = 0
    i = start_idx

    while i < len(message):
        curr = message[i]
        if curr == "\\":
            i += 2
            continue

        if curr == "(":
            depth += 1
        elif curr == ")":
            if depth == 0:
                return message[start_idx:i], i
            depth -= 1
        i += 1

    return message[start_idx:], None


def _normalize_link_destinations(message: str) -> str:
    """Wrap markdown link URLs in angle brackets so the parser handles special chars safely.

    Markdown link syntax [text](url) breaks when the URL contains unescaped
    parentheses, spaces, or other special characters. Wrapping the URL in angle
    brackets — [text](<url>) — tells the parser to treat everything inside as
    a literal URL. This applies to all links, not just citations.
    """
    if "](" not in message:
        return message

    normalized_parts: list[str] = []
    cursor = 0

    while match := _MARKDOWN_LINK_PATTERN.search(message, cursor):
        normalized_parts.append(message[cursor : match.end()])
        destination_start = match.end()
        destination, end_idx = _extract_link_destination(message, destination_start)
        if end_idx is None:
            normalized_parts.append(message[destination_start:])
            return "".join(normalized_parts)

        already_wrapped = destination.startswith("<") and destination.endswith(">")
        if destination and not already_wrapped:
            destination = f"<{destination}>"

        normalized_parts.append(destination)
        normalized_parts.append(")")
        cursor = end_idx + 1

    normalized_parts.append(message[cursor:])
    return "".join(normalized_parts)


def format_slack_message(message: str | None) -> str:
    if message is None:
        return ""
    message = _sanitize_for_slack(message)
    normalized_message = _normalize_link_destinations(message)
    md = create_markdown(renderer=SlackRenderer(), plugins=["strikethrough"])
    result = md(normalized_message)
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
        return _sanitize_html(html) + "\n"

    def block_error(self, text: str) -> str:
        return f"```\n{text}\n```\n"

    def text(self, text: str) -> str:
        # Only escape the three entities Slack recognizes: & < >
        # HTMLRenderer.text() also escapes " to &quot; which Slack renders
        # as literal &quot; text since Slack doesn't recognize that entity.
        return self.escape_special(text)

    def paragraph(self, text: str) -> str:
        return f"{text}\n"
