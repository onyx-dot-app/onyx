import codecs
import json
import re
import string
from typing import Any
from urllib.parse import quote

from langchain.text_splitter import RecursiveCharacterTextSplitter


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


def decode_escapes(s: str) -> str:
    def decode_match(match: re.Match) -> str:
        matched_str = match.group(0)

        # Only double escape non-Unicode sequences
        if matched_str.startswith("\\U") and not re.match(
            r"\\U[0-9a-fA-F]{8}", matched_str
        ):
            return matched_str

        try:
            return codecs.decode(matched_str, "unicode-escape")
        except UnicodeDecodeError:
            return matched_str

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


def extract_embedded_json(s: str) -> dict:
    first_brace_index = s.find("{")
    last_brace_index = s.rfind("}")

    if first_brace_index == -1 or last_brace_index == -1:
        raise ValueError("No valid json found")

    return json.loads(s[first_brace_index : last_brace_index + 1], strict=False)


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


def is_valid_email(text: str) -> bool:
    """Can use a library instead if more detailed checks are needed"""
    regex = r"^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if re.match(regex, text):
        return True
    else:
        return False


def count_punctuation(text: str) -> int:
    return sum(1 for char in text if char in string.punctuation)


def chunk_text(
    text: str,
    chunk_size: int,
    tokenizer: Any,
    overlap: int = 200,
) -> list[str]:
    """Split text into chunks of approximately equal token count.

    Args:
        text: The text to split into chunks
        chunk_size: Maximum number of tokens per chunk
        tokenizer: A tokenizer that has a encode method returning token IDs
        overlap: Number of tokens to overlap between chunks

    Returns:
        List of text chunks
    """

    # A length function that uses the tokenizer
    def length_function(text: str) -> int:
        return len(tokenizer.encode(text))

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=length_function,
        separators=["\n\n", "\n", " ", ""],
        is_separator_regex=False,
    )

    return text_splitter.split_text(text)
