import io

from PIL import Image


def create_test_image(
    width: int = 1,
    height: int = 1,
    color: str = "white",
    format: str = "PNG",
) -> io.BytesIO:
    """Create a test image file in memory for file attachment testing.

    Args:
        width: Width of the image in pixels. Defaults to 1.
        height: Height of the image in pixels. Defaults to 1.
        color: Color of the image. Defaults to "white".
        format: Image format (PNG, JPEG, etc.). Defaults to "PNG".

    Returns:
        A BytesIO object containing the image data, positioned at the start.
    """
    image = Image.new("RGB", (width, height), color=color)
    image_file = io.BytesIO()
    image.save(image_file, format=format)
    image_file.seek(0)
    return image_file


def create_test_pdf(text: str = "Hello from the test PDF") -> io.BytesIO:
    """Create a minimal single-page PDF whose text `pypdf` can extract.

    Hand-assembled rather than generated with a PDF library so the fixture stays
    a few hundred bytes and pulls in no extra dependency. `text` must be plain
    ASCII without parentheses or backslashes, which would need escaping inside
    the content stream.

    Returns:
        A BytesIO object containing the PDF, positioned at the start.
    """
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")

    return io.BytesIO(bytes(out))


def create_test_text_file(content: str | bytes) -> io.BytesIO:
    """Create a test text file in memory for file attachment testing.

    Args:
        content: The text content of the file. Can be string or bytes.

    Returns:
        A BytesIO object containing the text data, positioned at the start.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    text_file = io.BytesIO(content)
    text_file.seek(0)
    return text_file
