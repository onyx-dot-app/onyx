"""Regenerates the image-bearing PDF fixtures in this directory.

Run from this directory: ``uv run python generate_image_fixtures.py``

The fixtures exercise the embedded-image enumeration and filtering rules in
``onyx.file_processing.pdf_image_utils``:

- with_image.pdf          one content image (32x32)
- shredded_strips.pdf     one content image + 1px scanline strips (producer
                          artifact: figures shredded into thousands of strips)
- stencil_mask.pdf        one content image that uses an /ImageMask stencil
                          as its /Mask
- standalone_stencil.pdf  one painted /ImageMask stencil referenced by no
                          other image (content, e.g. a scanned signature)
- late_mask_reference.pdf a stencil on page 1 whose referencing image only
                          appears on page 2 (mask must still be excluded)
- shared_resources.pdf    three pages sharing one resource dict, plus a
                          nested Form XObject referencing the same image
- inline_image.pdf        one content-sized inline (BI/ID/EI) image + one
                          tiny inline image
"""

import zlib
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
)

HERE = Path(__file__).parent

CONTENT_PX = 32  # comfortably above MIN_EMBEDDED_IMAGE_DIMENSION_PX
STRIP_W, STRIP_H = 100, 1


def _base_image_stream(width: int, height: int) -> StreamObject:
    stream = StreamObject()
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Image")
    stream[NameObject("/Width")] = NumberObject(width)
    stream[NameObject("/Height")] = NumberObject(height)
    stream[NameObject("/Filter")] = NameObject("/FlateDecode")
    return stream


def _rgb_image_stream(
    width: int, height: int, color: tuple[int, int, int]
) -> StreamObject:
    stream = _base_image_stream(width, height)
    stream[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    stream[NameObject("/BitsPerComponent")] = NumberObject(8)
    stream._data = zlib.compress(bytes(color) * (width * height))
    return stream


def _stencil_mask_stream(width: int, height: int) -> StreamObject:
    stream = _base_image_stream(width, height)
    stream[NameObject("/ImageMask")] = BooleanObject(True)
    stream[NameObject("/BitsPerComponent")] = NumberObject(1)
    row_bytes = (width + 7) // 8
    stream._data = zlib.compress(b"\x00" * (row_bytes * height))
    return stream


def _attach_images(
    writer: PdfWriter, page: DictionaryObject, images: dict[str, IndirectObject]
) -> None:
    xobjects = DictionaryObject()
    for name, ref in images.items():
        xobjects[NameObject(name)] = ref
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = writer._add_object(resources)


def _single_page_pdf(path: Path, images: dict[str, StreamObject]) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    _attach_images(
        writer, page, {name: writer._add_object(img) for name, img in images.items()}
    )
    writer.write(path)


def make_with_image(out_dir: Path) -> None:
    _single_page_pdf(
        out_dir / "with_image.pdf",
        {"/Img1": _rgb_image_stream(CONTENT_PX, CONTENT_PX, (200, 30, 30))},
    )


def make_shredded_strips(out_dir: Path) -> None:
    images = {"/Img1": _rgb_image_stream(CONTENT_PX, CONTENT_PX, (30, 200, 30))}
    for i in range(30):
        images[f"/Strip{i}"] = _rgb_image_stream(STRIP_W, STRIP_H, (i * 8 % 256, 0, 0))
    _single_page_pdf(out_dir / "shredded_strips.pdf", images)


def make_stencil_mask(out_dir: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    mask = writer._add_object(_stencil_mask_stream(CONTENT_PX, CONTENT_PX))
    image = _rgb_image_stream(CONTENT_PX, CONTENT_PX, (30, 30, 200))
    image[NameObject("/Mask")] = mask
    _attach_images(writer, page, {"/Img1": writer._add_object(image), "/Mask1": mask})
    writer.write(out_dir / "stencil_mask.pdf")


def make_standalone_stencil(out_dir: Path) -> None:
    _single_page_pdf(
        out_dir / "standalone_stencil.pdf",
        {"/Stencil1": _stencil_mask_stream(CONTENT_PX, CONTENT_PX)},
    )


def make_late_mask_reference(out_dir: Path) -> None:
    writer = PdfWriter()
    page1 = writer.add_blank_page(width=200, height=200)
    page2 = writer.add_blank_page(width=200, height=200)
    mask = writer._add_object(_stencil_mask_stream(CONTENT_PX, CONTENT_PX))
    image = _rgb_image_stream(CONTENT_PX, CONTENT_PX, (200, 30, 200))
    image[NameObject("/Mask")] = mask
    _attach_images(writer, page1, {"/Mask1": mask})
    _attach_images(writer, page2, {"/Img1": writer._add_object(image)})
    writer.write(out_dir / "late_mask_reference.pdf")


def make_shared_resources(out_dir: Path) -> None:
    writer = PdfWriter()
    pages = [writer.add_blank_page(width=200, height=200) for _ in range(3)]
    img = writer._add_object(_rgb_image_stream(CONTENT_PX, CONTENT_PX, (200, 200, 30)))

    form_xobjects = DictionaryObject()
    form_xobjects[NameObject("/Im1")] = img
    form_resources = DictionaryObject()
    form_resources[NameObject("/XObject")] = form_xobjects
    form = StreamObject()
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/BBox")] = ArrayObject(
        [NumberObject(0), NumberObject(0), NumberObject(1), NumberObject(1)]
    )
    form[NameObject("/Resources")] = form_resources
    form._data = b""
    form_ref = writer._add_object(form)

    shared_xobjects = DictionaryObject()
    shared_xobjects[NameObject("/Im1")] = img
    shared_xobjects[NameObject("/Fm1")] = form_ref
    shared_resources = DictionaryObject()
    shared_resources[NameObject("/XObject")] = shared_xobjects
    shared_ref = writer._add_object(shared_resources)
    for page in pages:
        page[NameObject("/Resources")] = shared_ref

    writer.write(out_dir / "shared_resources.pdf")


def make_inline_image(out_dir: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)

    def inline_op(width: int, height: int) -> bytes:
        pixels = bytes((250, 100, 0)) * (width * height)
        return (
            f"BI /W {width} /H {height} /CS /RGB /BPC 8 ID ".encode() + pixels + b" EI"
        )

    content = (
        b"q " + inline_op(CONTENT_PX, CONTENT_PX) + b" Q q " + inline_op(4, 4) + b" Q"
    )
    contents = StreamObject()
    contents._data = content
    page[NameObject("/Contents")] = writer._add_object(contents)
    writer.write(out_dir / "inline_image.pdf")


def generate_all(out_dir: Path) -> None:
    make_with_image(out_dir)
    make_shredded_strips(out_dir)
    make_stencil_mask(out_dir)
    make_standalone_stencil(out_dir)
    make_late_mask_reference(out_dir)
    make_shared_resources(out_dir)
    make_inline_image(out_dir)


if __name__ == "__main__":
    generate_all(HERE)
    print("fixtures regenerated")
