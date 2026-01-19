import re
import unicodedata

from pydantic import BaseModel
from rapidfuzz import fuzz
from rapidfuzz import utils


class SnippetMatchResult(BaseModel):
    snippet_located: bool

    start_idx: int = -1
    end_idx: int = -1


NegativeSnippetMatchResult = SnippetMatchResult(snippet_located=False)


def find_snippet_in_content(content: str, snippet: str) -> SnippetMatchResult:
    """
    Finds where the snippet is located in the content.

    Strategy:
    1. Normalize the snippet & attempt to find it in the content
    2. Perform a token based fuzzy search for the snippet in the content

    Notes:
     - If there are multiple matches of snippet, we choose the first normalised occurrence
    """
    if not snippet or not content:
        return NegativeSnippetMatchResult

    result = _normalize_and_match(content, snippet)
    if result.snippet_located:
        return result

    result = _token_based_match(content, snippet)
    if result.snippet_located:
        return result

    return NegativeSnippetMatchResult


def _normalize_and_match(content: str, snippet: str) -> SnippetMatchResult:
    """
    Normalizes the snippet & content, then performs a direct string match.
    """
    normalized_content, content_map = _normalize_text_with_mapping(content)
    normalized_snippet, url_snippet_map = _normalize_text_with_mapping(snippet)

    if not normalized_content or not normalized_snippet:
        return NegativeSnippetMatchResult

    pos = normalized_content.find(normalized_snippet)
    if pos != -1:
        original_start = content_map[pos]

        # Account for leading characters stripped from snippet during normalization
        # (e.g., leading punctuation like "[![]![]]" that was removed)
        if url_snippet_map:
            first_snippet_orig_pos = url_snippet_map[0]
            if first_snippet_orig_pos > 0:
                # There were leading characters stripped from snippet
                # Extend start position backwards to include them from content
                original_start = max(original_start - first_snippet_orig_pos, 0)

        # Determine end position, including any trailing characters that were
        # normalized away (e.g., punctuation)
        match_end_norm = pos + len(normalized_snippet)
        if match_end_norm >= len(content_map):
            # Match extends to end of normalized content - include all trailing chars
            original_end = len(content) - 1
        else:
            # Match is in the middle - end at character before next normalized char
            original_end = content_map[match_end_norm] - 1

        # Account for trailing characters stripped from snippet during normalization
        # (e.g., trailing punctuation like "\n[" that was removed)
        if url_snippet_map:
            last_snippet_orig_pos = url_snippet_map[-1]
            trailing_stripped = len(snippet) - last_snippet_orig_pos - 1
            if trailing_stripped > 0:
                # Extend end position to include trailing characters from content
                # that correspond to the stripped trailing snippet characters
                original_end = min(original_end + trailing_stripped, len(content) - 1)

        return SnippetMatchResult(
            snippet_located=True,
            start_idx=original_start,
            end_idx=original_end,
        )

    return NegativeSnippetMatchResult


def _normalize_text_with_mapping(text: str) -> tuple[str, list[int]]:
    """
    Text normalization that maintains position mapping.

    Returns:
        tuple: (normalized_text, position_map)
        - position_map[i] gives the original position for normalized position i
    """
    if not text:
        return "", []

    original_text = text

    # Step 1: NFC normalization with position mapping
    nfc_text = unicodedata.normalize("NFC", text)

    # Build mapping from NFC positions to original start positions
    nfc_to_orig: list[int] = []
    orig_idx = 0
    for nfc_char in nfc_text:
        nfc_to_orig.append(orig_idx)
        # Find how many original chars contributed to this NFC char
        for length in range(1, len(original_text) - orig_idx + 1):
            substr = original_text[orig_idx : orig_idx + length]
            if unicodedata.normalize("NFC", substr) == nfc_char:
                orig_idx += length
                break
        else:
            orig_idx += 1  # Fallback

    # Work with NFC text from here
    text = nfc_text

    # Define all transformations upfront
    curly_to_straight = {
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
    }

    zero_width_chars = {
        "\u200b",
        "\u200c",
        "\u200d",
        "\ufeff",
        "\u2060",
    }

    html_entities = {
        "&nbsp;": " ",
        "&#160;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&apos;": "'",
        "&#39;": "'",
        "&#x27;": "'",
        "&ndash;": "-",
        "&mdash;": "-",
        "&hellip;": "...",
        "&#xB0;": "°",
        "&#xBA;": "°",
        "&zwj;": "",
    }

    # Sort entities by length (longest first) for greedy matching
    sorted_entities = sorted(html_entities.keys(), key=len, reverse=True)

    result_chars = []
    result_map = []
    i = 0
    last_was_space = True  # Track to avoid leading spaces

    def normalize_char(c: str) -> str:
        """Normalize a single character (curly quotes, whitespace, punctuation)."""
        if c in curly_to_straight:
            c = curly_to_straight[c]
        if c.isspace():
            return " "
        elif re.match(r"[^\w\s\']", c):
            return " "
        else:
            return c.lower()

    while i < len(text):
        # Convert NFC position to original position
        orig_pos = nfc_to_orig[i] if i < len(nfc_to_orig) else len(original_text) - 1
        char = text[i]
        output = None
        step = 1

        # Check for HTML entities first (greedy match)
        for entity in sorted_entities:
            if text[i : i + len(entity)] == entity:
                output = html_entities[entity]
                step = len(entity)
                break

        # If no entity matched, process single character
        if output is None:
            # Skip zero-width characters
            if char in zero_width_chars:
                i += 1
                continue

            output = normalize_char(char)

        # Add output to result, normalizing each character from entity output
        if output:
            for out_char in output:
                # Normalize entity output the same way as regular chars
                normalized = normalize_char(out_char)

                # Handle whitespace collapsing
                if normalized == " ":
                    if not last_was_space:
                        result_chars.append(" ")
                        result_map.append(orig_pos)
                        last_was_space = True
                else:
                    result_chars.append(normalized)
                    result_map.append(orig_pos)
                    last_was_space = False

        i += step

    # Remove trailing space if present
    if result_chars and result_chars[-1] == " ":
        result_chars.pop()
        result_map.pop()

    return "".join(result_chars), result_map


def _token_based_match(
    content: str,
    snippet: str,
    min_threshold: float = 0.8,
) -> SnippetMatchResult:
    """
    Performs a token based fuzzy search for the snippet in the content.

    min_threshold exists in the range [0, 1]
    """
    # Preprocess content & snippet
    processed_content = utils.default_process(content)
    processed_snippet = utils.default_process(snippet)

    if not processed_content or not processed_snippet:
        return NegativeSnippetMatchResult

    # Determine window size
    snippet_words = processed_snippet.split()
    window_size = len(snippet_words)

    if window_size == 0:
        return NegativeSnippetMatchResult

    content_words = processed_content.split()

    if len(content_words) < window_size:
        return NegativeSnippetMatchResult

    best_score = 0.0
    best_word_pos = -1

    # Sliding window through content words
    stride = (
        1  # max(1, window_size // 4) Optimisation if we need. Reduce speed by quarter.
    )

    for i in range(0, len(content_words) - window_size + 1, stride):
        window = " ".join(content_words[i : i + window_size])

        score = fuzz.ratio(processed_snippet, window)

        if score > best_score:
            best_score = score
            best_word_pos = i

    content_word_positions = _get_word_positions(content, processed_content)

    if best_score >= (min_threshold * 100):
        original_start = content_word_positions[best_word_pos][0]
        original_end = content_word_positions[best_word_pos + window_size - 1][1]

        return SnippetMatchResult(
            snippet_located=True,
            start_idx=original_start,
            end_idx=original_end,
        )

    return NegativeSnippetMatchResult


def _get_word_positions(original: str, processed: str) -> list[tuple[int, int]]:
    """
    Returns a list where index i gives (start, end) char positions
    in the original string for word i in the processed string.
    """
    processed_words = processed.split()
    word_positions: list[tuple[int, int]] = []

    search_start = 0
    for word in processed_words:
        # Find this word in the original (case-insensitive, allowing for punctuation)
        # We search character by character for alphanumeric sequences
        while search_start < len(original):
            # Skip non-alphanumeric chars
            while search_start < len(original) and not original[search_start].isalnum():
                search_start += 1

            if search_start >= len(original):
                break

            # Extract the next "word" from original
            word_start = search_start
            while search_start < len(original) and original[search_start].isalnum():
                search_start += 1
            word_end = search_start

            original_word = original[word_start:word_end].lower()

            # Check if this matches the processed word
            if original_word == word:
                word_positions.append((word_start, word_end))
                break

    return word_positions
