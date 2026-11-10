"""File content, rendered from the file id so that it never changes.

Each file has a title and sections of a heading and paragraphs. The renderers
turn that body into the format a download or an export asks for, and into the
document JSON of the Docs API.
"""

import csv
import hashlib
import io
import random
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from .corpus import MockFile
from .settings import (
    DOC_MIME,
    DOCX_MIME,
    MARKDOWN_MIME,
    PDF_MIME,
    PPTX_MIME,
    SHEET_MIME,
    SLIDES_MIME,
    TEXT_MIME,
)

HTML_MIME = "text/html"
CSV_MIME = "text/csv"
TSV_MIME = "text/tab-separated-values"

# What files.export accepts for each Google-native type.
EXPORT_FORMATS: dict[str, frozenset[str]] = {
    DOC_MIME: frozenset({TEXT_MIME, MARKDOWN_MIME, HTML_MIME, PDF_MIME, DOCX_MIME}),
    SHEET_MIME: frozenset({CSV_MIME, TSV_MIME}),
    SLIDES_MIME: frozenset({PPTX_MIME, TEXT_MIME, PDF_MIME}),
}
# Google refuses to export more than this.
EXPORT_SIZE_LIMIT_BYTES = 10 * 1024 * 1024

_WORDS = (
    "the of and to in is for on that with as by this from at be are it an or "
    "team project customer data report plan quarter revenue product launch "
    "design review meeting notes action item owner deadline budget forecast "
    "risk issue metric goal target market sales support engineering release "
    "feature roadmap priority status update summary decision approval policy "
    "security access account invoice contract partner vendor process workflow "
    "system service platform integration migration database pipeline index "
    "search query result document file folder drive share permission user "
    "group admin domain workspace onboarding training hiring interview offer "
    "benefit payroll expense travel office remote schedule calendar event "
    "launch beta feedback survey research analysis insight trend growth churn "
    "retention pricing discount renewal upgrade license compliance audit legal "
    "privacy incident outage postmortem latency throughput capacity scaling"
).split()


class DocSection(BaseModel):
    heading: str
    heading_id: str
    paragraphs: list[str]


class DocBody(BaseModel):
    title: str
    sections: list[DocSection]


def _rng_for(seed: int, file_id: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:content:{file_id}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _sentence(rng: random.Random) -> str:
    words = rng.choices(_WORDS, k=rng.randint(8, 16))
    return " ".join(words).capitalize() + "."


def _paragraph(rng: random.Random) -> str:
    return " ".join(_sentence(rng) for _ in range(rng.randint(2, 6)))


def build_body(seed: int, file_id: str, name: str, content_bytes: int) -> DocBody:
    rng = _rng_for(seed, file_id)
    sections: list[DocSection] = []
    size = len(name)
    while size < content_bytes:
        heading = " ".join(rng.choices(_WORDS, k=rng.randint(2, 5))).title()
        paragraphs: list[str] = []
        for _ in range(rng.randint(1, 4)):
            paragraph = _paragraph(rng)
            paragraphs.append(paragraph)
            size += len(paragraph) + 1
            if size >= content_bytes:
                break
        size += len(heading) + 1
        sections.append(
            DocSection(
                heading=heading,
                heading_id=_heading_id(file_id, len(sections)),
                paragraphs=paragraphs,
            )
        )
    return DocBody(title=name.rsplit(".", 1)[0], sections=sections)


def _heading_id(file_id: str, index: int) -> str:
    return "h." + hashlib.sha1(f"{file_id}:{index}".encode()).hexdigest()[:12]


def render_text(body: DocBody) -> str:
    parts = [body.title, ""]
    for section in body.sections:
        parts.append(section.heading)
        parts.extend(section.paragraphs)
        parts.append("")
    return "\n".join(parts)


def render_markdown(body: DocBody) -> str:
    parts = [f"# {body.title}", ""]
    for section in body.sections:
        parts.extend([f"## {section.heading}", ""])
        for paragraph in section.paragraphs:
            parts.extend([paragraph, ""])
    return "\n".join(parts)


def render_html(body: DocBody) -> str:
    parts = [f"<html><head><title>{body.title}</title></head><body>"]
    parts.append(f"<h1>{body.title}</h1>")
    for section in body.sections:
        parts.append(f'<h2 id="{section.heading_id}">{section.heading}</h2>')
        parts.extend(f"<p>{p}</p>" for p in section.paragraphs)
    parts.append("</body></html>")
    return "".join(parts)


def render_table(seed: int, file_id: str, content_bytes: int, delimiter: str) -> str:
    rng = _rng_for(seed, file_id)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    columns = ["id", "name", "owner", "status", "amount", "notes"]
    writer.writerow(columns)
    row = 0
    while out.tell() < content_bytes:
        row += 1
        writer.writerow(
            [
                row,
                " ".join(rng.choices(_WORDS, k=2)).title(),
                f"user{rng.randint(1, 50)}",
                rng.choice(["open", "done", "blocked", "review"]),
                f"{rng.uniform(10, 10_000):.2f}",
                _sentence(rng),
            ]
        )
    return out.getvalue()


def _pdf_escape(text: str) -> str:
    safe = text.encode("ascii", "replace").decode("ascii")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines or [""]


def render_pdf(body: DocBody) -> bytes:
    """A small valid PDF with the body as Helvetica text, 50 lines a page."""
    lines: list[str] = [body.title, ""]
    for section in body.sections:
        lines.append(section.heading)
        for paragraph in section.paragraphs:
            lines.extend(_wrap(paragraph, 95))
        lines.append("")
    pages = [lines[i : i + 50] for i in range(0, len(lines), 50)] or [[""]]

    objects: list[bytes] = []
    num_pages = len(pages)
    font_obj = 3 + 2 * num_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(num_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {num_pages} >>".encode())
    for i, page_lines in enumerate(pages):
        content_obj = 4 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_obj} 0 R "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
            ).encode()
        )
        text_ops = " T* ".join(f"({_pdf_escape(line)}) Tj" for line in page_lines)
        stream = f"BT /F1 10 Tf 14 TL 40 750 Td {text_ops} ET".encode()
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    return out.getvalue()


def render_docx(body: DocBody) -> bytes:
    import docx

    document = docx.Document()
    document.add_heading(body.title, level=0)
    for section in body.sections:
        document.add_heading(section.heading, level=2)
        for paragraph in section.paragraphs:
            document.add_paragraph(paragraph)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def render_pptx(body: DocBody) -> bytes:
    import pptx

    presentation = pptx.Presentation()
    layout = presentation.slide_layouts[1]
    for section in body.sections or [
        DocSection(heading=body.title, heading_id="", paragraphs=[])
    ]:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = section.heading
        slide.placeholders[1].text = "\n".join(section.paragraphs)
    out = io.BytesIO()
    presentation.save(out)
    return out.getvalue()


def _docs_paragraph(
    text: str, start: int, style: str, heading_id: str | None = None
) -> dict[str, Any]:
    content = f"{text}\n"
    paragraph_style: dict[str, Any] = {
        "namedStyleType": style,
        "direction": "LEFT_TO_RIGHT",
    }
    if heading_id:
        paragraph_style["headingId"] = heading_id
    end = start + len(content)
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {
            "elements": [
                {
                    "startIndex": start,
                    "endIndex": end,
                    "textRun": {"content": content, "textStyle": {}},
                }
            ],
            "paragraphStyle": paragraph_style,
        },
    }


def render_docs_api_document(
    file: MockFile, body: DocBody, include_tabs: bool
) -> dict[str, Any]:
    """The `documents.get` response of the Docs API."""
    content: list[dict[str, Any]] = [
        {
            "endIndex": 1,
            "sectionBreak": {"sectionStyle": {"columnSeparatorStyle": "NONE"}},
        }
    ]
    index = 1
    title = _docs_paragraph(body.title, index, "TITLE", _heading_id(file.id, -1))
    content.append(title)
    index = title["endIndex"]
    for section in body.sections:
        heading = _docs_paragraph(
            section.heading, index, "HEADING_2", section.heading_id
        )
        content.append(heading)
        index = heading["endIndex"]
        for paragraph in section.paragraphs:
            element = _docs_paragraph(paragraph, index, "NORMAL_TEXT")
            content.append(element)
            index = element["endIndex"]
    document: dict[str, Any] = {
        "documentId": file.id,
        "title": file.name,
        "revisionId": hashlib.sha1(
            f"{file.id}:{file.modified_time.isoformat()}".encode()
        ).hexdigest(),
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
    }
    if include_tabs:
        document["tabs"] = [
            {
                "tabProperties": {"tabId": "t.0", "title": "Tab 1", "index": 0},
                "documentTab": {"body": {"content": content}},
            }
        ]
    else:
        document["body"] = {"content": content}
    return document


class RenderedContent(BaseModel):
    data: bytes
    mime_type: str


@lru_cache(maxsize=512)
def _render_cached(
    seed: int,
    file_id: str,
    name: str,
    content_bytes: int,
    mime_type: str,
    utf8_bom: bool,
) -> RenderedContent:
    if mime_type == CSV_MIME:
        table = render_table(seed, file_id, content_bytes, ",")
        return RenderedContent(data=table.encode(), mime_type=CSV_MIME)
    if mime_type == TSV_MIME:
        table = render_table(seed, file_id, content_bytes, "\t")
        return RenderedContent(data=table.encode(), mime_type=TSV_MIME)
    body = build_body(seed, file_id, name, content_bytes)
    if mime_type == TEXT_MIME:
        text = render_text(body)
        # Google adds a byte order mark to the text export of a Doc.
        data = ("\ufeff" + text).encode() if utf8_bom else text.encode()
        return RenderedContent(data=data, mime_type=TEXT_MIME)
    if mime_type == MARKDOWN_MIME:
        data = render_markdown(body).encode()
        return RenderedContent(data=data, mime_type=MARKDOWN_MIME)
    if mime_type == HTML_MIME:
        return RenderedContent(data=render_html(body).encode(), mime_type=HTML_MIME)
    if mime_type == PDF_MIME:
        return RenderedContent(data=render_pdf(body), mime_type=PDF_MIME)
    if mime_type == DOCX_MIME:
        return RenderedContent(data=render_docx(body), mime_type=DOCX_MIME)
    if mime_type == PPTX_MIME:
        return RenderedContent(data=render_pptx(body), mime_type=PPTX_MIME)
    raise ValueError(f"Cannot render {mime_type}")


def render(seed: int, file: MockFile, mime_type: str) -> RenderedContent:
    """The bytes of `file` as `mime_type`: an upload's own type, or an export
    format of a Google-native file."""
    return _render_cached(
        seed,
        file.id,
        file.name,
        file.content_bytes,
        mime_type,
        file.mime_type == DOC_MIME,
    )


def docs_api_document(seed: int, file: MockFile, include_tabs: bool) -> dict[str, Any]:
    body = build_body(seed, file.id, file.name, file.content_bytes)
    return render_docs_api_document(file, body, include_tabs)
