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
        # Epoch seconds; every call gets GitHub's rate limit answer until reset.
        self.rate_limit_reset: int | None = None

    def push(
        self,
        owner: str,
        repo: str,
        files: dict[str, bytes],
        *,
        ref: str = "main",
        private: bool = False,
    ) -> str:
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
        if self.rate_limit_reset is not None:
            return self._response(
                403,
                headers={
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(self.rate_limit_reset),
                },
            )
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
        owner, repo = parts[1], parts[2]
        repository = self.repositories.get((owner, repo))
        if repository is None or (repository.private and authorization is None):
            return self._response(404)
        if len(parts) == 3:
            return self._response(
                200, json.dumps({"full_name": f"{owner}/{repo}"}).encode()
            )
        kind = parts[3]
        if kind == "commits":
            ref = unquote("/".join(parts[4:]))
            sha = repository.refs.get(ref) or (
                ref if ref in repository.commits else None
            )
            if sha is None:
                # GitHub answers 422 for a ref that names no commit.
                return self._response(422)
            return self._response(200, json.dumps({"sha": sha}).encode())
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
