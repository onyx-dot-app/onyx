"""External dependency tests for open_url URL -> Document.id resolution.

Uses real Postgres because the resolution under test (_resolve_urls_to_document_ids)
matches candidate URLs against actual `Document.id` rows via `filter_existing_document_ids`.
The bug this guards: a Google Doc indexed under the `docs.google.com/document/d/<id>`
form must still be found when the user pastes the type-ambiguous
`drive.google.com/file/d/<id>` form.
"""

from collections.abc import Callable
from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Document as DBDocument
from onyx.kg.models import KGStage
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _resolve_urls_to_document_ids,
)
from tests.utils.sharepoint import make_sharing_token


@pytest.fixture
def doc_cleanup(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[str], None, None]:
    created: list[str] = []
    try:
        yield created
    finally:
        if created:
            db_session.query(DBDocument).filter(DBDocument.id.in_(created)).delete(
                synchronize_session="fetch"
            )
            db_session.commit()


def _seed_doc(
    db_session: Session, tracker: list[str], doc_id: str, link: str | None = None
) -> None:
    doc = DBDocument(
        id=doc_id,
        semantic_id=f"semantic-{doc_id}",
        kg_stage=KGStage.NOT_STARTED,
        link=link,
    )
    db_session.add(doc)
    db_session.commit()
    tracker.append(doc_id)


def test_file_d_url_resolves_to_indexed_native_doc(
    db_session: Session,
    doc_cleanup: list[str],
) -> None:
    """A pasted drive.google.com/file/d/<id> URL resolves to a doc indexed under
    the docs.google.com/document/d/<id> form."""
    file_id = uuid4().hex
    indexed_id = f"https://docs.google.com/document/d/{file_id}"
    _seed_doc(db_session, doc_cleanup, indexed_id)

    pasted = f"https://drive.google.com/file/d/{file_id}/view"
    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert unresolved == []
    assert len(matches) == 1
    assert matches[0].document_id == indexed_id
    assert matches[0].original_url == pasted


def test_unindexed_file_id_is_unresolved(
    db_session: Session,
    doc_cleanup: list[str],  # noqa: ARG001
) -> None:
    """A file id that isn't in the index resolves to nothing (falls back to crawl)."""
    pasted = f"https://drive.google.com/file/d/{uuid4().hex}/view"
    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert matches == []
    assert unresolved == [pasted]


def _seed_sharepoint_doc(
    db_session: Session, doc_cleanup: list[str]
) -> tuple[str, str, str]:
    """Seed a SharePoint-shaped doc: Graph drive-item id + Doc.aspx link.

    Returns (doc_id, guid, stored_link).
    """
    guid = str(uuid4()).upper()
    doc_id = f"01SFDIZ6{uuid4().hex.upper()[:24]}"
    stored_link = (
        "https://acme.sharepoint.com/sites/eng/_layouts/15/Doc.aspx"
        f"?sourcedoc=%7B{guid}%7D&file=Foo.docx&action=default&mobileredirect=true"
    )
    _seed_doc(db_session, doc_cleanup, doc_id, link=stored_link)
    return doc_id, guid, stored_link


@pytest.mark.parametrize(
    "build_pasted",
    [
        pytest.param(lambda _guid, stored_link: stored_link, id="stored-doc-aspx-url"),
        pytest.param(
            lambda guid, _stored_link: (
                "https://acme.sharepoint.com/sites/eng/_layouts/15/Doc.aspx"
                f"?sourcedoc={{{guid.lower()}}}&file=Foo.docx&action=default&mobileredirect=true"
            ),
            id="raw-brace-lowercase-guid",
        ),
        pytest.param(
            lambda guid, _stored_link: (
                "https://acme.sharepoint.com/sites/eng/_layouts/15/Doc.aspx"
                f"?file=Foo.docx&wdOrigin=TEAMS&sourcedoc=%7B{guid}%7D"
            ),
            id="reordered-extra-params",
        ),
        pytest.param(
            lambda guid, _stored_link: (
                f"https://acme.sharepoint.com/:w:/s/eng/{make_sharing_token(guid)}?e=u4Gcoi"
            ),
            id="sharing-link-token",
        ),
    ],
)
def test_sharepoint_file_url_form_resolves(
    db_session: Session,
    doc_cleanup: list[str],
    build_pasted: Callable[[str, str], str],
) -> None:
    """Every pasted file-URL form resolves to the Graph drive-item Document.id."""
    doc_id, guid, stored_link = _seed_sharepoint_doc(db_session, doc_cleanup)
    pasted = build_pasted(guid, stored_link)

    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert unresolved == []
    assert len(matches) == 1
    assert matches[0].document_id == doc_id
    assert matches[0].original_url == pasted


def test_sharepoint_site_page_resolves_via_stored_link(
    db_session: Session,
    doc_cleanup: list[str],
) -> None:
    """A SitePages URL resolves to its GUID Document.id via exact-link lookup,
    including with volatile query params attached."""
    doc_id = str(uuid4())
    stored_link = "https://acme.sharepoint.com/sites/eng/SitePages/Team-Updates.aspx"
    _seed_doc(db_session, doc_cleanup, doc_id, link=stored_link)

    for pasted in (stored_link, f"{stored_link}?web=1"):
        matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

        assert unresolved == []
        assert len(matches) == 1
        assert matches[0].document_id == doc_id
        assert matches[0].original_url == pasted


def test_sharepoint_page_sharing_link_resolves_via_guid_document_id(
    db_session: Session,
    doc_cleanup: list[str],
) -> None:
    """A sharing link to a site page resolves even though page links carry no
    GUID: the page GUID is the Document.id itself, offered as a speculative
    candidate. Rename-proof — the stored link's site name doesn't matter."""
    page_guid = str(uuid4())
    stored_link = "https://acme.sharepoint.com/sites/old-name/SitePages/Home.aspx"
    _seed_doc(db_session, doc_cleanup, page_guid, link=stored_link)

    token = make_sharing_token(page_guid.upper())
    pasted = f"https://acme.sharepoint.com/:u:/s/renamed/{token}?e=O7vbMs"

    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert unresolved == []
    assert len(matches) == 1
    assert matches[0].document_id == page_guid
    assert matches[0].original_url == pasted


def test_sharepoint_share_redirect_url_resolves_for_page(
    db_session: Session,
    doc_cleanup: list[str],
) -> None:
    """A share-redirect page URL (`?...&share=<token>`) resolves via the token."""
    page_guid = str(uuid4())
    stored_link = "https://acme.sharepoint.com/sites/eng/SitePages/Home.aspx"
    _seed_doc(db_session, doc_cleanup, page_guid, link=stored_link)

    token = make_sharing_token(page_guid.upper())
    pasted = (
        "https://acme.sharepoint.com/:u:/r/sites/eng/SitePages/Home.aspx"
        f"?csf=1&web=1&share={token}&e=9xtHB2"
    )

    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert unresolved == []
    assert len(matches) == 1
    assert matches[0].document_id == page_guid
    assert matches[0].original_url == pasted


def test_sharepoint_page_url_with_encoding_mismatch_resolves(
    db_session: Session,
    doc_cleanup: list[str],
) -> None:
    """Exact-link matching tolerates percent-encoding differences between the
    stored Graph webUrl and the pasted clipboard form."""
    doc_id = str(uuid4())
    stored_link = (
        "https://acme.sharepoint.com/sites/eng/SitePages/What's-happening.aspx"
    )
    _seed_doc(db_session, doc_cleanup, doc_id, link=stored_link)

    pasted = "https://acme.sharepoint.com/sites/eng/SitePages/What%27s-happening.aspx"
    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert unresolved == []
    assert len(matches) == 1
    assert matches[0].document_id == doc_id
    assert matches[0].original_url == pasted


def test_sharepoint_url_with_unknown_guid_is_unresolved(
    db_session: Session,
    doc_cleanup: list[str],  # noqa: ARG001
) -> None:
    """A sourcedoc GUID not in the index resolves to nothing (falls back to crawl)."""
    pasted = (
        "https://acme.sharepoint.com/sites/eng/_layouts/15/Doc.aspx"
        f"?sourcedoc=%7B{str(uuid4()).upper()}%7D&file=Foo.docx"
    )
    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert matches == []
    assert pasted in unresolved
