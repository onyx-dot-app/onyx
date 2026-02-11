"""
Extract images from HTML and add them as ImageSections to web connector documents.

Images are taken from <img> src (and data: URLs), stored in FileStore, and appended
so they are indexed with text. Each ImageSection gets link=page_url so citations
to image chunks show a clickable source URL (the page the image came from).
"""

import base64
import hashlib
import io
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from onyx.configs.constants import FileOrigin
from onyx.configs.llm_configs import get_image_analysis_max_size_mb
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()

IMAGE_FETCH_TIMEOUT_SEC = 15
DATA_URL_IMAGE_PREFIX = "data:image/"


def _slug_from_url(page_url: str) -> str:
    digest = hashlib.md5(page_url.encode()).hexdigest()[:16]
    return f"web_{digest}"


def _resolve_image_url(page_url: str, src: str) -> str:
    src = src.strip()
    if not src or src.startswith(("http://", "https://")):
        return src
    return urljoin(page_url, src)


def _decode_data_url(data_url: str) -> tuple[bytes, str] | None:
    if not data_url.startswith(DATA_URL_IMAGE_PREFIX):
        return None
    try:
        rest = data_url[len(DATA_URL_IMAGE_PREFIX) :]
        if ";base64," not in rest:
            return None
        media_part, b64 = rest.split(";base64,", 1)
        media_type = f"image/{media_part.split(';')[0].strip() or 'png'}"
        return (base64.b64decode(b64, validate=True), media_type)
    except Exception:
        return None


def _fetch_image_bytes(url: str, max_size_bytes: int) -> tuple[bytes, str] | None:
    try:
        resp = requests.get(
            url,
            timeout=IMAGE_FETCH_TIMEOUT_SEC,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; OnyxWebConnector/1.0)"},
        )
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip() or "application/octet-stream"
        size = 0
        chunks = []
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                size += len(chunk)
                if size > max_size_bytes:
                    logger.warning(
                        "Skipping image from %s (exceeds max size %s MB)",
                        url,
                        max_size_bytes // (1024 * 1024),
                    )
                    return None
                chunks.append(chunk)
        raw = b"".join(chunks)
        return (raw, content_type) if raw else None
    except requests.RequestException as e:
        logger.warning("Failed to fetch image from %s: %s", url, e)
        return None


def _create_image_section(
    image_data: bytes,
    parent_slug: str,
    display_name: str,
    media_type: str,
    link: str | None = None,
    idx: int = 0,
) -> ImageSection | None:
    """Create an ImageSection for one image. Sets link=page_url so citations to image chunks have a clickable source URL."""
    file_id = f"{parent_slug}_embedded_{idx}" if idx > 0 else parent_slug
    if media_type == "application/octet-stream":
        try:
            media_type = get_image_type_from_bytes(image_data)
        except ValueError:
            logger.warning(
                "Unable to determine media type for image %s; using application/octet-stream",
                display_name,
            )
    try:
        section, stored_name = store_image_and_create_section(
            image_data=image_data,
            file_id=file_id,
            display_name=display_name,
            media_type=media_type,
            link=link,
            file_origin=FileOrigin.CONNECTOR,
        )
        logger.info(
            "Web connector image indexing: created ImageSection for %s, stored as: %s",
            display_name,
            stored_name,
        )
        return section
    except Exception as e:
        logger.error("Failed to store image %s: %s", display_name, e)
        return None


def _extract_image_sources(soup: BeautifulSoup) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        alt = (img.get("alt") or "").strip() or f"image_{len(out) + 1}"
        out.append((src, alt))
    return out


def add_images_to_web_document(doc: Document, html_content: str, page_url: str) -> Document:
    """
    Extract images from HTML, store in FileStore, and return doc with
    existing sections plus ImageSections for each stored image.
    Same config as file connector: get_image_analysis_max_size_mb(), FileOrigin.CONNECTOR.
    No-op when image extraction/analysis is disabled (consistent with file connector).
    """
    max_size_mb = get_image_analysis_max_size_mb()
    logger.info(
        "Web connector image indexing: starting url=%s doc_id=%s html_len=%s max_size_mb=%s",
        page_url,
        doc.id,
        len(html_content),
        max_size_mb,
    )
    max_size_bytes = get_image_analysis_max_size_mb() * 1024 * 1024
    parent_slug = _slug_from_url(page_url)
    soup = BeautifulSoup(html_content, "html.parser")
    image_sources = _extract_image_sources(soup)
    if not image_sources:
        logger.info(
            "Web connector image indexing: no <img> sources in HTML for %s (images found: 0)",
            page_url,
        )
        return doc

    num_images_found = len(image_sources)
    logger.info(
        "Web connector image indexing: images found in HTML: %s for %s (extracting %s image(s))",
        num_images_found,
        page_url,
        num_images_found,
    )
    new_sections: list[TextSection | ImageSection] = list(doc.sections)
    num_stored = 0
    num_skipped = 0
    skip_reasons: list[str] = []

    for idx, (src, _alt) in enumerate(image_sources, start=1):
        display_name = f"{doc.semantic_identifier or page_url} - image {idx}"
        src_preview = (src[:80] + "..." if len(src) > 80 else src) if src else "(empty)"
        if src.startswith("data:"):
            logger.info(
                "Web connector image indexing: processing image %s/%s (data URL) src_preview=%s",
                idx,
                len(image_sources),
                src_preview[:50] + "..." if len(src_preview) > 50 else src_preview,
            )
            decoded = _decode_data_url(src)
            if not decoded:
                logger.warning(
                    "Web connector image indexing: skipping image %s — unsupported or invalid data URL",
                    display_name,
                )
                num_skipped += 1
                skip_reasons.append(f"img_{idx}: invalid data URL")
                continue
            image_data, media_type = decoded
            if len(image_data) > max_size_bytes:
                logger.warning(
                    "Web connector image indexing: skipping image %s — data URL exceeds max size (%s MB)",
                    display_name,
                    max_size_bytes // (1024 * 1024),
                )
                num_skipped += 1
                skip_reasons.append(f"img_{idx}: data URL too large")
                continue
        else:
            resolved = _resolve_image_url(page_url, src)
            if not resolved:
                logger.warning(
                    "Web connector image indexing: skipping image %s — resolved URL empty",
                    display_name,
                )
                num_skipped += 1
                skip_reasons.append(f"img_{idx}: empty resolved URL")
                continue
            logger.info(
                "Web connector image indexing: fetching image %s/%s url=%s",
                idx,
                len(image_sources),
                resolved[:100] + "..." if len(resolved) > 100 else resolved,
            )
            fetched = _fetch_image_bytes(resolved, max_size_bytes)
            if not fetched:
                logger.warning(
                    "Web connector image indexing: skipping image %s — fetch failed or size exceeded",
                    display_name,
                )
                num_skipped += 1
                skip_reasons.append(f"img_{idx}: fetch failed")
                continue
            image_data, media_type = fetched

        section = _create_image_section(
            image_data=image_data,
            parent_slug=parent_slug,
            display_name=display_name,
            media_type=media_type,
            idx=idx,
            link=page_url,
        )
        if section is not None:
            new_sections.append(section)
            num_stored += 1
            logger.info(
                "Web connector image indexing: stored image %s/%s for %s",
                idx,
                len(image_sources),
                page_url,
            )
        else:
            num_skipped += 1
            skip_reasons.append(f"img_{idx}: store failed")

    num_added = len(new_sections) - len(doc.sections)
    logger.info(
        "Web connector image indexing: finished url=%s images_found=%s stored=%s skipped=%s added_to_doc=%s%s",
        page_url,
        len(image_sources),
        num_stored,
        num_skipped,
        num_added,
        (" skip_reasons=[" + "; ".join(skip_reasons) + "]") if skip_reasons else "",
    )
    if num_added == 0:
        return doc
    return doc.model_copy(update={"sections": new_sections})


def add_images_to_pdf_document(doc: Document, pdf_content: bytes, page_url: str) -> Document:
    """
    Extract images from PDF, store in FileStore, and return doc with
    existing sections plus ImageSections for each stored image.
    Same config as file connector: get_image_analysis_max_size_mb(), FileOrigin.CONNECTOR.
    No-op when image extraction/analysis is disabled (consistent with file connector).
    """
    
    logger.info(
        "Web connector PDF image indexing: starting url=%s doc_id=%s pdf_size=%s",
        page_url,
        doc.id,
        len(pdf_content),
    )
    
    # Extract images from PDF using read_pdf_file
    _, _, images = read_pdf_file(
        io.BytesIO(pdf_content), extract_images=True
    )
    
    if not images:
        logger.info(
            "Web connector PDF image indexing: no images found in PDF for %s",
            page_url,
        )
        return doc
    
    num_images_found = len(images)
    logger.info(
        "Web connector PDF image indexing: images found in PDF: %s for %s (extracting %s image(s))",
        num_images_found,
        page_url,
        num_images_found,
    )
    
    new_sections: list[TextSection | ImageSection] = list(doc.sections)
    num_stored = 0
    num_skipped = 0
    skip_reasons: list[str] = []
    parent_slug = _slug_from_url(page_url)
    pdf_file_name = page_url.rstrip("/").split("/")[-1] or "pdf"
    
    for idx, (img_data, img_name) in enumerate(images, start=1):
        display_name = img_name or f"{pdf_file_name} - image {idx}"
        try:
            section = _create_image_section(
                image_data=img_data,
                parent_slug=parent_slug,
                display_name=display_name,
                media_type="application/octet-stream",
                idx=idx,
                link=page_url,
            )
            if section is not None:
                new_sections.append(section)
                num_stored += 1
                logger.info(
                    "Web connector PDF image indexing: stored image %s/%s for %s",
                    idx,
                    num_images_found,
                    page_url,
                )
            else:
                num_skipped += 1
                skip_reasons.append(f"img_{idx}: store failed")
        except Exception as e:
            logger.error(
                "Web connector PDF image indexing: failed to process image %s/%s from %s: %s",
                idx,
                num_images_found,
                page_url,
                e,
            )
            num_skipped += 1
            skip_reasons.append(f"img_{idx}: {str(e)}")
    
    num_added = len(new_sections) - len(doc.sections)
    logger.info(
        "Web connector PDF image indexing: finished url=%s images_found=%s stored=%s skipped=%s added_to_doc=%s%s",
        page_url,
        num_images_found,
        num_stored,
        num_skipped,
        num_added,
        (" skip_reasons=[" + "; ".join(skip_reasons) + "]") if skip_reasons else "",
    )
    if num_added == 0:
        return doc
    return doc.model_copy(update={"sections": new_sections})
