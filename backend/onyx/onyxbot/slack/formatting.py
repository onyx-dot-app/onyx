from typing import Any

from mistune import create_markdown
from mistune import HTMLRenderer


def format_slack_message(message: str | None) -> str:
    if message is None:
        return ""
    md = create_markdown(renderer=SlackRenderer(), plugins=["strikethrough"])
    result = md(message)
    # With HTMLRenderer, result is always str (not AST list)
    assert isinstance(result, str)
    return result


class SlackRenderer(HTMLRenderer):
    SPECIALS: dict[str, str] = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}

    def escape_special(self, text: str) -> str:
        for special, replacement in self.SPECIALS.items():
            text = text.replace(special, replacement)
        return text

    def heading(self, text: str, level: int, **attrs: Any) -> str:
        return f"*{text}*\n"

    def emphasis(self, text: str) -> str:
        return f"_{text}_"

    def strong(self, text: str) -> str:
        return f"*{text}*"

    def strikethrough(self, text: str) -> str:
        return f"~{text}~"

    def list(self, text: str, ordered: bool, **attrs: Any) -> str:
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

    def block_code(self, code: str, info: str | None = None) -> str:
        return f"```\n{code}\n```\n"

    def paragraph(self, text: str) -> str:
        return f"{text}\n"
