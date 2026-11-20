"""A fake GitHub for marketplace tests. Patches the HTTP call of
``onyx.utils.github`` and points its base URLs at hosts that do not exist, so
no test reaches the real GitHub."""

import hashlib
import io
import json
import tarfile
from urllib.parse import unquote, urlparse

import pytest
import requests

from onyx.utils import github

API = "https://api.github.fake"
ARCHIVE = "https://codeload.github.fake"
GOOD_TOKEN = "Bearer fake-good-token"


def _sha(*parts: bytes) -> str:
    return hashlib.sha1(b"\0".join(parts), usedforsecurity=False).hexdigest()


class FakeRepository:
    def __init__(self, private: bool) -> None:
        self.private = private
        self.refs: dict[str, str] = {}
        self.commits: dict[str, dict[str, bytes]] = {}
        self.truncated_tree = False

    def tree(self, sha: str) -> dict[str, object]:
        files = self.commits[sha]
        folders: dict[str, list[str]] = {}
        for path in files:
            parts = path.split("/")
            for depth in range(1, len(parts)):
                folders.setdefault("/".join(parts[:depth]), []).append(path)

        def folder_sha(paths: list[str]) -> str:
            return _sha(
                *(
                    part
                    for path in sorted(paths)
                    for part in (path.encode(), files[path])
                )
            )

        return {
            "sha": folder_sha(list(files)),
            "truncated": self.truncated_tree,
            "tree": [
                {"path": folder, "type": "tree", "sha": folder_sha(paths)}
                for folder, paths in sorted(folders.items())
            ]
            + [
                {"path": path, "type": "blob", "sha": _sha(content)}
                for path, content in sorted(files.items())
            ],
        }

    def tarball(self, owner: str, repo: str, sha: str) -> bytes:
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            for path, data in sorted(self.commits[sha].items()):
                info = tarfile.TarInfo(f"{owner}-{repo}-{sha[:7]}/{path}")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return out.getvalue()


class FakeGitHub:
    def __init__(self) -> None:
        self.repositories: dict[tuple[str, str], FakeRepository] = {}
        self.urls: list[str] = []

    def push(
        self,
        owner: str,
        repo: str,
        files: dict[str, bytes],
        *,
        ref: str = "main",
        private: bool = False,
    ) -> str:
        """Commit ``files`` as the whole repository on ``ref``, which is also
        the default branch. Returns the commit."""
        repository = self.repositories.setdefault(
            (owner, repo), FakeRepository(private)
        )
        sha = _sha(
            owner.encode(),
            repo.encode(),
            str(len(repository.commits)).encode(),
            *(part for path in sorted(files) for part in (path.encode(), files[path])),
        )
        repository.commits[sha] = dict(files)
        repository.refs[ref] = sha
        repository.refs["HEAD"] = sha
        return sha

    def _response(
        self,
        status: int,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        response = requests.Response()
        response.status_code = status
        response.raw = io.BytesIO(body)
        response.headers.update(headers or {})
        return response

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> requests.Response:
        self.urls.append(url)
        authorization = (headers or {}).get("Authorization")
        if authorization is not None and authorization != GOOD_TOKEN:
            return self._response(401)
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if url.startswith(ARCHIVE):
            owner, repo, _, sha = parts[:4]
            repository = self.repositories.get((owner, repo))
            signed = parsed.query == "signed"
            if (
                repository is None
                or sha not in repository.commits
                or (repository.private and not signed)
            ):
                return self._response(404)
            return self._response(200, repository.tarball(owner, repo, sha))
        if not url.startswith(API) or parts[0] != "repos":
            return self._response(404)
        owner, repo, kind = parts[1], parts[2], parts[3]
        repository = self.repositories.get((owner, repo))
        if repository is None or (repository.private and authorization is None):
            return self._response(404)
        if kind == "commits":
            ref = unquote("/".join(parts[4:]))
            sha = repository.refs.get(ref) or (
                ref if ref in repository.commits else None
            )
            if sha is None:
                return self._response(404)
            return self._response(200, json.dumps({"sha": sha}).encode())
        if kind == "git" and parts[4] == "trees":
            sha = parts[5]
            if sha not in repository.commits:
                return self._response(404)
            return self._response(200, json.dumps(repository.tree(sha)).encode())
        if kind == "tarball":
            sha = parts[4]
            return self._response(
                302,
                headers={"Location": f"{ARCHIVE}/{owner}/{repo}/tar.gz/{sha}?signed"},
            )
        return self._response(404)


def install_fake_github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(github, "ssrf_safe_get", fake.get)
    monkeypatch.setattr(github, "GITHUB_API_BASE_URL", API)
    monkeypatch.setattr(github, "GITHUB_ARCHIVE_BASE_URL", ARCHIVE)
    return fake
