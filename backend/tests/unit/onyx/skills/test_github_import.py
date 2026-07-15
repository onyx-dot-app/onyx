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
from onyx.skills.github_import import fetch_github_skill_bundles

_REVISION = "a" * 40


class _ArchiveResponse:
    def __init__(
        self,
        archive: bytes,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        self.archive = archive
        self.status_code = status_code
        self.headers = headers or {}
        self.json_data = json_data

    def __enter__(self) -> "_ArchiveResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for offset in range(0, len(self.archive), chunk_size):
            yield self.archive[offset : offset + chunk_size]

    def json(self) -> dict[str, Any]:
        if self.json_data is None:
            raise ValueError("No JSON response")
        return self.json_data

    def close(self) -> None:
        return None


def _skill_md(name: str, description: str) -> bytes:
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


def _mock_archive(monkeypatch: pytest.MonkeyPatch, archive: bytes) -> None:
    def get(url: str, **_kwargs: Any) -> _ArchiveResponse:
        if "/commits/" in url:
            ref = unquote(url.rsplit("/", maxsplit=1)[1])
            if ref not in {"HEAD", "main"}:
                return _ArchiveResponse(b"", status_code=404)
            return _ArchiveResponse(b"", json_data={"sha": _REVISION})
        return _ArchiveResponse(archive)

    monkeypatch.setattr(
        "onyx.skills.github_import.ssrf_safe_get",
        get,
    )


@pytest.mark.parametrize(
    "source,owner,repo,subpath",
    [
        ("onyx-dot-app/onyx", "onyx-dot-app", "onyx", None),
        (
            "https://github.com/onyx-dot-app/onyx.git",
            "onyx-dot-app",
            "onyx",
            None,
        ),
        (
            "https://github.com/onyx-dot-app/onyx/tree/main/skills/example",
            "onyx-dot-app",
            "onyx",
            "skills/example",
        ),
    ],
)
def test_parse_github_repository(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    owner: str,
    repo: str,
    subpath: str | None,
) -> None:
    _mock_archive(
        monkeypatch,
        _repository_archive(
            {"skills/example/SKILL.md": _skill_md("Example", "Example skill")}
        ),
    )
    parsed, _ = fetch_github_skill_bundles(source)
    assert (parsed.owner, parsed.repo, parsed.ref, parsed.subpath) == (
        owner,
        repo,
        _REVISION,
        subpath,
    )


def test_tree_url_resolves_the_longest_matching_slash_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive(
        {"skills/example/SKILL.md": _skill_md("Example", "Example skill")}
    )
    refs_seen: list[str] = []

    def get(url: str, **_kwargs: Any) -> _ArchiveResponse:
        if "/commits/" not in url:
            return _ArchiveResponse(archive)
        refs_seen.append(unquote(url.rsplit("/", maxsplit=1)[1]))
        if refs_seen[-1] == "feature/foo":
            return _ArchiveResponse(b"", json_data={"sha": _REVISION})
        return _ArchiveResponse(b"", status_code=404)

    monkeypatch.setattr("onyx.skills.github_import.ssrf_safe_get", get)

    repository, skills = fetch_github_skill_bundles(
        "https://github.com/owner/repo/tree/feature/foo/skills/example"
    )

    assert repository.ref == _REVISION
    assert repository.subpath == "skills/example"
    assert refs_seen == [
        "feature/foo/skills/example",
        "feature/foo/skills",
        "feature/foo",
    ]
    assert [skill.name for skill in skills] == ["Example"]


def test_pinned_import_uses_previewed_revision_and_subpath(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive(
        {
            "skills/alpha/SKILL.md": _skill_md("Alpha", "First"),
            "skills/beta/SKILL.md": _skill_md("Beta", "Second"),
        }
    )
    urls_seen: list[str] = []

    def get(url: str, **_kwargs: Any) -> _ArchiveResponse:
        urls_seen.append(url)
        return _ArchiveResponse(archive)

    monkeypatch.setattr("onyx.skills.github_import.ssrf_safe_get", get)

    repository, skills = fetch_github_skill_bundles(
        "owner/repo",
        revision=_REVISION,
        subpath="skills/beta",
    )

    assert urls_seen == [f"https://codeload.github.com/owner/repo/tar.gz/{_REVISION}"]
    assert repository.ref == _REVISION
    assert repository.subpath == "skills/beta"
    assert [skill.name for skill in skills] == ["Beta"]


def test_discovers_multiple_skills_and_builds_independent_bundles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_archive(
        monkeypatch,
        _repository_archive(
            {
                "README.md": b"repository readme",
                "skills/research/SKILL.md": _skill_md(
                    "Deep Research", "Research a topic"
                ),
                "skills/research/references/guide.md": b"research guide",
                ".agents/skills/review/SKILL.md": _skill_md(
                    "Code Review", "Review a change"
                ),
                ".agents/skills/review/scripts/check.py": b"print('ok')",
            }
        ),
    )

    repository, skills = fetch_github_skill_bundles("onyx-dot-app/skills")

    assert repository.owner == "onyx-dot-app"
    assert [(skill.path, skill.slug) for skill in skills] == [
        (".agents/skills/review", "code-review"),
        ("skills/research", "deep-research"),
    ]
    by_slug = {skill.slug: skill for skill in skills}
    research = by_slug["deep-research"]
    assert research.description == "Research a topic"
    assert research.bundle_bytes is not None
    with zipfile.ZipFile(io.BytesIO(research.bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "references/guide.md"}
        assert bundle.read("references/guide.md") == b"research guide"

    review = by_slug["code-review"]
    assert review.bundle_bytes is not None
    with zipfile.ZipFile(io.BytesIO(review.bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "scripts/check.py"}
        assert "README.md" not in bundle.namelist()


def test_nested_skills_are_packaged_as_independent_bundles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_archive(
        monkeypatch,
        _repository_archive(
            {
                "skill/SKILL.md": _skill_md("Parent", "Parent skill"),
                "skill/parent.txt": b"parent",
                "skill/child/SKILL.md": _skill_md("Child", "Child skill"),
                "skill/child/child.txt": b"child",
            }
        ),
    )

    _, skills = fetch_github_skill_bundles("owner/repo")
    by_name = {skill.name: skill for skill in skills}
    assert by_name["Parent"].bundle_bytes is not None
    assert by_name["Child"].bundle_bytes is not None
    with zipfile.ZipFile(io.BytesIO(by_name["Parent"].bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "parent.txt"}
    with zipfile.ZipFile(io.BytesIO(by_name["Child"].bundle_bytes)) as bundle:
        assert set(bundle.namelist()) == {"SKILL.md", "child.txt"}


def test_reserved_skill_name_does_not_block_other_repository_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_archive(
        monkeypatch,
        _repository_archive(
            {
                "skills/pptx/SKILL.md": _skill_md(
                    "pptx", "Create and edit presentations"
                ),
                "skills/research/SKILL.md": _skill_md("Research", "Research a topic"),
            }
        ),
    )

    _, skills = fetch_github_skill_bundles("anthropics/skills")

    by_slug = {skill.slug: skill for skill in skills}
    assert by_slug["pptx"].bundle_bytes is None
    assert (
        by_slug["pptx"].unavailable_reason
        == "Can't import: 'pptx' is a reserved skill name in Onyx."
    )
    assert by_slug["research"].bundle_bytes is not None
    assert by_slug["research"].unavailable_reason is None


def test_tree_url_limits_discovery_to_selected_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_archive(
        monkeypatch,
        _repository_archive(
            {
                "skills/alpha/SKILL.md": _skill_md("Alpha", "First"),
                "skills/beta/SKILL.md": _skill_md("Beta", "Second"),
            }
        ),
    )

    _, skills = fetch_github_skill_bundles(
        "https://github.com/owner/repo/tree/main/skills/beta"
    )

    assert [(skill.path, skill.name) for skill in skills] == [("skills/beta", "Beta")]


def test_rejects_repository_symlinks(monkeypatch: pytest.MonkeyPatch) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        skill_md = _skill_md("Unsafe", "Contains a link")
        skill_member = tarfile.TarInfo("repo-sha/skill/SKILL.md")
        skill_member.size = len(skill_md)
        archive.addfile(skill_member, io.BytesIO(skill_md))
        link_member = tarfile.TarInfo("repo-sha/skill/escape")
        link_member.type = tarfile.SYMTYPE
        link_member.linkname = "../../outside"
        archive.addfile(link_member)
    _mock_archive(monkeypatch, output.getvalue())

    with pytest.raises(OnyxError, match="contains a symbolic link"):
        fetch_github_skill_bundles("owner/repo")


@pytest.mark.parametrize(
    "unsafe_path",
    ["repo-sha/skill//SKILL.md", "repo-sha/skill\\SKILL.md"],
)
def test_rejects_noncanonical_repository_paths(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_path: str,
) -> None:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        skill_md = _skill_md("Unsafe", "Contains an unsafe path")
        member = tarfile.TarInfo(unsafe_path)
        member.size = len(skill_md)
        archive.addfile(member, io.BytesIO(skill_md))
    _mock_archive(monkeypatch, output.getvalue())

    with pytest.raises(OnyxError, match="unsupported path"):
        fetch_github_skill_bundles("owner/repo")


def test_reports_invalid_skill_with_its_repository_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_archive(
        monkeypatch,
        _repository_archive({"skills/broken/SKILL.md": b"No frontmatter"}),
    )

    with pytest.raises(OnyxError, match="skills/broken/SKILL.md"):
        fetch_github_skill_bundles("owner/repo")


def test_private_repo_token_is_not_forwarded_to_archive_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive(
        {"skill/SKILL.md": _skill_md("Private", "Private skill")}
    )
    requests_seen: list[tuple[str, dict[str, Any]]] = []

    def get(url: str, **kwargs: Any) -> _ArchiveResponse:
        requests_seen.append((url, kwargs))
        if "/commits/" in url:
            if kwargs.get("headers") is None:
                return _ArchiveResponse(b"", status_code=404)
            return _ArchiveResponse(b"", json_data={"sha": _REVISION})
        if url.startswith("https://codeload.github.com/owner/repo/"):
            return _ArchiveResponse(b"", status_code=404)
        if url.startswith("https://api.github.com/"):
            return _ArchiveResponse(
                b"",
                status_code=302,
                headers={"Location": "https://codeload.github.com/signed/archive"},
            )
        return _ArchiveResponse(archive)

    monkeypatch.setattr("onyx.skills.github_import.ssrf_safe_get", get)

    _, skills = fetch_github_skill_bundles(
        "owner/repo", authorization_header="Bearer private-token"
    )

    assert [skill.name for skill in skills] == ["Private"]
    authenticated = [
        request for request in requests_seen if request[1].get("headers") is not None
    ]
    assert all(
        request[1]["headers"]["Authorization"] == "Bearer private-token"
        for request in authenticated
    )
    signed_download = requests_seen[-1]
    assert signed_download[0] == "https://codeload.github.com/signed/archive"
    assert signed_download[1]["headers"] is None


def test_connected_user_downloads_public_repository_anonymously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _repository_archive(
        {"skill/SKILL.md": _skill_md("Public", "Public skill")}
    )
    requests_seen: list[dict[str, Any]] = []

    def get(url: str, **kwargs: Any) -> _ArchiveResponse:
        requests_seen.append(kwargs)
        if "/commits/" in url:
            return _ArchiveResponse(b"", json_data={"sha": _REVISION})
        return _ArchiveResponse(archive)

    monkeypatch.setattr("onyx.skills.github_import.ssrf_safe_get", get)

    _, skills = fetch_github_skill_bundles(
        "owner/repo", authorization_header="Bearer stale-token"
    )

    assert [skill.name for skill in skills] == ["Public"]
    assert all(request["headers"] is None for request in requests_seen)


@pytest.mark.parametrize(
    "status_code,headers,error_code,message",
    [
        (
            401,
            {},
            OnyxErrorCode.UNAUTHENTICATED,
            "connection has expired",
        ),
        (
            403,
            {"X-RateLimit-Remaining": "0"},
            OnyxErrorCode.RATE_LIMITED,
            "API rate limit",
        ),
        (
            403,
            {},
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "organization SSO",
        ),
    ],
)
def test_private_repo_reports_actionable_github_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    headers: dict[str, str],
    error_code: OnyxErrorCode,
    message: str,
) -> None:
    def get(_url: str, **kwargs: Any) -> _ArchiveResponse:
        if kwargs.get("headers") is None:
            return _ArchiveResponse(b"", status_code=404)
        return _ArchiveResponse(b"", status_code=status_code, headers=headers)

    monkeypatch.setattr("onyx.skills.github_import.ssrf_safe_get", get)

    with pytest.raises(OnyxError, match=message) as exc_info:
        fetch_github_skill_bundles(
            "owner/repo", authorization_header="Bearer private-token"
        )

    assert exc_info.value.error_code == error_code


def test_unauthenticated_forbidden_repository_suggests_connecting_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.skills.github_import.ssrf_safe_get",
        lambda *_args, **_kwargs: _ArchiveResponse(b"", status_code=403),
    )

    with pytest.raises(OnyxError, match="private, connect GitHub") as exc_info:
        fetch_github_skill_bundles("owner/private-repo")

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
