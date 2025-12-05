from mistune import create_markdown
from mistune.renderers.html import HTMLRenderer


def format_slack_message(message: str | None) -> str:
    if message is None:
        return ""
    markdown = create_markdown(renderer=SlackRenderer())
    result = markdown(message)
    return result if isinstance(result, str) else ""


class SlackRenderer(HTMLRenderer):
    SPECIALS: dict[str, str] = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}

    def escape_special(self, text: str) -> str:
        for special, replacement in self.SPECIALS.items():
            text = text.replace(special, replacement)
        return text

    def heading(self, text: str, level: int, **attrs: dict) -> str:
        return f"*{text}*\n"

    def emphasis(self, text: str) -> str:
        return f"_{text}_"

    def strong(self, text: str) -> str:
        return f"*{text}*"

    def strikethrough(self, text: str) -> str:
        return f"~{text}~"

    def list(self, text: str, ordered: bool, **attrs: dict) -> str:
        lines = text.split("\n")
        count = 0
        for i, line in enumerate(lines):
            if line.startswith("li: "):
                count += 1
                prefix = f"{count}. " if ordered else "• "
                lines[i] = f"{prefix}{line[4:]}"
        return "\n".join(lines)

    def list_item(self, text: str, **attrs: dict) -> str:
        return f"li: {text}\n"

    def link(self, text: str, url: str, title: str | None = None) -> str:
        escaped_link = self.escape_special(url)
        if text:
            return f"<{escaped_link}|{text}>"
        if title:
            return f"<{escaped_link}|{title}>"
        return f"<{escaped_link}>"

    def image(self, text: str, url: str, title: str | None = None) -> str:
        escaped_src = self.escape_special(url)
        display_text = title or text
        return f"<{escaped_src}|{display_text}>" if display_text else f"<{escaped_src}>"

    def codespan(self, text: str) -> str:
        return f"`{text}`"

    def block_code(self, code: str, info: str | None = None) -> str:
        return f"```\n{code}\n```\n"

    def paragraph(self, text: str) -> str:
        return f"{text}\n"

    def autolink(self, text: str, url: str) -> str:
        return url if url.startswith("mailto:") else self.link(text or "", url, None)
