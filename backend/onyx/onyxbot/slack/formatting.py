import re
from typing import Any

from mistune import create_markdown
from mistune import HTMLRenderer

_CITATION_LINK_PATTERN = re.compile(r"\[\[\d+\]\]\(")


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


def _normalize_citation_link_destinations(message: str) -> str:
    """Wrap citation URLs in angle brackets so markdown parsers handle parentheses safely."""
    if "[[" not in message:
        return message

    normalized_parts: list[str] = []
    cursor = 0

    while match := _CITATION_LINK_PATTERN.search(message, cursor):
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
    md = create_markdown(renderer=SlackRenderer(), plugins=["strikethrough"])
    normalized_message = _normalize_citation_link_destinations(message)
    result = md(normalized_message)
    # With HTMLRenderer, result is always str (not AST list)
    assert isinstance(result, str)
    return result


class SlackRenderer(HTMLRenderer):
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

    def paragraph(self, text: str) -> str:
        return f"{text}\n"
