import re

# [label](url) -> label. The url may contain one level of balanced parens
# (e.g. Wikipedia "..._(programming_language)" links).
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)")
# Paired emphasis markers only, so literal "*" and intraword underscores
# (snake_case) survive. Delimiters must hug non-whitespace (CommonMark flanking),
# and underscore variants additionally require non-word boundaries.
_MD_BOLD_STAR = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_MD_ITALIC_STAR = re.compile(r"\*(?=\S)(.+?)(?<=\S)\*")
_MD_BOLD_UNDERSCORE = re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_MD_ITALIC_UNDERSCORE = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
# Inline-code / code-fence backticks.
_MD_CODE = re.compile(r"`{1,3}")
# Leading header hashes at the start of a line. Line-anchored so inline text
# such as "C#" or "#1" is left untouched.
_MD_HEADER = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]*")
# Runs of whitespace (including newlines).
_WS = re.compile(r"\s+")


def strip_markdown_for_tts(text: str) -> str:
    """Remove common markdown markers so TTS does not read them aloud.

    Mirrors the frontend ``stripMarkdownForTTS`` and is applied server-side as a
    version-independent safety net: the web bundle may lag the backend, and not
    every TTS entry point strips on the client.

    Only paired emphasis delimiters are removed, so literal ``*`` and intraword
    underscores (``snake_case``) survive. Also drops code/code-fence backticks
    and leading header hashes (line-anchored to spare ``C#``/``#1``), and converts
    ``[label](url)`` to ``label``. Whitespace runs are collapsed so the
    synthesized speech does not contain odd pauses.
    """
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_BOLD_STAR.sub(r"\1", text)
    text = _MD_ITALIC_STAR.sub(r"\1", text)
    text = _MD_BOLD_UNDERSCORE.sub(r"\1", text)
    text = _MD_ITALIC_UNDERSCORE.sub(r"\1", text)
    text = _MD_CODE.sub("", text)
    text = _MD_HEADER.sub("", text)
    text = _WS.sub(" ", text)
    return text.strip()
