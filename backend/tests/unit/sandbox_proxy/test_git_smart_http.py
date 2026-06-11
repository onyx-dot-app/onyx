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


class TestReadResolver:
    def _ctx(self) -> InjectionContext:
        return InjectionContext(
            sandbox=make_resolved_sandbox(user_id=uuid4()), matched_actions=None
        )

    def test_claims_reads_and_pushes(self) -> None:
        resolver = GitRemoteResolver()
        read = _request(path="/acme/webapp.git/info/refs?service=git-upload-pack")
        push = _request(
            method="POST", path="/acme/webapp.git/git-receive-pack", content=b"x"
        )
        assert resolver.claims(read, self._ctx())
        assert resolver.claims(push, self._ctx())

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


_OLD = "a" * 40
_NEW = "b" * 40
_ZERO = "0" * 40


def _pkt(line: bytes) -> bytes:
    return f"{len(line) + 4:04x}".encode() + line


def _push_body(*refs: str, zero_new: bool = False) -> bytes:
    body = b""
    for index, ref in enumerate(refs):
        new_sha = _ZERO if zero_new else _NEW
        line = f"{_OLD} {new_sha} {ref}".encode()
        if index == 0:
            line += b"\0report-status side-band-64k"
        body += _pkt(line + b"\n")
    return body + b"0000" + b"PACK\x00\x00fake"


class TestParseReceivePackCommands:
    def test_single_command_with_capabilities(self) -> None:
        from onyx.sandbox_proxy.git_smart_http import parse_receive_pack_commands

        updates = parse_receive_pack_commands(_push_body("refs/heads/craft/x-aa"))
        assert len(updates) == 1
        assert updates[0].ref_name == "refs/heads/craft/x-aa"
        assert not updates[0].is_delete

    def test_delete_detected(self) -> None:
        from onyx.sandbox_proxy.git_smart_http import parse_receive_pack_commands

        updates = parse_receive_pack_commands(
            _push_body("refs/heads/craft/x-aa", zero_new=True)
        )
        assert updates[0].is_delete

    @pytest.mark.parametrize(
        "body",
        [
            b"",
            b"00",
            b"zzzz" + b"0000",
            b"0000",
            _pkt(b"garbage line\n") + b"0000",
        ],
    )
    def test_malformed_bodies_raise(self, body: bytes) -> None:
        from onyx.sandbox_proxy.git_smart_http import GitProtocolError
        from onyx.sandbox_proxy.git_smart_http import parse_receive_pack_commands

        with pytest.raises(GitProtocolError):
            parse_receive_pack_commands(body)

    def test_disallowed_refs(self) -> None:
        from onyx.sandbox_proxy.git_smart_http import disallowed_push_refs

        assert disallowed_push_refs(_push_body("refs/heads/craft/ok-aa")) == []
        assert disallowed_push_refs(
            _push_body("refs/heads/craft/ok-aa", "refs/heads/main")
        ) == ["refs/heads/main"]
        assert disallowed_push_refs(_push_body("refs/tags/v1")) == ["refs/tags/v1"]
        assert disallowed_push_refs(_push_body("refs/craft/x")) == ["refs/craft/x"]


class TestPushEnforcement:
    def _ctx(self) -> InjectionContext:
        return InjectionContext(
            sandbox=make_resolved_sandbox(user_id=uuid4()), matched_actions=None
        )

    def test_push_outside_craft_blocked_before_credentials(self) -> None:
        request = _request(
            method="POST",
            path="/acme/webapp.git/git-receive-pack",
            content=_push_body("refs/heads/main"),
        )
        resolver = GitRemoteResolver()
        assert resolver.claims(request, self._ctx())
        with pytest.raises(CredentialUnavailableError, match="non-craft"):
            resolver.resolve(request, self._ctx())

    def test_unparseable_push_blocked(self) -> None:
        request = _request(
            method="POST",
            path="/acme/webapp.git/git-receive-pack",
            content=b"not pkt lines at all",
        )
        with pytest.raises(CredentialUnavailableError, match="unparseable"):
            GitRemoteResolver().resolve(request, self._ctx())

    def test_compressed_push_rejected(self) -> None:
        request = _request(
            method="POST",
            path="/acme/webapp.git/git-receive-pack",
            content=_push_body("refs/heads/craft/ok-aa"),
        )
        request.headers["content-encoding"] = "gzip"
        with pytest.raises(CredentialUnavailableError, match="compressed"):
            GitRemoteResolver().resolve(request, self._ctx())

    def test_craft_push_injects_basic_auth(self) -> None:
        request = _request(
            method="POST",
            path="/acme/webapp.git/git-receive-pack",
            content=_push_body("refs/heads/craft/ok-aa"),
        )
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
        decoded = base64.b64decode(headers["Authorization"].split(" ", 1)[1]).decode()
        assert decoded == "x-access-token:gho_token123"
