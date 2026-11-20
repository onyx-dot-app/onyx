"""File bytes and site page text, made from a seed.

The text is random words. A file renders to the same bytes each time, until
its version changes.
"""

import hashlib
import io
import random
from functools import lru_cache

from pydantic import BaseModel

_WORDS = (
    "the of and to in is for on that with as by this from at be are it an or "
    "team project customer data report plan quarter revenue product launch "
    "design review meeting notes action item owner deadline budget forecast "
    "risk issue metric goal target market sales support engineering release "
    "feature roadmap priority status update summary decision approval policy "
    "security access account invoice contract partner vendor process workflow "
    "system service platform integration migration database pipeline index "
    "search query result document file folder library site page permission "
    "group admin tenant workspace onboarding training hiring interview offer"
).split()


class DocSection(BaseModel):
    heading: str
    paragraphs: list[str]


class DocBody(BaseModel):
    title: str
    sections: list[DocSection]


def _rng_for(seed: int, key: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:content:{key}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _sentence(rng: random.Random) -> str:
    words = rng.choices(_WORDS, k=rng.randint(8, 16))
    return " ".join(words).capitalize() + "."


def _paragraph(rng: random.Random) -> str:
    return " ".join(_sentence(rng) for _ in range(rng.randint(2, 6)))


def build_body(seed: int, key: str, title: str, content_bytes: int) -> DocBody:
    rng = _rng_for(seed, key)
    sections: list[DocSection] = []
    size = len(title)
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
        sections.append(DocSection(heading=heading, paragraphs=paragraphs))
    return DocBody(title=title, sections=sections)


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
    for section in body.sections or [DocSection(heading=body.title, paragraphs=[])]:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = section.heading
        slide.placeholders[1].text = "\n".join(section.paragraphs)
    out = io.BytesIO()
    presentation.save(out)
    return out.getvalue()


@lru_cache(maxsize=256)
def render_file(
    seed: int, item_id: str, version: int, name: str, content_bytes: int
) -> bytes:
    """The bytes of a generated file. An unsupported type gets random bytes."""
    stem, _, extension = name.rpartition(".")
    key = f"{item_id}:{version}"
    body = build_body(seed, key, stem or name, content_bytes)
    extension = extension.lower()
    if extension == "txt":
        return render_text(body).encode()
    if extension == "md":
        return render_markdown(body).encode()
    if extension == "pdf":
        return render_pdf(body)
    if extension == "docx":
        return render_docx(body)
    if extension == "pptx":
        return render_pptx(body)
    return _rng_for(seed, key).randbytes(content_bytes)


def render_text_file(name: str, text: str) -> bytes:
    """The bytes of a file whose text a test set, in the file's format."""
    stem, _, extension = name.rpartition(".")
    extension = extension.lower()
    body = DocBody(
        title=stem or name, sections=[DocSection(heading="", paragraphs=[text])]
    )
    if extension == "pdf":
        return render_pdf(body)
    if extension == "docx":
        return render_docx(body)
    if extension == "pptx":
        return render_pptx(body)
    return text.encode()


def page_paragraphs(seed: int, page_id: str, count: int) -> list[str]:
    rng = _rng_for(seed, f"page:{page_id}")
    return [_paragraph(rng) for _ in range(count)]
