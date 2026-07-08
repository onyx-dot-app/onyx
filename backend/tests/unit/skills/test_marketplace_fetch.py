"""Unit tests for fetch_repo_archive URL construction + error mapping.

ssrf_safe_get is monkeypatched so no real network calls are made.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import requests

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace import fetch_repo_archive
from onyx.skills.marketplace import ParsedSource
from onyx.utils.url import SSRFException


class _FakeResponse:
    def __init__(self, status_code: int, chunks: list[bytes]) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.url = "fake"

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def iter_content(self, chunk_size: int = 0) -> Iterator[bytes]:  # noqa: ARG002
        yield from self._chunks


def _source(host: str, owner: str, repo: str, ref: str | None = None) -> ParsedSource:
    return ParsedSource(
        host=host, owner=owner, repo=repo, ref=ref, subpath=None, skill_filters=[]
    )


def test_github_url_constructed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_get(url: str, **_kwargs: Any) -> _FakeResponse:
        seen["url"] = url
        return _FakeResponse(200, [b"tar", b"ball"])

    monkeypatch.setattr("onyx.skills.marketplace.ssrf_safe_get", fake_get)
    out = fetch_repo_archive(_source("github.com", "o", "r", "main"))
    assert out == b"tarball"
    assert seen["url"] == "https://codeload.github.com/o/r/tar.gz/main"


def test_github_default_ref_is_head(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_get(url: str, **_kwargs: Any) -> _FakeResponse:
        seen["url"] = url
        return _FakeResponse(200, [b"x"])

    monkeypatch.setattr("onyx.skills.marketplace.ssrf_safe_get", fake_get)
    fetch_repo_archive(_source("github.com", "o", "r"))
    assert seen["url"].endswith("/tar.gz/HEAD")


def test_gitlab_subgroup_url_constructed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_get(url: str, **_kwargs: Any) -> _FakeResponse:
        seen["url"] = url
        return _FakeResponse(200, [b"x"])

    monkeypatch.setattr("onyx.skills.marketplace.ssrf_safe_get", fake_get)
    fetch_repo_archive(_source("gitlab.com", "group/subgroup", "r", "dev"))
    assert seen["url"] == (
        "https://gitlab.com/group/subgroup/r/-/archive/dev/r-dev.tar.gz"
    )


def test_url_components_are_percent_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    # A ref carrying URL-structural chars must be encoded so it can't truncate
    # the path as a fragment/query; slashed refs keep their '/'.
    seen: dict[str, str] = {}

    def fake_get(url: str, **_kwargs: Any) -> _FakeResponse:
        seen["url"] = url
        return _FakeResponse(200, [b"x"])

    monkeypatch.setattr("onyx.skills.marketplace.ssrf_safe_get", fake_get)
    fetch_repo_archive(_source("github.com", "o", "r", "feature/x#frag"))
    assert seen["url"] == "https://codeload.github.com/o/r/tar.gz/feature/x%23frag"


def test_404_maps_to_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.skills.marketplace.ssrf_safe_get",
        lambda _url, **_kw: _FakeResponse(404, []),
    )
    with pytest.raises(OnyxError):
        fetch_repo_archive(_source("github.com", "o", "r"))


def test_non_200_maps_to_bad_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.skills.marketplace.ssrf_safe_get",
        lambda _url, **_kw: _FakeResponse(503, []),
    )
    with pytest.raises(OnyxError):
        fetch_repo_archive(_source("github.com", "o", "r"))


def test_ssrf_exception_maps_to_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        raise SSRFException("blocked")

    monkeypatch.setattr("onyx.skills.marketplace.ssrf_safe_get", fake_get)
    with pytest.raises(OnyxError):
        fetch_repo_archive(_source("github.com", "o", "r"))


def test_network_error_maps_to_bad_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(_url: str, **_kwargs: Any) -> _FakeResponse:
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("onyx.skills.marketplace.ssrf_safe_get", fake_get)
    with pytest.raises(OnyxError):
        fetch_repo_archive(_source("github.com", "o", "r"))


def test_streamed_size_cap_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.skills.marketplace.SKILL_MARKETPLACE_ARCHIVE_MAX_BYTES", 4
    )
    monkeypatch.setattr(
        "onyx.skills.marketplace.ssrf_safe_get",
        lambda _url, **_kw: _FakeResponse(200, [b"aa", b"bb", b"cc"]),
    )
    with pytest.raises(OnyxError):
        fetch_repo_archive(_source("github.com", "o", "r"))
