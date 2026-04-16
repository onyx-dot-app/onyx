from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import count_tokens


def pack_lines(
    lines: list[str],
    prefix: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[str]:
    """Greedily pack ``lines`` into chunks ≤ ``max_tokens``, prepending
    ``prefix`` (verbatim) to every emitted chunk. Lines whose own token
    count exceeds the post-prefix budget are skipped. Callers assemble
    the full prefix (heading, header text, etc.) before calling.
    """
    prefix_tokens = count_tokens(prefix, tokenizer) + 1 if prefix else 0
    budget = max_tokens - prefix_tokens

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for line in lines:
        line_tokens = count_tokens(line, tokenizer)
        if line_tokens > budget:
            continue
        sep = 1 if current else 0
        if current_tokens + sep + line_tokens > budget:
            chunks.append(_join_with_prefix(current, prefix))
            current = [line]
            current_tokens = line_tokens
        else:
            current.append(line)
            current_tokens += sep + line_tokens
    if current:
        chunks.append(_join_with_prefix(current, prefix))
    return chunks


def _join_with_prefix(lines: list[str], prefix: str) -> str:
    body = "\n".join(lines)
    return f"{prefix}\n{body}" if prefix else body
