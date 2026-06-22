import re

# [label](url) -> label
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# Leading header hashes at the start of a line. Line-anchored so inline text such
# as "C#" or "#1" is left untouched.
_MD_HEADER = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]*")
# Inline code / code-fence backticks.
_MD_CODE = re.compile(r"`{1,3}")
# Runs of whitespace (including newlines).
_WS = re.compile(r"\s+")


def strip_markdown_for_tts(text: str) -> str:
    """Remove common markdown markers so TTS does not read them aloud.

    Mirrors the frontend ``stripMarkdownForTTS`` and is applied server-side as a
    version-independent safety net: the web bundle may lag the backend, and not
    every TTS entry point strips on the client.

    Removes bold/italic markers, inline-code and code-fence backticks, and leading
    header hashes (line-anchored to avoid mangling text like ``C#`` or ``#1``),
    and converts ``[label](url)`` to ``label``. Whitespace runs are collapsed so
    the synthesized speech does not contain odd pauses.
    """
    text = text.replace("**", "").replace("__", "")
    text = text.replace("*", "").replace("_", "")
    text = _MD_CODE.sub("", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _WS.sub(" ", text)
    return text.strip()
