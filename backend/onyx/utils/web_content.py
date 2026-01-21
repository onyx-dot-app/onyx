from __future__ import annotations

import io
from urllib.parse import unquote
from urllib.parse import urlparse

from bs4.dammit import UnicodeDammit

from onyx.file_processing.extract_file_text import read_pdf_file

PDF_MIME_TYPES = (
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "application/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
)


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[-1].strip().strip("\"'")
            return charset or None
    return None


def decode_html_bytes(
    content: bytes,
    content_type: str | None = None,
    fallback_encoding: str | None = None,
) -> str:
    override_encodings: list[str] = []
    charset = _charset_from_content_type(content_type)
    if charset:
        override_encodings.append(charset)
    if fallback_encoding and fallback_encoding not in override_encodings:
        override_encodings.append(fallback_encoding)

    unicode_dammit = UnicodeDammit(
        content, override_encodings=override_encodings or None
    )
    if unicode_dammit.unicode_markup is not None:
        return unicode_dammit.unicode_markup

    encoding = override_encodings[0] if override_encodings else "utf-8"
    return content.decode(encoding, errors="replace")


def is_pdf_mime_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    lowered = content_type.lower()
    return any(pdf_type in lowered for pdf_type in PDF_MIME_TYPES)


def is_pdf_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.path.lower().endswith(".pdf")


def has_pdf_signature(content_sniff: bytes | None) -> bool:
    if not content_sniff:
        return False
    return content_sniff.lstrip().startswith(b"%PDF-")


def is_pdf_resource(
    url: str,
    content_type: str | None = None,
    content_sniff: bytes | None = None,
) -> bool:
    return (
        is_pdf_mime_type(content_type)
        or is_pdf_url(url)
        or has_pdf_signature(content_sniff)
    )


def extract_pdf_text(content: bytes) -> tuple[str, dict[str, str | list[str]]]:
    text_content, metadata, _ = read_pdf_file(io.BytesIO(content))
    return text_content or "", normalize_metadata(metadata)


def title_from_pdf_metadata(metadata: dict[str, str | list[str]]) -> str:
    if not metadata:
        return ""
    for key in ("Title", "title"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            items = [item.strip() for item in value if isinstance(item, str)]
            if items:
                return ", ".join(items)
    return ""


def normalize_metadata(metadata: dict[str, object]) -> dict[str, str | list[str]]:
    sanitized: dict[str, str | list[str]] = {}
    for key, value in metadata.items():
        if isinstance(value, str):
            if value.strip():
                sanitized[key] = value
            continue
        if isinstance(value, list):
            items = [item.strip() for item in value if isinstance(item, str)]
            if items:
                sanitized[key] = items
            continue
        if value is not None:
            sanitized[key] = str(value)
    return sanitized


def title_from_url(url: str) -> str:
    parsed = urlparse(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    if not filename:
        return ""
    return unquote(filename)
