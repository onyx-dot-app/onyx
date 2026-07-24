from typing import Any

from onyx.connectors.gitbook.connector import _build_public_page_url
from onyx.connectors.gitbook.connector import _convert_page_to_document
from onyx.connectors.gitbook.connector import GitbookApiClient


class FakeGitbookApiClient(GitbookApiClient):
    def __init__(self) -> None:
        pass

    def get_page_content(self, space_id: str, page_id: str) -> dict[str, Any]:
        return {
            "document": {
                "nodes": [
                    {
                        "type": "paragraph",
                        "nodes": [{"leaves": [{"text": "Published content"}]}],
                    }
                ]
            }
        }


def test_build_public_page_url_prefers_page_public_url() -> None:
    page = {
        "urls": {
            "app": "https://app.gitbook.com/o/org/s/space/page",
            "published": "https://docs.example.com/custom-page",
        },
        "path": "fallback-page",
    }

    assert (
        _build_public_page_url(page, "https://docs.example.com")
        == "https://docs.example.com/custom-page"
    )


def test_build_public_page_url_joins_space_public_url_and_page_path() -> None:
    page = {
        "urls": {"app": "https://app.gitbook.com/o/org/s/space/page"},
        "path": "/nested/page",
    }

    assert (
        _build_public_page_url(page, "https://docs.example.com/docs")
        == "https://docs.example.com/docs/nested/page"
    )


def test_build_public_page_url_falls_back_to_app_url() -> None:
    page = {
        "urls": {"app": "https://app.gitbook.com/o/org/s/space/page"},
        "path": "nested/page",
    }

    assert (
        _build_public_page_url(page, None)
        == "https://app.gitbook.com/o/org/s/space/page"
    )


def test_convert_page_to_document_uses_public_url() -> None:
    page = {
        "id": "page-id",
        "title": "Page title",
        "updatedAt": "2026-05-12T10:00:00.000Z",
        "urls": {"app": "https://app.gitbook.com/o/org/s/space/page-id"},
        "path": "page-title",
    }

    document = _convert_page_to_document(
        FakeGitbookApiClient(),
        "space-id",
        page,
        "https://docs.example.com",
    )

    assert document.sections[0].link == "https://docs.example.com/page-title"
    assert document.sections[0].text == "Published content\n\n"
