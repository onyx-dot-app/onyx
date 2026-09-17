import re
from typing import Any

from bs4 import BeautifulSoup

# Keys whose values hold renderable widget text inside a LumApps content template.
_CONTENT_KEYS = {"html", "content", "longText", "text", "body", "value"}

# A language-code key in a LumApps localized value: "en", "fr", "en-US", "pt_BR".
_LANG_CODE_RE = re.compile(r"^[a-z]{2}(?:[-_][A-Za-z]{2,4})?$")


def slugify_family_key(name: str, fallback: str = "metadata") -> str:
    """Turn a metadata family display name into a stable Onyx metadata key.

    e.g. "News type" -> "news_type", "Country" -> "country". Names with no
    ASCII alphanumerics (e.g. non-Latin family names) slugify to nothing and
    return ``fallback`` instead — callers pass a per-family fallback so
    distinct families don't collapse into one key.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return cleaned or fallback


def pick_lang(value: Any, preferred_lang: str, fallback_lang: str = "en") -> str:
    """Pick a string from a LumApps language-keyed dict (e.g. {"en": "...", "fr": "..."}).

    Falls back to the preferred language, then English, then any non-empty value.
    Plain strings are returned as-is.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, dict) or not value:
        return ""
    for lang in (preferred_lang, fallback_lang):
        if value.get(lang):
            return str(value[lang])
    for candidate in value.values():
        if candidate:
            return str(candidate)
    return ""


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    if "<" in html and ">" in html:
        return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
    return html.strip()


def _is_lang_dict(node: dict) -> bool:
    # A LumApps localized value: language-code keys (en, fr, en-US) -> string values.
    return bool(node) and all(
        isinstance(k, str) and _LANG_CODE_RE.match(k) and isinstance(v, str)
        for k, v in node.items()
    )


def extract_body_text(
    template: Any, preferred_lang: str, fallback_lang: str = "en"
) -> str:
    """Best-effort extraction of human-readable body text from a LumApps template.

    LumApps stores the body inside a structured template (components -> cells ->
    widgets; rich-text/HTML widgets keep their text under ``properties`` in
    content-ish, often language-keyed, fields). The exact widget schema varies, so we
    walk the whole structure, harvest text only from content-ish keys, convert HTML to
    text, de-duplicate, and join.
    """
    chunks: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        text = _html_to_text(raw)
        if text and text not in seen:
            seen.add(text)
            chunks.append(text)

    def walk(node: Any, under_content_key: bool) -> None:
        if isinstance(node, str):
            if under_content_key:
                add(node)
        elif isinstance(node, dict):
            if _is_lang_dict(node):
                if under_content_key:
                    add(pick_lang(node, preferred_lang, fallback_lang))
                return
            for key, value in node.items():
                walk(value, under_content_key or key in _CONTENT_KEYS)
        elif isinstance(node, list):
            for item in node:
                walk(item, under_content_key)

    walk(template, False)
    return "\n\n".join(chunks).strip()


def resolve_metadata_labels(
    metadata_ids: list[str], label_map: dict[str, tuple[str, str]]
) -> dict[str, list[str]]:
    """Group resolved metadata values by family for ``Document.metadata``.

    ``label_map`` maps a metadata value id -> ``(family_key, value_label)``. Returns
    ``{family_key: [value labels...]}`` carrying **all** labels generically (no
    country special-casing). Ids missing from ``label_map`` are skipped (the caller
    logs them).
    """
    grouped: dict[str, list[str]] = {}
    for metadata_id in metadata_ids or []:
        entry = label_map.get(str(metadata_id))
        if not entry:
            continue
        family_key, value_label = entry
        if not family_key or not value_label:
            continue
        values = grouped.setdefault(family_key, [])
        if value_label not in values:
            values.append(value_label)
    return grouped
