import codecs
import json
import re
import string
from urllib.parse import quote

from onyx.utils.logger import setup_logger


logger = setup_logger(__name__)

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
    "\U00002000-\U0000206f"  # General Punctuation
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


def find_all_json_objects(text: str) -> list[dict]:
    """Find all JSON objects in text using balanced brace matching.

    Iterates through the text, and for each '{' found, attempts to find its
    matching '}' by counting brace depth. Each balanced substring is then
    validated as JSON. This includes nested JSON objects within other objects.

    Use case: Parsing LLM output that may contain multiple JSON objects, or when
    the LLM/serving layer outputs function calls in non-standard formats
    (e.g. OpenAI's function.open_url style).

    Args:
        text: The text to search for JSON objects.

    Returns:
        A list of all successfully parsed JSON objects (dicts only).
    """
    json_objects: list[dict] = []
    i = 0

    while i < len(text):
        if text[i] == "{":
            # Try to find a matching closing brace
            brace_count = 0
            start = i
            for j in range(i, len(text)):
                if text[j] == "{":
                    brace_count += 1
                elif text[j] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        # Found potential JSON object
                        candidate = text[start : j + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict):
                                json_objects.append(parsed)
                        except json.JSONDecodeError:
                            pass
                        break
        i += 1

    return json_objects


def parse_llm_json_response(content: str) -> dict | None:
    """Parse a single JSON object from LLM output, handling markdown code blocks.

    Designed for LLM responses that typically contain exactly one JSON object,
    possibly wrapped in markdown formatting.

    Tries extraction in order:
    1. JSON inside markdown code block (```json ... ``` or ``` ... ```)
    2. Entire content as raw JSON
    3. First '{' to last '}' in content (greedy match)

    Args:
        content: The LLM response text to parse.

    Returns:
        The parsed JSON dict if found, None otherwise.
    """
    # Try to find JSON in markdown code block first
    # Use greedy .* (not .*?) to match nested objects correctly within code block bounds
    json_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Try to parse the entire content as JSON
    try:
        result = json.loads(content)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try to find any JSON object in the content
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


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
    - Unpaired UTF-16 surrogates (e.g. \udc00) that cause 'surrogates not allowed' errors
    - Unicode non-characters
    """
    return _INVALID_UNICODE_CHARS_RE.sub("", text)
