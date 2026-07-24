from __future__ import annotations

import io
import tarfile
import zipfile
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.ingest_from_github import fetch_github_skill_bundles

_REVISION = "a" * 40


class _Response:
    def __init__(
        self,
        content: bytes = b"",
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.json_data = json_data

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        if self.json_data is None:
            raise ValueError("No JSON response")
        return self.json_data

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]


def _skill_md(name: str, description: str = "A useful skill") -> bytes:
    return (
        f"---\nname: {name}\ndescription: {description}\n---\n\n# Instructions\n"
    ).encode()


def _repository_archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path, content in files.items():
            member = tarfile.TarInfo(f"repo-sha/{path}")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def _mock_repository(
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, bytes],
) -> None:
    archive = _repository_archive(files)

    def get(url: str, **_kwargs: Any) -> _Response:
        if "/commits/" in url:
            ref = unquote(url.rsplit("/", maxsplit=1)[1])
            if ref not in {"HEAD", "main"}:
                return _Response(status_code=404)
            return _Response(json_data={"sha": _REVISION})
        return _Response(archive)

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)


def test_discovers_independent_skill_bundles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_repository(
        monkeypatch,
        {
            "README.md": b"repository readme",
            "skills/research/SKILL.md": _skill_md("research"),
            "skills/research/references/guide.md": b"research guide",
            ".agents/skills/review/SKILL.md": _skill_md("review"),
            ".agents/skills/review/scripts/check.py": b"print('ok')",
        },
    )

    repository, skills = fetch_github_skill_bundles("owner/repository")

    assert repository.revision == _REVISION
    assert [(skill.path, skill.name) for skill in skills] == [
        (".agents/skills/review", "review"),
        ("skills/research", "research"),
    ]
    by_name = {skill.name: skill for skill in skills}
    assert by_name["research"].bundle_bytes is not None
    with zipfile.ZipFile(io.BytesIO(by_name["research"].bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "references/guide.md"}
    assert by_name["review"].bundle_bytes is not None
    with zipfile.ZipFile(io.BytesIO(by_name["review"].bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "scripts/check.py"}


def test_invalid_and_reserved_skills_do_not_block_valid_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_repository(
        monkeypatch,
        {
            "skills/broken/SKILL.md": _skill_md("wrong-name"),
            "skills/pptx/SKILL.md": _skill_md("pptx"),
            "skills/research/SKILL.md": _skill_md("research"),
        },
    )

    _, skills = fetch_github_skill_bundles("owner/repository")
    by_name = {skill.name: skill for skill in skills}

    assert by_name["research"].bundle_bytes is not None
    assert by_name["research"].unavailable_reason is None
    assert by_name["broken"].bundle_bytes is None
    assert "must match its parent directory" in (
        by_name["broken"].unavailable_reason or ""
    )
    assert by_name["pptx"].bundle_bytes is None
    assert by_name["pptx"].unavailable_reason == (
        "A built-in Onyx skill already uses this name."
    )


def test_nested_skills_do_not_repeat_child_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_repository(
        monkeypatch,
        {
            "parent/SKILL.md": _skill_md("parent"),
            "parent/parent.txt": b"parent",
            "parent/child/SKILL.md": _skill_md("child"),
            "parent/child/child.txt": b"child",
        },
    )

    _, skills = fetch_github_skill_bundles("owner/repository")
    by_name = {skill.name: skill for skill in skills}
    assert by_name["parent"].bundle_bytes is not None
    assert by_name["child"].bundle_bytes is not None
    with zipfile.ZipFile(io.BytesIO(by_name["parent"].bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "parent.txt"}
    with zipfile.ZipFile(io.BytesIO(by_name["child"].bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "child.txt"}


def test_tree_url_resolves_longest_matching_slash_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive({"skills/example/SKILL.md": _skill_md("example")})
    refs_seen: list[str] = []

    def get(url: str, **_kwargs: Any) -> _Response:
        if "/commits/" not in url:
            return _Response(archive)
        ref = unquote(url.rsplit("/", maxsplit=1)[1])
        refs_seen.append(ref)
        if ref == "feature/foo":
            return _Response(json_data={"sha": _REVISION})
        return _Response(status_code=404)

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)

    repository, skills = fetch_github_skill_bundles(
        "https://github.com/owner/repository/tree/feature/foo/skills/example"
    )

    assert repository.subpath == "skills/example"
    assert refs_seen == [
        "feature/foo/skills/example",
        "feature/foo/skills",
        "feature/foo",
    ]
    assert [skill.name for skill in skills] == ["example"]


def test_import_uses_previewed_revision_without_resolving_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive(
        {
            "skills/alpha/SKILL.md": _skill_md("alpha"),
            "skills/beta/SKILL.md": _skill_md("beta"),
        }
    )
    urls_seen: list[str] = []

    def get(url: str, **_kwargs: Any) -> _Response:
        urls_seen.append(url)
        return _Response(archive)

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)

    repository, skills = fetch_github_skill_bundles(
        "owner/repository",
        revision=_REVISION,
        subpath="skills/beta",
    )

    assert urls_seen == [
        f"https://codeload.github.com/owner/repository/tar.gz/{_REVISION}"
    ]
    assert repository.subpath == "skills/beta"
    assert [skill.name for skill in skills] == ["beta"]


def test_private_token_is_not_forwarded_to_archive_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive({"private/SKILL.md": _skill_md("private")})
    requests_seen: list[tuple[str, dict[str, Any]]] = []

    def get(url: str, **kwargs: Any) -> _Response:
        requests_seen.append((url, kwargs))
        if "/commits/" in url:
            if kwargs.get("headers") is None:
                return _Response(status_code=404)
            return _Response(json_data={"sha": _REVISION})
        if url.startswith("https://codeload.github.com/owner/repository/"):
            return _Response(status_code=404)
        if url.startswith("https://api.github.com/"):
            return _Response(
                status_code=302,
                headers={"Location": "https://codeload.github.com/signed/archive"},
            )
        return _Response(archive)

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)

    _, skills = fetch_github_skill_bundles(
        "owner/repository",
        authorization_header="Bearer private-token",
    )

    assert [skill.name for skill in skills] == ["private"]
    signed_download = requests_seen[-1]
    assert signed_download[0] == "https://codeload.github.com/signed/archive"
    assert signed_download[1]["headers"] is None


def test_public_repository_stays_anonymous_when_github_is_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive({"public/SKILL.md": _skill_md("public")})
    requests_seen: list[dict[str, Any]] = []

    def get(url: str, **kwargs: Any) -> _Response:
        requests_seen.append(kwargs)
        if "/commits/" in url:
            return _Response(json_data={"sha": _REVISION})
        return _Response(archive)

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)

    _, skills = fetch_github_skill_bundles(
        "owner/repository",
        authorization_header="Bearer private-token",
    )

    assert [skill.name for skill in skills] == ["public"]
    assert all(request["headers"] is None for request in requests_seen)


def test_truncated_archive_returns_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive(
        {
            "truncated/SKILL.md": _skill_md("truncated"),
            "truncated/data.bin": b"x" * 100_000,
        }
    )

    def get(url: str, **_kwargs: Any) -> _Response:
        if "/commits/" in url:
            return _Response(json_data={"sha": _REVISION})
        return _Response(archive[:-32])

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)

    with pytest.raises(OnyxError, match="unreadable repository download") as exc_info:
        fetch_github_skill_bundles("owner/repository")

    assert exc_info.value.error_code == OnyxErrorCode.BAD_GATEWAY


def test_rejects_repository_symlinks(monkeypatch: pytest.MonkeyPatch) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        skill_md = _skill_md("unsafe")
        skill_member = tarfile.TarInfo("repo-sha/unsafe/SKILL.md")
        skill_member.size = len(skill_md)
        archive.addfile(skill_member, io.BytesIO(skill_md))
        link_member = tarfile.TarInfo("repo-sha/unsafe/escape")
        link_member.type = tarfile.SYMTYPE
        link_member.linkname = "../../outside"
        archive.addfile(link_member)

    def get(url: str, **_kwargs: Any) -> _Response:
        if "/commits/" in url:
            return _Response(json_data={"sha": _REVISION})
        return _Response(output.getvalue())

    monkeypatch.setattr("onyx.skills.ingest_from_github.ssrf_safe_get", get)

    with pytest.raises(OnyxError, match="symbolic link"):
        fetch_github_skill_bundles("owner/repository")
