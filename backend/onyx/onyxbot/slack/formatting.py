from mistune import Markdown  # type: ignore
from mistune import Renderer  # type: ignore


def format_slack_message(message: str | None) -> str:
    return Markdown(renderer=SlackRenderer()).render(message)


class SlackRenderer(Renderer):
    SPECIALS: dict[str, str] = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}

    def escape_special(self, text: str) -> str:
        for special, replacement in self.SPECIALS.items():
            text = text.replace(special, replacement)
        return text

    def header(self, text: str, level: int, raw: str | None = None) -> str:
        return f"*{text}*\n"

    def emphasis(self, text: str) -> str:
        return f"_{text}_"

    def double_emphasis(self, text: str) -> str:
        return f"*{text}*"

    def strikethrough(self, text: str) -> str:
        return f"~{text}~"

    def list(self, body: str, ordered: bool = True) -> str:
        lines = body.split("\n")
        count = 0
        for i, line in enumerate(lines):
            if line.startswith("li: "):
                count += 1
                prefix = f"{count}. " if ordered else "• "
                lines[i] = f"{prefix}{line[4:]}"
        return "\n".join(lines)

    def list_item(self, text: str) -> str:
        return f"li: {text}\n"

    def link(self, link: str, title: str | None, content: str | None) -> str:
        escaped_link = self.escape_special(link)
        if content:
            return f"<{escaped_link}|{content}>"
        if title:
            return f"<{escaped_link}|{title}>"
        return f"<{escaped_link}>"

    def image(self, src: str, title: str | None, text: str | None) -> str:
        escaped_src = self.escape_special(src)
        display_text = title or text
        return f"<{escaped_src}|{display_text}>" if display_text else f"<{escaped_src}>"

    def codespan(self, text: str) -> str:
        return f"`{text}`"

    def block_code(self, text: str, lang: str | None) -> str:
        return f"```\n{text}\n```\n"

    def paragraph(self, text: str) -> str:
        return f"{text}\n"

    def autolink(self, link: str, is_email: bool) -> str:
        return link if is_email else self.link(link, None, None)
