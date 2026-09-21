"""Images pasted into channel messages: which ones join their thread, in what
order, and what is never downloaded."""

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.microsoft_utils.drive_items import SizeCapExceeded
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    ImageSection,
    Section,
    TextSection,
)
from onyx.connectors.teams import images as images_module
from onyx.connectors.teams import threads as threads_module
from onyx.connectors.teams.utils import hosted_content_urls
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL_ID,
    DELTA_URL,
    MEMBERS_URL,
    SERVICE_ROOT,
    TEAM_ID,
    connector,
    graph_client,
    member,
    message,
    replies_url,
    walk_channel,
)

MEMBERS = {MEMBERS_URL: {"value": [member("Ada", "ada@example.com", "u1")]}}
PNG = b"\x89PNG\r\n\x1a\n" + b"png-bytes"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"


def _hosted(message_id: str, hosted_id: str, reply_of: str | None = None) -> str:
    """The Graph url of one hosted image, as the img tag names it."""
    path = f"teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/{reply_of or message_id}"
    if reply_of:
        path += f"/replies/{message_id}"
    return f"{SERVICE_ROOT}/{path}/hostedContents/{hosted_id}/$value"


def _img(url: str) -> str:
    return f'<img src="{url}" width="10" height="10">'


def _with_html(msg: dict[str, Any], html: str) -> dict[str, Any]:
    msg["body"]["content"] = html
    return msg


def _refusal(status: int) -> requests.HTTPError:
    return requests.HTTPError(str(status), response=MagicMock(status_code=status))


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The capped Graph download answering from ``served`` (bytes, or an
    exception to raise) and recording every url it was asked for."""
    served: dict[str, Any] = {}
    asked: list[str] = []

    def download(access_token: str, url: str, cap: int, description: str) -> bytes:
        assert access_token == "token" and cap > 0 and description
        asked.append(url)
        answer = served[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(images_module, "download_graph_url_with_cap", download)
    return {"served": served, "asked": asked}


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Image storage recorded instead of touching the file store."""
    saved: list[dict[str, Any]] = []

    def store(**kwargs: Any) -> tuple[ImageSection, str]:
        saved.append(kwargs)
        section = ImageSection(link=kwargs["link"], image_file_id=kwargs["file_id"])
        return section, kwargs["file_id"]

    monkeypatch.setattr(images_module, "store_image_and_create_section", store)
    return saved


def _thread_routes(
    *roots: dict[str, Any], replies: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {**MEMBERS, DELTA_URL: {"value": list(roots)}}
    for root in roots:
        routes[replies_url(root["id"])] = {"value": (replies or {}).get(root["id"], [])}
    return routes


def _sections(items: list[Document | ConnectorFailure]) -> list[Section]:
    """The sections of the one document a single-thread walk yields."""
    assert len(items) == 1
    document = items[0]
    assert isinstance(document, Document)
    return list(document.sections)


def _kinds(items: list[Document | ConnectorFailure]) -> list[str]:
    return [type(section).__name__ for section in _sections(items)]


def test_hosted_content_urls_keep_this_graph_hosts_pasted_images_only() -> None:
    root = "https://graph.microsoft.com/v1.0/teams/t/channels/c/messages/m"
    body = (
        f'<p>See</p><img itemid="1" src="{root}/hostedContents/H1/$value">'
        '<img src="https://example.com/logo.png">'
        '<img src="https://evil.example/v1.0/teams/t/channels/c/messages/m/hostedContents/H2/$value">'
        f"<img src='{root}/replies/r/hostedContents/H3/&#36;value' data-src=\"{root}/hostedContents/H4/$value\">"
        f'<a href="{root}/hostedContents/H5/$value">not an image</a>'
    )

    assert hosted_content_urls(body, "https://graph.microsoft.com/v1.0") == [
        f"{root}/hostedContents/H1/$value",
        f"{root}/replies/r/hostedContents/H3/$value",
    ]


def test_inline_images_are_off_by_default(
    downloads: dict[str, Any], stored: list[dict[str, Any]]
) -> None:
    url = _hosted("m1", "H1")
    downloads["served"][url] = PNG
    root = _with_html(message("m1", "See"), f"<p>See</p>{_img(url)}")

    items = walk_channel(connector(graph_client(_thread_routes(root))))

    assert _kinds(items) == ["TextSection"]
    assert downloads["asked"] == []
    assert stored == []


def test_images_follow_their_message_and_link_to_it(
    downloads: dict[str, Any], stored: list[dict[str, Any]]
) -> None:
    root_url, reply_url = _hosted("m1", "H1"), _hosted("r1", "H2", reply_of="m1")
    downloads["served"].update({root_url: PNG, reply_url: JPEG})
    root = _with_html(message("m1", "See"), f"<p>See</p>{_img(root_url)}")
    reply = _with_html(
        message("r1", "Zoom", reply_to="m1", created="2026-09-01T11:00:00Z"),
        f"{_img(reply_url)}<p>Zoom</p>",
    )
    client = graph_client(_thread_routes(root, replies={"m1": [reply]}))

    items = walk_channel(connector(client, include_inline_images=True))

    assert _kinds(items) == [
        "TextSection",
        "ImageSection",
        "TextSection",
        "ImageSection",
    ]
    assert [section.link for section in _sections(items)] == [
        "https://teams.example/m1",
        "https://teams.example/m1",
        "https://teams.example/r1",
        "https://teams.example/r1",
    ]
    assert [entry["image_data"] for entry in stored] == [PNG, JPEG]
    assert [entry["media_type"] for entry in stored] == ["image/png", "image/jpeg"]
    assert len({entry["file_id"] for entry in stored}) == 2


@pytest.mark.usefixtures("stored")
def test_the_thread_cap_counts_downloads_not_kept_images(
    downloads: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(threads_module, "_MAX_IMAGES_PER_THREAD", 2)
    urls = [_hosted("m1", f"H{n}") for n in range(3)]
    reply_url = _hosted("r1", "H9", reply_of="m1")
    downloads["served"].update(
        {urls[0]: SizeCapExceeded("too big"), urls[1]: PNG, reply_url: PNG}
    )
    root = _with_html(message("m1", "See"), "".join(_img(url) for url in urls))
    reply = _with_html(
        message("r1", "More", reply_to="m1", created="2026-09-01T11:00:00Z"),
        _img(reply_url),
    )
    client = graph_client(_thread_routes(root, replies={"m1": [reply]}))

    items = walk_channel(connector(client, include_inline_images=True))

    assert downloads["asked"] == urls[:2]
    assert _kinds(items).count("ImageSection") == 1
    # Three images the document does not carry: the oversized one, the third of
    # the root, and the one the reply pasted with the budget spent.
    document = next(item for item in items if isinstance(item, Document))
    assert document.metadata[images_module.IMAGES_NOT_INDEXED] == "3"


@pytest.mark.usefixtures("stored")
def test_a_thread_within_the_cap_says_nothing_about_missing_images(
    downloads: dict[str, Any],
) -> None:
    url = _hosted("m1", "H1")
    downloads["served"][url] = PNG
    root = _with_html(message("m1", "See"), _img(url))
    client = graph_client(_thread_routes(root))

    items = walk_channel(connector(client, include_inline_images=True))

    document = next(item for item in items if isinstance(item, Document))
    assert images_module.IMAGES_NOT_INDEXED not in document.metadata


def test_nothing_is_downloaded_while_image_analysis_is_off(
    downloads: dict[str, Any], stored: list[dict[str, Any]]
) -> None:
    url = _hosted("m1", "H1")
    downloads["served"][url] = PNG
    root = _with_html(message("m1", "See"), _img(url))
    teams_connector = connector(
        graph_client(_thread_routes(root)), include_inline_images=True
    )
    teams_connector.set_allow_images(False)

    items = walk_channel(teams_connector)

    assert downloads["asked"] == []
    assert stored == []
    assert _kinds(items) == ["TextSection"]


def test_a_refused_image_is_skipped_and_an_outage_fails_the_attempt(
    downloads: dict[str, Any], stored: list[dict[str, Any]]
) -> None:
    gone, fine = _hosted("m1", "GONE"), _hosted("m1", "FINE")
    downloads["served"].update({gone: _refusal(404), fine: PNG})
    root = _with_html(message("m1", "See"), _img(gone) + _img(fine))

    items = walk_channel(
        connector(graph_client(_thread_routes(root)), include_inline_images=True)
    )

    assert [entry["image_data"] for entry in stored] == [PNG]
    assert not any(isinstance(item, ConnectorFailure) for item in items)
    # The refused one is an image the document does not carry, and says so.
    document = next(item for item in items if isinstance(item, Document))
    assert document.metadata[images_module.IMAGES_NOT_INDEXED] == "1"

    outage = _hosted("m1", "OUT")
    downloads["served"][outage] = _refusal(503)
    root = _with_html(message("m1", "See"), _img(outage))
    with pytest.raises(requests.HTTPError):
        walk_channel(
            connector(graph_client(_thread_routes(root)), include_inline_images=True)
        )


@pytest.mark.usefixtures("stored")
def test_a_thread_of_only_images_is_its_images_alone(
    downloads: dict[str, Any],
) -> None:
    url = _hosted("m1", "H1")
    downloads["served"][url] = PNG
    root = _with_html(message("m1", None), _img(url))

    items = walk_channel(
        connector(graph_client(_thread_routes(root)), include_inline_images=True)
    )

    sections = _sections(items)
    assert isinstance(sections[0], ImageSection)
    assert not any(isinstance(section, TextSection) for section in sections)
