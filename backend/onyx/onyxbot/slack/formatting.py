import re
from collections.abc import Callable
from typing import Any

from mistune import (
    BlockState,
    HTMLRenderer,
    InlineParser,
    InlineState,
    Markdown,
    PluginRef,
    create_markdown,
)

# Tags that should be replaced with a newline (line-break and block-level elements)
_HTML_NEWLINE_TAG_PATTERN = re.compile(
    r"<br\s*/?>|</(?:p|div|li|h[1-6]|tr|blockquote|section|article)>",
    re.IGNORECASE,
)

# Strips HTML tags but excludes autolinks like <https://...> and <mailto:...>
_HTML_TAG_PATTERN = re.compile(
    r"<(?!https?://|mailto:)/?[a-zA-Z][^>]*>",
)

# Fenced blocks before inline spans, so a fence wins over its own backticks
_CODE_PATTERN = re.compile(r"```[\s\S]*?```|`[^`\n]*`")

# Matches the start of any markdown link: [text]( or [[n]](
# The inner group handles nested brackets for citation links like [[1]](.
_MARKDOWN_LINK_PATTERN = re.compile(r"\[(?:[^\[\]]|\[[^\]]*\])*\]\(")

# Slack-style <url|text> links that LLMs sometimes emit directly. Mistune parses
# <scheme:...|label> as one autolink and percent-encodes the pipe, so these are
# rewritten before the parser sees them.
_SLACK_LINK_PATTERN = re.compile(r"<((?:https?://|mailto:)[^|<>]+)\|([^<>]+)>")
# Same shape against already-rendered output, where the label may be absent
_RENDERED_SLACK_LINK_PATTERN = re.compile(
    r"<((?:https?://|mailto:)[^|<>]+)(?:\|([^<>]*))?>"
)

# Bare URLs and emails are emitted explicitly because Slack's auto-linker absorbs
# an adjacent emphasis delimiter into the href (observed in Block Kit Builder).
_URL_LINK_PATTERN = r"https?://[^\s<>|]+"
_EMAIL_LOCAL_CHARACTER_CLASS = r"a-zA-Z0-9.!#$%&'*+/=?^_`{}~-"
_EMAIL_LOCAL_CHARACTER_PATTERN = re.compile(rf"[{_EMAIL_LOCAL_CHARACTER_CLASS}]")
_EMAIL_MARKDOWN_DELIMITER_LENGTHS = {"*": (1, 3), "_": (1, 3), "~": (2, 2)}
_EMAIL_LINK_PATTERN = (
    r"(?<![a-zA-Z0-9])"
    rf"[{_EMAIL_LOCAL_CHARACTER_CLASS}]{{1,64}}"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+"
    r"(?![a-zA-Z0-9-])"
)
_URL_TRAILING_PUNCTUATION = ".,:;\"'*_~"
_SLACK_SPECIALS: dict[str, str] = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def escape_slack_specials(text: str) -> str:
    """Make text safe to drop into mrkdwn without rendering it as markup."""
    for special, replacement in _SLACK_SPECIALS.items():
        text = text.replace(special, replacement)
    return text


def format_slack_link_url(url: str) -> str:
    return escape_slack_specials(url.replace("|", "%7C"))


def _escape_markdown_link_destination(url: str) -> str:
    return url.replace("|", "%7C").replace("<", "&lt;").replace(">", "&gt;")


def _format_slack_link_label(text: str) -> str:
    text = _RENDERED_SLACK_LINK_PATTERN.sub(
        lambda match: match.group(2) or match.group(1), text
    )
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _sanitize_html(text: str) -> str:
    """Strip HTML tags from a text fragment.

    Block-level closing tags and <br> are converted to newlines.
    All other HTML tags are removed. Autolinks (<https://...>) are preserved.
    """
    text = _HTML_NEWLINE_TAG_PATTERN.sub("\n", text)
    text = _HTML_TAG_PATTERN.sub("", text)
    return text


def _transform_outside_code_blocks(
    message: str, transform: Callable[[str], str]
) -> str:
    """Apply *transform* outside code spans and fenced blocks."""
    parts = _CODE_PATTERN.split(message)
    code_blocks = _CODE_PATTERN.findall(message)

    result: list[str] = []
    for i, part in enumerate(parts):
        result.append(transform(part))
        if i < len(code_blocks):
            result.append(code_blocks[i])

    return "".join(result)


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

        if destination:
            already_wrapped = destination.startswith("<") and destination.endswith(">")
            if already_wrapped:
                destination = destination[1:-1]
            destination = f"<{_escape_markdown_link_destination(destination)}>"

        normalized_parts.append(destination)
        normalized_parts.append(")")
        cursor = end_idx + 1

    normalized_parts.append(message[cursor:])
    return "".join(normalized_parts)


def _convert_slack_links_to_markdown(message: str) -> str:
    """Convert Slack-style <url|text> links to standard markdown [text](url).

    LLMs sometimes emit Slack mrkdwn link syntax directly. Mistune doesn't
    recognise it, so the angle brackets would be escaped by text() and Slack
    would render the link as literal text instead of a clickable link.
    """
    return _transform_outside_code_blocks(
        message, lambda text: _SLACK_LINK_PATTERN.sub(r"[\2](\1)", text)
    )


def _append_autolink(
    inline: InlineParser,
    state: InlineState,
    label: str,
    url: str,
    end_pos: int,
) -> int:
    # link() compares label to href before flattening, so a nested autolink
    # would defeat the redundant-label collapse
    if state.in_link or state.in_image:
        inline.process_text(label, state)
    else:
        state.append_token(
            {
                "type": "link",
                "children": [{"type": "text", "raw": label}],
                "attrs": {"url": url},
            }
        )
    return end_pos


def _trim_url_trailing_punctuation(url: str) -> str:
    """Give back trailing sentence punctuation and unbalanced closers.

    Shortening the match is what leaves a closing emphasis marker for the
    emphasis rule, so _URL_TRAILING_PUNCTUATION carries * _ ~ as well.
    """
    url = url.rstrip(_URL_TRAILING_PUNCTUATION)
    for opening, closing in (("(", ")"), ("[", "]")):
        excess = url.count(closing) - url.count(opening)
        while excess > 0 and url.endswith(closing):
            url = url[:-1]
            excess -= 1
    return url


def _parse_url_link(inline: InlineParser, m: re.Match[str], state: InlineState) -> int:
    url = _trim_url_trailing_punctuation(m.group(0))
    return _append_autolink(
        inline,
        state,
        label=url,
        url=url,
        end_pos=m.start() + len(url),
    )


def _parse_email_link(
    inline: InlineParser, m: re.Match[str], state: InlineState
) -> int:
    email = m.group(0)
    if _email_match_starts_inside_local_part(m, state):
        inline.process_text(email, state)
        return m.end()
    return _append_autolink(
        inline,
        state,
        label=email,
        url=f"mailto:{email}",
        end_pos=m.end(),
    )


def _email_match_starts_inside_local_part(m: re.Match[str], state: InlineState) -> bool:
    """True when the match is a truncated local part rather than a whole address.

    A preceding local-part character normally means the regex started mid-address.
    The exception is an emphasis run that brackets the match on both sides with
    the same delimiter at the same length, which makes it markup rather than text.
    """
    match_start, match_end = m.span()
    if match_start == 0:
        return False

    preceding_character = state.src[match_start - 1]
    if _EMAIL_LOCAL_CHARACTER_PATTERN.fullmatch(preceding_character) is None:
        return False

    delimiter_lengths = _EMAIL_MARKDOWN_DELIMITER_LENGTHS.get(preceding_character)
    if delimiter_lengths is None or m.group(0).startswith(preceding_character):
        return True

    before = state.src[:match_start]
    opening_run = len(before) - len(before.rstrip(preceding_character))
    minimum_length, maximum_length = delimiter_lengths
    return not (
        minimum_length <= opening_run <= maximum_length
        and state.src.startswith(preceding_character * opening_run, match_end)
    )


def _slack_autolink(md: Markdown) -> None:
    """Mistune plugin turning bare URLs and emails into link tokens.

    Link and image labels still reach these rules, so nesting is prevented by
    the in_link/in_image guard in _append_autolink.
    """
    md.inline.register("slack_url_link", _URL_LINK_PATTERN, _parse_url_link)
    md.inline.register("slack_email_link", _EMAIL_LINK_PATTERN, _parse_email_link)


def format_slack_message(message: str | None, render_links: bool = True) -> str:
    """Render markdown as Slack mrkdwn.

    Callers embedding the result inside a Slack link label must pass
    render_links=False, since a nested <...> would terminate the outer link.
    """
    if message is None:
        return ""
    message = _transform_outside_code_blocks(message, _sanitize_html)
    message = _convert_slack_links_to_markdown(message)
    normalized_message = _transform_outside_code_blocks(
        message, _normalize_link_destinations
    )
    plugins: list[PluginRef] = ["strikethrough", "table"]
    if render_links:
        plugins.append(_slack_autolink)
    md = create_markdown(
        renderer=SlackRenderer(render_links=render_links), plugins=plugins
    )
    result = md(normalized_message)
    # With HTMLRenderer, result is always str (not AST list)
    assert isinstance(result, str)
    return result.rstrip("\n")


class SlackRenderer(HTMLRenderer):
    """Renders markdown as Slack mrkdwn format instead of HTML.

    Overrides all HTMLRenderer methods that produce HTML tags to ensure
    no raw HTML ever appears in Slack messages.
    """

    def __init__(self, render_links: bool = True) -> None:
        super().__init__()
        self._render_links = render_links
        self._table_headers: list[str] = []
        self._current_row_cells: list[str] = []
        self._list_depth = 0

    def render_token(self, token: dict[str, Any], state: BlockState) -> str:
        # attrs["depth"] counts every block container, so a list inside a
        # blockquote reports depth 1. Only list ancestry may indent.
        if token["type"] != "list":
            return super().render_token(token, state)
        self._list_depth += 1
        try:
            return super().render_token(token, state)
        finally:
            self._list_depth -= 1

    def escape_special(self, text: str) -> str:
        return escape_slack_specials(text)

    def heading(self, text: str, level: int, **attrs: Any) -> str:  # noqa: ARG002
        return f"*{text}*\n\n"

    def emphasis(self, text: str) -> str:
        return f"_{text}_"

    def strong(self, text: str) -> str:
        return f"*{text}*"

    def strikethrough(self, text: str) -> str:
        return f"~{text}~"

    def list(self, text: str, ordered: bool, **attrs: Any) -> str:
        depth: int = self._list_depth - 1
        # An interrupting block splits a list, so the tail arrives as a fresh
        # list carrying the number it has to resume from
        number: int = attrs.get("start", 1)
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if not line.startswith("li: "):
                continue
            prefix = f"{number}. " if ordered else "• "
            lines[i] = f"{'  ' * depth}{prefix}{line[4:]}"
            number += 1

        rendered = "\n".join(lines)
        if not depth:
            return rendered + "\n"
        # A nested list is appended to its parent item's text, mid-line
        return "\n" + rendered.rstrip("\n")

    def list_item(self, text: str) -> str:
        return f"li: {text}\n"

    def link(self, text: str, url: str, title: str | None = None) -> str:
        escaped_url = format_slack_link_url(url)
        # A label identical to the href is what an autolinked bare URL produces
        label = text or (self.escape_special(title) if title else None)
        if not self._render_links:
            return _format_slack_link_label(label or self.escape_special(url))
        if label and label != escaped_url:
            return f"<{escaped_url}|{_format_slack_link_label(label)}>"
        return f"<{escaped_url}>"

    def image(self, text: str, url: str, title: str | None = None) -> str:
        escaped_url = format_slack_link_url(url)
        display_text = self.escape_special(title) if title else text
        display_text = _format_slack_link_label(
            display_text or self.escape_special(url)
        )
        if not self._render_links:
            return display_text
        return f"<{escaped_url}|{display_text}>" if display_text else f"<{escaped_url}>"

    def codespan(self, text: str) -> str:
        return f"`{text}`"

    def block_code(self, code: str, info: str | None = None) -> str:  # noqa: ARG002
        return f"```\n{code.rstrip(chr(10))}\n```\n\n"

    def linebreak(self) -> str:
        return "\n"

    def thematic_break(self) -> str:
        return "---\n\n"

    def block_quote(self, text: str) -> str:
        lines = text.strip().split("\n")
        quoted = "\n".join(f">{line}" for line in lines)
        return quoted + "\n\n"

    def block_html(self, html: str) -> str:
        return _sanitize_html(html) + "\n\n"

    def block_error(self, text: str) -> str:
        return f"```\n{text}\n```\n\n"

    def text(self, text: str) -> str:
        # Only escape the three entities Slack recognizes: & < >
        # HTMLRenderer.text() also escapes " to &quot; which Slack renders
        # as literal &quot; text since Slack doesn't recognize that entity.
        return self.escape_special(text)

    # -- Table rendering (converts markdown tables to vertical cards) --

    def table_cell(
        self,
        text: str,
        align: str | None = None,  # noqa: ARG002
        head: bool = False,  # noqa: ARG002
    ) -> str:
        if head:
            self._table_headers.append(text.strip())
        else:
            self._current_row_cells.append(text.strip())
        return ""

    def table_head(self, text: str) -> str:  # noqa: ARG002
        self._current_row_cells = []
        return ""

    def table_row(self, text: str) -> str:  # noqa: ARG002
        cells = self._current_row_cells
        self._current_row_cells = []
        # First column becomes the bold title, remaining columns are bulleted fields
        lines: list[str] = []
        if cells:
            title = cells[0]
            if title:
                # Avoid double-wrapping if cell already contains bold markup
                if title.startswith("*") and title.endswith("*") and len(title) > 1:
                    lines.append(title)
                else:
                    lines.append(f"*{title}*")
            for i, cell in enumerate(cells[1:], start=1):
                if i < len(self._table_headers):
                    lines.append(f"  • {self._table_headers[i]}: {cell}")
                else:
                    lines.append(f"  • {cell}")
        return "\n".join(lines) + "\n\n"

    def table_body(self, text: str) -> str:
        return text

    def table(self, text: str) -> str:
        self._table_headers = []
        self._current_row_cells = []
        return text + "\n"

    def paragraph(self, text: str) -> str:
        return f"{text}\n\n"
