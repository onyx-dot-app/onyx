import codecs
import json
import re
import string
from urllib.parse import quote

from onyx.utils.logger import setup_logger

logger = setup_logger(__name__)

# Mapping of curly/smart quotes to straight quotes
CURLY_TO_STRAIGHT_QUOTES: dict[str, str] = {
    "\u2019": "'",  # Right single quotation mark
    "\u2018": "'",  # Left single quotation mark
    "\u201c": '"',  # Left double quotation mark
    "\u201d": '"',  # Right double quotation mark
}

# Zero-width characters that should typically be removed during text normalization
ZERO_WIDTH_CHARS: set[str] = {
    "\u200b",  # Zero-width space
    "\u200c",  # Zero-width non-joiner
    "\u200d",  # Zero-width joiner
    "\ufeff",  # Byte order mark / zero-width no-break space
    "\u2060",  # Word joiner
}


def normalize_curly_quotes(text: str) -> str:
    """Convert curly/smart quotes to straight quotes."""
    for curly, straight in CURLY_TO_STRAIGHT_QUOTES.items():
        text = text.replace(curly, straight)
    return text


def is_zero_width_char(c: str) -> bool:
    """Check if a character is a zero-width character."""
    return c in ZERO_WIDTH_CHARS


ESCAPE_SEQUENCE_RE = re.compile(
    r"""
    ( \\U........      # 8-digit hex escapes
    | \\u....          # 4-digit hex escapes
    | \\x..            # 2-digit hex escapes
    | \\[0-7]{1,3}     # Octal escapes
    | \\N\{[^}]+\}     # Unicode characters by name
    | \\[\\'"abfnrtv]  # Single-character escapes
    )""",
    re.UNICODE | re.VERBOSE,
)

_INITIAL_FILTER = re.compile(
    "["
    "\U0000fff0-\U0000ffff"  # Specials
    "\U0001f000-\U0001f9ff"  # Emoticons
    "\U0000200b-\U0000200f\U0000202a-\U0000202e\U00002060-\U0000206f"  # Format controls
    "\U00002190-\U000021ff"  # Arrows
    "\U00002700-\U000027bf"  # Dingbats
    "]+",
    flags=re.UNICODE,
)

# Regex to match invalid Unicode characters that cause UTF-8 encoding errors:
# - \x00-\x08: Control characters (except tab \x09)
# - \x0b-\x0c: Vertical tab and form feed
# - \x0e-\x1f: More control characters (except newline \x0a, carriage return \x0d)
# - \ud800-\udfff: Surrogate pairs (invalid when unpaired, causes "surrogates not allowed" errors)
# - \ufdd0-\ufdef: Non-characters
# - \ufffe-\uffff: Non-characters
_INVALID_UNICODE_CHARS_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufdd0-\ufdef\ufffe\uffff]"
)


def decode_escapes(s: str) -> str:
    def decode_match(match: re.Match) -> str:
        return codecs.decode(match.group(0), "unicode-escape")

    return ESCAPE_SEQUENCE_RE.sub(decode_match, s)


def make_url_compatible(s: str) -> str:
    s_with_underscores = s.replace(" ", "_")
    return quote(s_with_underscores, safe="")


def has_unescaped_quote(s: str) -> bool:
    pattern = r'(?<!\\)"'
    return bool(re.search(pattern, s))


def escape_newlines(s: str) -> str:
    return re.sub(r"(?<!\\)\n", "\\\\n", s)


def replace_whitespaces_w_space(s: str) -> str:
    return re.sub(r"\s", " ", s)


# Function to remove punctuation from a string
def remove_punctuation(s: str) -> str:
    return s.translate(str.maketrans("", "", string.punctuation))


def escape_quotes(original_json_str: str) -> str:
    result = []
    in_string = False
    for i, char in enumerate(original_json_str):
        if char == '"':
            if not in_string:
                in_string = True
                result.append(char)
            else:
                next_char = (
                    original_json_str[i + 1] if i + 1 < len(original_json_str) else None
                )
                if result and result[-1] == "\\":
                    result.append(char)
                elif next_char not in [",", ":", "}", "\n"]:
                    result.append("\\" + char)
                else:
                    result.append(char)
                    in_string = False
        else:
            result.append(char)
    return "".join(result)


_BRACE_RE = re.compile(r"[{}]")
_WHITESPACE_RE = re.compile(r"\s*")
_CODE_FENCE = "```"
# Each top-level brace span may decode candidates totalling this multiple of
# its own length. Deep nesting stays linear, and one deep object cannot use up
# the work that later, separate objects need.
_JSON_DECODE_BUDGET_PER_CHAR = 16


def _balanced_brace_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of balanced braces, ordered by start, in one pass."""
    spans: list[tuple[int, int]] = []
    open_positions: list[int] = []
    for match in _BRACE_RE.finditer(text):
        if match.group() == "{":
            open_positions.append(match.start())
        elif open_positions:
            spans.append((open_positions.pop(), match.end()))
    spans.sort()
    return spans


def find_all_json_objects(text: str) -> list[dict]:
    """Find all JSON objects in text using balanced brace matching.

    Each balanced '{...}' substring (counting braces only) is validated as JSON.
    This includes nested JSON objects within other objects. Runs in time linear
    in the text length.

    Use case: Parsing LLM output that may contain multiple JSON objects, or when
    the LLM/serving layer outputs function calls in non-standard formats
    (e.g. OpenAI's function.open_url style).

    Args:
        text: The text to search for JSON objects.

    Returns:
        A list of all successfully parsed JSON objects (dicts only).
    """
    json_objects: list[dict] = []
    group_end = -1
    budget = 0

    for start, end in _balanced_brace_spans(text):
        if start >= group_end:
            # A new top-level span: it always gets a decode.
            group_end = end
            budget = _JSON_DECODE_BUDGET_PER_CHAR * (end - start)
        elif budget <= 0:
            continue
        # A candidate costs its length: the slice copy plus a decode (and any
        # error position lookup) bounded by the slice.
        budget -= end - start
        try:
            parsed = json.loads(text[start:end])
        except (json.JSONDecodeError, RecursionError):
            continue
        if isinstance(parsed, dict):
            json_objects.append(parsed)

    return json_objects


def _find_fenced_json_span(content: str) -> tuple[int, int] | None:
    """Find the span matched by ```(?:json)?\\s*(\\{.*\\})\\s*``` (DOTALL) in linear time."""
    brace_start = -1
    fence = content.find(_CODE_FENCE)
    while fence != -1:
        pos = fence + len(_CODE_FENCE)
        if content.startswith("json", pos):
            after_json = _WHITESPACE_RE.match(content, pos + 4)
            if after_json and content.startswith("{", after_json.end()):
                brace_start = after_json.end()
                break
        after_fence = _WHITESPACE_RE.match(content, pos)
        if after_fence and content.startswith("{", after_fence.end()):
            brace_start = after_fence.end()
            break
        fence = content.find(_CODE_FENCE, fence + 1)
    if brace_start == -1:
        return None

    # Greedy: the last closing fence that follows a '}' after the opening brace.
    closing = content.rfind(_CODE_FENCE)
    while closing > brace_start:
        brace_end = closing - 1
        while brace_end > brace_start and content[brace_end].isspace():
            brace_end -= 1
        if brace_end > brace_start and content[brace_end] == "}":
            return brace_start, brace_end + 1
        closing = content.rfind(_CODE_FENCE, 0, closing + len(_CODE_FENCE) - 1)
    return None


def _loads_dict(candidate: str) -> dict | None:
    try:
        result = json.loads(candidate)
    except (json.JSONDecodeError, RecursionError):
        return None
    return result if isinstance(result, dict) else None


def parse_llm_json_response(content: str) -> dict | None:
    """Parse a single JSON object from LLM output, handling markdown code blocks.

    Designed for LLM responses that typically contain exactly one JSON object,
    possibly wrapped in markdown formatting. Runs in time linear in the content
    length.

    Tries extraction in order:
    1. JSON inside markdown code block (```json ... ``` or ``` ... ```)
    2. Entire content as raw JSON
    3. First '{' to last '}' in content (greedy match)

    Args:
        content: The LLM response text to parse.

    Returns:
        The parsed JSON dict if found, None otherwise.
    """
    fenced_span = _find_fenced_json_span(content)
    if fenced_span:
        result = _loads_dict(content[fenced_span[0] : fenced_span[1]])
        if result is not None:
            return result

    result = _loads_dict(content)
    if result is not None:
        return result

    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return _loads_dict(content[first_brace : last_brace + 1])

    return None


def parse_bracketed_list(content: str | None) -> list[str] | None:
    """Parse a bracketed comma-separated list from LLM output, e.g.
    `[zendesk, asana]` or `["a", "b"]` -> `["zendesk", "asana"]`.

    Tolerates stray text around the list and quoted or unquoted items, and uses
    the last `[...]` when several are present. Returns the items (empty list for
    `[]`), or None when no bracketed list is found.
    """
    if not content:
        return None
    matches = re.findall(r"\[([^\[\]]*)\]", content)
    if not matches:
        return None
    items = (item.strip().strip("\"'") for item in matches[-1].split(","))
    return [item for item in items if item]


def clean_model_quote(quote: str, trim_length: int) -> str:
    quote_clean = quote.strip()
    if quote_clean[0] == '"':
        quote_clean = quote_clean[1:]
    if quote_clean[-1] == '"':
        quote_clean = quote_clean[:-1]
    if trim_length > 0:
        quote_clean = quote_clean[:trim_length]
    return quote_clean


def shared_precompare_cleanup(text: str) -> str:
    """LLMs models sometime restructure whitespaces or edits special characters to fit a more likely
    distribution of characters found in its training data, but this hurts exact quote matching
    """
    text = text.lower()

    # \s: matches any whitespace character (spaces, tabs, newlines, etc.)
    # |: acts as an OR.
    # \*: matches the asterisk character.
    # \\": matches the \" sequence.
    # [.,:`"#-]: matches any character inside the square brackets.
    text = re.sub(r'\s|\*|\\"|[.,:`"#-]', "", text)

    return text


def clean_text(text: str) -> str:
    # Remove specific Unicode ranges that might cause issues
    cleaned = _INITIAL_FILTER.sub("", text)

    # Remove any control characters except for newline and tab
    cleaned = "".join(ch for ch in cleaned if ch >= " " or ch in "\n\t")

    return cleaned


def is_valid_email(text: str) -> bool:
    """Can use a library instead if more detailed checks are needed"""
    regex = r"^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if re.match(regex, text):
        return True
    else:
        return False


def count_punctuation(text: str) -> int:
    return sum(1 for char in text if char in string.punctuation)


def remove_markdown_image_references(text: str) -> str:
    """Remove markdown-style image references like ![alt text](url)"""
    return re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", text)


def remove_invalid_unicode_chars(text: str) -> str:
    """Remove Unicode characters that are invalid in UTF-8 or cause encoding issues.

    This handles:
    - Control characters (except tab, newline, carriage return)
    - Unpaired UTF-16 surrogates (e.g. U+DC00) that cause 'surrogates not allowed' errors
    - Unicode non-characters
    """
    return _INVALID_UNICODE_CHARS_RE.sub("", text)


def normalize_char(c: str) -> str:
    """Normalize a single character (curly quotes, whitespace, punctuation)."""
    if c in CURLY_TO_STRAIGHT_QUOTES:
        c = CURLY_TO_STRAIGHT_QUOTES[c]
    if c.isspace():
        return " "
    elif re.match(r"[^\w\s\']", c):
        return " "
    else:
        return c.lower()
