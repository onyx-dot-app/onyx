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


def extract_embedded_json(s: str) -> dict:
    """Extract a single JSON object from text by finding first '{' to last '}'.

    Use this when you expect exactly ONE JSON object in the text, possibly surrounded
    by other content. Falls back to quote escaping if initial parse fails.

    Note: This will fail or produce incorrect results if the text contains multiple
    JSON objects. For that case, use find_json_objects_in_text() instead.

    Returns:
        The parsed JSON object as a dict, or a default dict if no JSON found.
    """
    first_brace_index = s.find("{")
    last_brace_index = s.rfind("}")

    if first_brace_index == -1 or last_brace_index == -1:
        logger.warning("No valid json found, assuming answer is entire string")
        return {"answer": s, "quotes": []}

    json_str = s[first_brace_index : last_brace_index + 1]
    try:
        return json.loads(json_str, strict=False)

    except json.JSONDecodeError:
        try:
            return json.loads(escape_quotes(json_str), strict=False)
        except json.JSONDecodeError as e:
            raise ValueError("Failed to parse JSON, even after escaping quotes") from e


def find_json_objects_in_text(text: str) -> list[dict]:
    """Find ALL JSON objects in a text string using balanced brace matching.

    Use this when the text may contain multiple JSON objects, or when the simple
    first-to-last brace approach of extract_embedded_json() would fail.

    This function iterates through the text, and for each '{' found, attempts to
    find its matching '}' by counting brace depth. Each balanced substring is
    then validated as JSON.

    Note: This looks for nested json objects in other json objects as well.
    This is needed for some LLMs which may output function calls in another format
    which is typically captured and processed by the serving layer. In this case, the
    LLM or serving layer has failed so it may not match the outer json exactly for the
    function calls. E.g. For OpenAI, the calls look like function.open_url.

    Note: This is more robust but slower than extract_embedded_json(). Use
    extract_embedded_json() if you know there's exactly one JSON object.

    Returns:
        A list of successfully parsed JSON objects (dicts only).
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


def clean_up_code_blocks(model_out_raw: str) -> str:
    return model_out_raw.strip().strip("```").strip().replace("\\xa0", "")


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
