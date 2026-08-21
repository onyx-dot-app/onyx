"""Enumeration and filtering of embedded images in PDFs.

Upload-time validation (count) and indexing-time extraction share one
enumerator and filter chain, so they can never disagree. Enumeration reads
only metadata; pixel data is decoded solely for extracted images.
"""

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterator
from typing import IO, Any

from pydantic import BaseModel

from onyx.configs.app_configs import MIN_EMBEDDED_IMAGE_DIMENSION_PX
from onyx.utils.logger import setup_logger

logger = setup_logger()


class PdfImageRef(BaseModel):
    """Metadata for one embedded image; nothing is decoded to build it.

    ``locator`` is the pypdf image id: pass it to
    ``reader.pages[page_index].images[locator]`` to decode just this image.
    """

    locator: str | list[str]
    page_index: int
    width: int
    height: int
    # True when another image uses this one as its /Mask or /SMask. A
    # standalone painted stencil (signature, line art) is content and stays
    # False.
    is_transparency_mask: bool


class PdfImageFilter(ABC):
    """Decides whether an enumerated image is content or an artifact."""

    @abstractmethod
    def exclude_reason(self, ref: PdfImageRef) -> str | None:
        """Return why the image should be skipped, or None to keep it."""


class TransparencyMaskFilter(PdfImageFilter):
    """Skips masks another image paints through; they are not content."""

    def exclude_reason(self, ref: PdfImageRef) -> str | None:
        return "transparency mask" if ref.is_transparency_mask else None


class MinDimensionFilter(PdfImageFilter):
    """Skips images under ``min_px`` in either dimension: scanline strips,
    spacers, and gradient tiles, which carry no readable content."""

    def __init__(self, min_px: int) -> None:
        self.min_px = min_px
        self._reason = f"under {min_px}px in one dimension"

    def exclude_reason(self, ref: PdfImageRef) -> str | None:
        return self._reason if min(ref.width, ref.height) < self.min_px else None


_DEFAULT_FILTERS: tuple[PdfImageFilter, ...] = (
    TransparencyMaskFilter(),
    MinDimensionFilter(MIN_EMBEDDED_IMAGE_DIMENSION_PX),
)


def _first_exclude_reason(ref: PdfImageRef) -> str | None:
    for f in _DEFAULT_FILTERS:
        reason = f.exclude_reason(ref)
        if reason is not None:
            return reason
    return None


def _resolve(value: Any) -> Any:
    """Follow an indirect reference if given one; pass plain values through."""
    try:
        return value.get_object()
    except AttributeError:
        return value


def _to_int(value: Any) -> int:
    try:
        return int(_resolve(value))
    except (TypeError, ValueError):
        return 0


def _first_visit(obj: Any, seen: set[Any]) -> bool:
    """True on the first sighting of ``obj``'s indirect reference. Direct
    objects have no reference and are always treated as new."""
    ref = getattr(obj, "indirect_reference", None)
    if ref is None:
        return True
    if ref in seen:
        return False
    seen.add(ref)
    return True


def _iter_xobject_entries(
    reader: Any,
) -> Iterator[tuple[int, list[str], str, Any, Any]]:
    """Yield ``(page_index, ancestors, name, obj, subtype)`` for each XObject
    entry, visiting shared resource dicts and Form XObjects once."""
    seen_forms: set[Any] = set()
    seen_resources: set[Any] = set()
    for page_index, page in enumerate(reader.pages):
        page_resources = _resolve(page.get("/Resources"))
        if page_resources is None or not _first_visit(page_resources, seen_resources):
            continue
        # Iterative: Form XObjects can nest arbitrarily deep.
        stack: list[tuple[Any, list[str]]] = [(page_resources, [])]
        while stack:
            resources, ancestors = stack.pop()
            resources = _resolve(resources)
            if resources is None:
                continue
            xobjects = _resolve(resources.get("/XObject"))
            if xobjects is None:
                continue
            for name in xobjects:
                try:
                    obj = xobjects[name]
                    subtype = _resolve(obj.get("/Subtype"))
                except Exception:
                    logger.debug(
                        "Skipping malformed XObject %s on PDF page %d",
                        name,
                        page_index + 1,
                        exc_info=True,
                    )
                    continue
                yield page_index, ancestors, name, obj, subtype
                if subtype == "/Form" and _first_visit(obj, seen_forms):
                    stack.append((obj.get("/Resources"), [*ancestors, name]))


def _collect_mask_refs(reader: Any) -> set[Any]:
    """Every image referenced as another image's /Mask or /SMask, document-wide.

    A full pre-pass: a referrer can live on a later page or in a nested form
    than the mask it points at, so classification must wait until all
    references are known.
    """
    from pypdf.generic import IndirectObject

    mask_refs: set[Any] = set()
    for _, _, _, obj, subtype in _iter_xobject_entries(reader):
        if subtype != "/Image":
            continue
        for mask_key in ("/Mask", "/SMask"):
            mask_ref = obj.get(mask_key)
            if isinstance(mask_ref, IndirectObject):
                mask_refs.add(mask_ref)
    return mask_refs


def _content_bytes(page: Any) -> bytes | None:
    """Decoded page content, without tokenizing it into operations."""
    contents = _resolve(page.get("/Contents"))
    if contents is None:
        return None
    if isinstance(contents, (list, tuple)):
        return b"".join(_resolve(part).get_data() for part in contents)
    return contents.get_data()


def _iter_inline_image_refs(page: Any, page_index: int) -> Iterator[PdfImageRef]:
    # pypdf keys inline (BI...EI) images "~N~" in content-stream operation
    # order; the locators here must match for page.images[locator] to work.
    try:
        raw = _content_bytes(page)
    except Exception:
        raw = None
    # Tokenizing operations is expensive; skip pages that cannot contain an
    # inline image. A false "BI" hit just falls through to the full parse.
    if raw is not None and b"BI" not in raw:
        return
    try:
        contents = page.get_contents()
        operations = contents.operations if contents is not None else []
    except Exception:
        logger.warning(
            "Failed to parse content stream on PDF page %d; "
            "inline images on this page are not counted.",
            page_index + 1,
        )
        return
    inline_index = 0
    for operands, operator in operations:
        if operator != b"INLINE IMAGE":
            continue
        # Inline image dicts may use abbreviated or full key names.
        settings = operands.get("settings", {})
        yield PdfImageRef(
            locator=f"~{inline_index}~",
            page_index=page_index,
            width=_to_int(settings.get("/W", settings.get("/Width"))),
            height=_to_int(settings.get("/H", settings.get("/Height"))),
            # An inline image cannot be referenced by another image, so a
            # painted inline stencil is content.
            is_transparency_mask=False,
        )
        inline_index += 1


def iter_pdf_image_refs(reader: Any) -> Iterator[PdfImageRef]:
    """Yield one ref per unique embedded image, on the first page that
    references it. Shared resource dictionaries and nested forms would
    otherwise multiply the count by pages times nesting depth.

    Inline images inside Form XObject content streams are not enumerated:
    pypdf never parses form streams, so no ``page.images`` locator exists
    for them and extraction could not decode them anyway.
    """
    mask_refs = _collect_mask_refs(reader)
    seen_images: set[Any] = set()
    for page_index, ancestors, name, obj, subtype in _iter_xobject_entries(reader):
        if subtype != "/Image" or not _first_visit(obj, seen_images):
            continue
        yield PdfImageRef(
            locator=name if not ancestors else [*ancestors, name],
            page_index=page_index,
            width=_to_int(obj.get("/Width")),
            height=_to_int(obj.get("/Height")),
            is_transparency_mask=(
                getattr(obj, "indirect_reference", None) in mask_refs
            ),
        )
    for page_index, page in enumerate(reader.pages):
        yield from _iter_inline_image_refs(page, page_index)


def _iter_content_image_refs(reader: Any) -> Iterator[PdfImageRef]:
    """Refs that pass the filter chain; logs a skip summary when done."""
    excluded: Counter[str] = Counter()
    try:
        for ref in iter_pdf_image_refs(reader):
            reason = _first_exclude_reason(ref)
            if reason is not None:
                excluded[reason] += 1
                continue
            yield ref
    finally:
        if excluded:
            logger.info(
                "Skipped non-content embedded images in PDF: %s", dict(excluded)
            )


def count_pdf_embedded_images(file: IO[Any], cap: int) -> int:
    """Count content images in a PDF, short-circuiting at cap+1.

    Counts unique, filtered images — exactly what extraction would
    materialize. Returns a value > cap as a sentinel once the count exceeds
    the cap, and 0 if the PDF cannot be parsed.

    Owner-password-only PDFs decrypt with an empty string and are counted
    normally. Truly password-locked PDFs return 0; the caller should run the
    password-protected check first.

    Always restores the file pointer before returning.
    """
    from pypdf import PdfReader

    try:
        start_pos = file.tell()
    except Exception:
        start_pos = None
    try:
        if start_pos is not None:
            file.seek(0)
        reader = PdfReader(file)
        if reader.is_encrypted:
            # Try empty password first (owner-password-only PDFs); give up if that fails.
            try:
                if reader.decrypt("") == 0:
                    return 0
            except Exception:
                return 0
        count = 0
        for _ in _iter_content_image_refs(reader):
            count += 1
            if count > cap:
                return count
        return count
    except Exception:
        logger.warning("Failed to count embedded images in PDF", exc_info=True)
        return 0
    finally:
        if start_pos is not None:
            try:
                file.seek(start_pos)
            except Exception:
                pass


def iter_pdf_extracted_images(reader: Any, cap: int) -> Iterator[tuple[bytes, str]]:
    """Decode and yield ``(image_bytes, image_name)`` for content images.

    Decodes at most ``cap`` filtered images — a backstop so one oversized
    file can never pin a worker. An image that fails to decode is skipped,
    not fatal.
    """
    yielded = 0
    for ref in _iter_content_image_refs(reader):
        if yielded >= cap:
            logger.warning(
                "PDF embedded image cap reached (%d). "
                "Skipping remaining images on page %d and beyond.",
                cap,
                ref.page_index + 1,
            )
            break
        try:
            image_file = reader.pages[ref.page_index].images[ref.locator]
        except Exception:
            logger.warning(
                "Failed to decode embedded image %s on PDF page %d; skipping it.",
                ref.locator,
                ref.page_index + 1,
            )
            continue
        # image_file.data is already encoded and image_file.name already
        # carries the extension pypdf chose for it.
        yield image_file.data, f"page_{ref.page_index + 1}_image_{image_file.name}"
        yielded += 1
