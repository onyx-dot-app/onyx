"""Unit tests for git smart-HTTP recognition and the read-only
GitRemoteResolver (clone/fetch token injection)."""

import base64
from unittest.mock import patch
from uuid import uuid4

import pytest
from mitmproxy import http

from onyx.sandbox_proxy.credential_injection import CredentialUnavailableError
from onyx.sandbox_proxy.credential_injection import InjectionContext
from onyx.sandbox_proxy.git_smart_http import parse_git_request
from onyx.sandbox_proxy.resolvers.git_remote import GitRemoteResolver
from tests.unit.sandbox_proxy.conftest import make_resolved_sandbox


def _request(
    method: str = "GET",
    host: str = "github.com",
    path: str = "/acme/webapp.git/info/refs?service=git-upload-pack",
    content: bytes = b"",
) -> http.Request:
    return http.Request.make(method, f"https://{host}{path}", content=content)


class TestParseGitRequest:
    @pytest.mark.parametrize(
        "method,path,is_push",
        [
            ("GET", "/acme/webapp.git/info/refs?service=git-upload-pack", False),
            ("GET", "/acme/webapp.git/info/refs?service=git-receive-pack", True),
            ("GET", "/acme/webapp/info/refs?service=git-upload-pack", False),
            ("POST", "/acme/webapp.git/git-upload-pack", False),
            ("POST", "/acme/webapp.git/git-receive-pack", True),
            ("POST", "/acme/web.app/git-receive-pack", True),
        ],
    )
    def test_recognized_shapes(self, method: str, path: str, is_push: bool) -> None:
        info = parse_git_request(_request(method=method, path=path))
        assert info is not None
        assert info.owner == "acme"
        assert info.is_push is is_push

    @pytest.mark.parametrize(
        "method,host,path",
        [
            ("GET", "api.github.com", "/acme/webapp.git/info/refs?service=git-upload-pack"),
            ("GET", "github.com", "/acme/webapp"),
            ("GET", "github.com", "/acme/webapp/releases"),
            ("GET", "github.com", "/acme/webapp.git/info/refs"),
            ("GET", "github.com", "/acme/webapp.git/info/refs?service=other"),
            ("POST", "github.com", "/acme/webapp.git/info/refs?service=git-upload-pack"),
            ("GET", "github.com", "/acme/webapp.git/git-receive-pack"),
            ("POST", "github.com", "/acme/../evil/git-receive-pack"),
        ],
    )
    def test_unrecognized_shapes(self, method: str, host: str, path: str) -> None:
        assert parse_git_request(_request(method=method, host=host, path=path)) is None

    def test_strips_git_suffix(self) -> None:
        info = parse_git_request(
            _request(path="/acme/webapp.git/git-upload-pack", method="POST")
        )
        assert info is not None
        assert info.name == "webapp"


class TestReadOnlyResolver:
    def _ctx(self) -> InjectionContext:
        return InjectionContext(
            sandbox=make_resolved_sandbox(user_id=uuid4()), matched_actions=None
        )

    def test_claims_reads_not_pushes(self) -> None:
        resolver = GitRemoteResolver()
        read = _request(path="/acme/webapp.git/info/refs?service=git-upload-pack")
        push = _request(
            method="POST", path="/acme/webapp.git/git-receive-pack", content=b"x"
        )
        assert resolver.claims(read, self._ctx())
        assert not resolver.claims(push, self._ctx())

    def test_read_injects_basic_x_access_token(self) -> None:
        request = _request(path="/acme/webapp.git/info/refs?service=git-upload-pack")
        with patch(
            "onyx.sandbox_proxy.resolvers.git_remote.get_session_with_tenant"
        ) as session_cm, patch(
            "onyx.sandbox_proxy.resolvers.git_remote.get_built_in_external_app",
            return_value=None,
        ), patch(
            "onyx.sandbox_proxy.resolvers.git_remote.get_user_github_access_token",
            return_value="gho_token123",
        ):
            session_cm.return_value.__enter__.return_value = object()
            headers = GitRemoteResolver().resolve(request, self._ctx())
        assert headers["Authorization"].startswith("Basic ")
        decoded = base64.b64decode(headers["Authorization"].split(" ", 1)[1]).decode()
        assert decoded == "x-access-token:gho_token123"

    def test_no_token_passes_through(self) -> None:
        request = _request(path="/acme/webapp.git/info/refs?service=git-upload-pack")
        with patch(
            "onyx.sandbox_proxy.resolvers.git_remote.get_session_with_tenant"
        ) as session_cm, patch(
            "onyx.sandbox_proxy.resolvers.git_remote.get_built_in_external_app",
            return_value=None,
        ), patch(
            "onyx.sandbox_proxy.resolvers.git_remote.get_user_github_access_token",
            return_value=None,
        ):
            session_cm.return_value.__enter__.return_value = object()
            assert GitRemoteResolver().resolve(request, self._ctx()) == {}

    def test_resolve_on_push_raises(self) -> None:
        push = _request(
            method="POST", path="/acme/webapp.git/git-receive-pack", content=b"x"
        )
        with pytest.raises(CredentialUnavailableError):
            GitRemoteResolver().resolve(push, self._ctx())
