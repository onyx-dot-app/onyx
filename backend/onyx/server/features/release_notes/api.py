import asyncio
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi.responses import JSONResponse

from onyx.auth.users import current_user


# Where humans should be sent for release notes
DOCS_CHANGELOG_URL = "https://docs.onyx.app/changelog"
# Used to resolve relative links/images in the MDX content
DOCS_ORIGIN = "https://docs.onyx.app"
# Raw MDX source-of-truth that we fetch and parse
CHANGELOG_RAW_URL = (
    "https://raw.githubusercontent.com/onyx-dot-app/documentation/main/changelog.mdx"
)

# Cache the parsed changelog in-memory (per API server process)
REVALIDATE_SECONDS = 600

router = APIRouter()

_cache_lock = asyncio.Lock()
_cache: dict[str, Any] = {
    "expires_at": None,  # datetime | None
    "fetched_at": None,  # datetime | None
    "releases": None,  # list[dict] | None
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dedent_block(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return text.strip()

    # Correct handling: re.match always returns a Match or None, not a Pattern
    indents: list[int] = []
    for line in non_empty:
        # `r"^\s*"` always matches, but `re.match` is typed as Optional.
        m = re.match(r"^\s*", line)
        if m is None:
            indents.append(0)
        else:
            indents.append(len(m.group(0)))
    min_indent = min(indents)
    if min_indent <= 0:
        return "\n".join(lines).strip()
    return "\n".join(
        [line[min_indent:] if len(line) >= min_indent else "" for line in lines]
    ).strip()


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---[\s\S]*?---\s*", "", text, flags=re.MULTILINE)


def _to_absolute_docs_url(maybe_relative: str) -> str:
    if maybe_relative.startswith("#"):
        return maybe_relative
    try:
        return urljoin(DOCS_ORIGIN, maybe_relative)
    except Exception:
        return maybe_relative


def _is_allowed_external_url(url: str) -> bool:
    try:
        u = urlparse(url)
        return u.scheme == "https" and u.hostname == urlparse(DOCS_ORIGIN).hostname
    except Exception:
        return False


def _normalize_markdown_links(markdown: str) -> str:
    # Convert docs-relative links like /admins/... to https://docs.onyx.app/admins/...
    return re.sub(r"\]\((\/[^)]+)\)", rf"]({DOCS_ORIGIN}\1)", markdown)


def _note_blocks_to_blockquotes(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1) or ""
        lines = [line.strip() for line in inner.strip().split("\n") if line.strip()]
        return "\n".join([f"> {line}" for line in lines])

    return re.sub(r"<Note>\s*([\s\S]*?)\s*<\/Note>", repl, text)


def _inline_images_to_markdown(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = re.search(r'src="([^"]+)"', tag)
        alt_match = re.search(r'alt="([^"]*)"', tag)
        src = src_match.group(1) if src_match else ""
        alt = alt_match.group(1) if alt_match else ""
        abs_src = _to_absolute_docs_url(src) if src else ""
        if not abs_src or not _is_allowed_external_url(abs_src):
            return ""
        return f"![{alt}]({abs_src})"

    return re.sub(r"<img\s+[^>]*\/>", repl, text)


def _strip_unsupported_containers(text: str) -> str:
    return re.sub(r"</?div[^>]*>", "", text)


def _mdx_to_markdown(mdx_content: str) -> str:
    out = _dedent_block(mdx_content)
    out = _strip_frontmatter(out)
    out = _note_blocks_to_blockquotes(out)
    out = _inline_images_to_markdown(out)
    out = re.sub(r"</?Update[^>]*>", "", out)
    out = _strip_unsupported_containers(out)
    out = _normalize_markdown_links(out)
    return _dedent_block(out)


def _label_to_id(label: str) -> str:
    m = re.match(r"^v(\d+(?:\.\d+)+)$", label.strip())
    if m:
        return f"v{m.group(1).replace('.', '-')}"
    return re.sub(r"\s+", "-", label.strip().lower())


def _strip_redundant_leading_title_line(
    content_markdown: str, title: str, rid: str
) -> str:
    lines = content_markdown.replace("\r\n", "\n").split("\n")
    if not lines:
        return content_markdown

    first = (lines[0] or "").strip()
    m = re.match(r"^#{1,6}\s+(.+?)\s*$", first)
    if not m:
        return content_markdown

    heading_text = (m.group(1) or "").strip()

    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.lower())

    candidates = {
        norm(title),
        norm(rid),
        norm(title.replace(".", "-")),
        norm(rid.replace("-", ".")),
    }

    if norm(heading_text) not in candidates:
        return content_markdown

    idx = 1
    while idx < len(lines) and (lines[idx] or "").strip() == "":
        idx += 1
    return "\n".join(lines[idx:]).strip()


def _parse_releases_from_changelog_mdx(mdx: str) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for match in re.finditer(r"<Update\b([^>]*)>([\s\S]*?)<\/Update>", mdx):
        attrs = match.group(1) or ""
        body = match.group(2) or ""

        label_match = re.search(r'label="([^"]+)"', attrs)
        title = (label_match.group(1).strip() if label_match else "") or "Release Notes"
        rid = _label_to_id(title)
        content = _strip_redundant_leading_title_line(
            _mdx_to_markdown(body), title, rid
        )
        is_semver = re.match(r"^v(\d+(?:\.\d+)+)$", title.strip()) is not None

        releases.append(
            {
                "id": rid,
                "title": title,
                "url": (
                    f"{DOCS_CHANGELOG_URL}#{rid}" if is_semver else DOCS_CHANGELOG_URL
                ),
                "contentMarkdown": content,
            }
        )
    return releases


async def _get_cached_releases(force: bool) -> tuple[list[dict[str, Any]], datetime]:
    async with _cache_lock:
        now = _now_utc()
        expires_at: datetime | None = _cache.get("expires_at")
        fetched_at: datetime | None = _cache.get("fetched_at")
        releases: list[dict[str, Any]] | None = _cache.get("releases")

        if (
            not force
            and expires_at
            and fetched_at
            and releases is not None
            and now < expires_at
        ):
            return releases, fetched_at

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(CHANGELOG_RAW_URL)

        if res.status_code != 200:
            raise RuntimeError(f"Failed to fetch release notes ({res.status_code})")

        mdx = res.text
        parsed = _parse_releases_from_changelog_mdx(mdx)
        fetched_at = now
        _cache["releases"] = parsed
        _cache["fetched_at"] = fetched_at
        _cache["expires_at"] = now + timedelta(seconds=REVALIDATE_SECONDS)

        return parsed, fetched_at


@router.get("/release-notes", dependencies=[Depends(current_user)])
async def get_release_notes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    force: bool = Query(False),
) -> JSONResponse:
    try:
        releases, fetched_at = await _get_cached_releases(force=force)
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": str(e), "sourceUrl": CHANGELOG_RAW_URL},
        )

    sliced = releases[offset : offset + limit]

    return JSONResponse(
        status_code=200,
        content={
            "sourceUrl": CHANGELOG_RAW_URL,
            "fetchedAt": fetched_at.isoformat(),
            "total": len(releases),
            "offset": offset,
            "limit": limit,
            "items": sliced,
        },
    )
