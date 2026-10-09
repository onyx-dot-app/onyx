"""The Notion censor keeps only pages the user's own Notion MCP token can
fetch: a successful fetch allows, a Notion object_not_found or
validation_error denies, and anything else drops the page without caching.
Cached answers count only while the user still has a working grant, a failed
session hides everything, the per-query check is capped, result order is
kept, and only a per-user OAuth Notion MCP server with a working grant is
used."""

from unittest.mock import MagicMock, patch

import pytest
from mcp.types import CallToolResult, TextContent

from ee.onyx.external_permissions.notion.censoring import (
    ACCESS_CACHE_TTL_S,
    MAX_PAGES_PER_QUERY,
    MAX_PARALLEL_FETCHES,
    NOTION_FETCH_TOOL,
    PageAccess,
    _fetch_pages,
    _grant_fingerprint,
    _usable_notion_connection,
    censor_notion_chunks,
    classify_fetch_result,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.server.features.mcp.models import MCPServerConnection

_MODULE = "ee.onyx.external_permissions.notion.censoring"
_USER = "user@example.com"
_NOTION_URL = "https://mcp.notion.com/mcp"
_CONNECTION = (MagicMock(), MagicMock())


def _result(text: str, is_error: bool) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)], isError=is_error
    )


def _chunk(page_id: str, chunk_id: int = 0) -> InferenceChunk:
    return InferenceChunk(
        document_id=page_id,
        chunk_id=chunk_id,
        content=f"{page_id} content",
        source_type=DocumentSource.NOTION,
        semantic_identifier=page_id,
        title=page_id,
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb=page_id,
    )


def _server(
    url: str = _NOTION_URL,
    auth_type: MCPAuthenticationType = MCPAuthenticationType.OAUTH,
    performer: MCPAuthenticationPerformer = MCPAuthenticationPerformer.PER_USER,
) -> MagicMock:
    server = MagicMock()
    server.server_url = url
    server.auth_type = auth_type
    server.auth_performer = performer
    server.transport = MCPTransport.STREAMABLE_HTTP
    return server


def _credentials(usable: bool) -> MagicMock:
    credentials = MagicMock()
    credentials.can_authenticate.return_value = usable
    credentials.connection_config_id = 7 if usable else None
    credentials.build_headers.return_value = {"Authorization": "Bearer t"}
    return credentials


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int | None] = {}

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def set(
        self, key: str, value: str | bytes | int | float, ex: int | None = None
    ) -> None:
        self.values[key] = value if isinstance(value, bytes) else str(value).encode()
        self.ttls[key] = ex


@pytest.mark.parametrize(
    "text,is_error,expected",
    [
        ('{"metadata":{"type":"page"},"title":"Page"}', False, PageAccess.ALLOWED),
        (
            '{"name":"APIResponseError","code":"object_not_found","status":404}',
            True,
            PageAccess.DENIED,
        ),
        ('{"code":"validation_error","status":400}', True, PageAccess.DENIED),
        (
            "The Notion API rate limit was reached. Wait at least 7 seconds",
            True,
            PageAccess.UNKNOWN,
        ),
        ('{"code":"internal_server_error","status":500}', True, PageAccess.UNKNOWN),
        ('["not","an","object"]', True, PageAccess.UNKNOWN),
    ],
)
def test_classify_fetch_result(text: str, is_error: bool, expected: PageAccess) -> None:
    assert classify_fetch_result(_result(text, is_error)) == expected


class TestCensorNotionChunks:
    @pytest.fixture(autouse=True)
    def setUp(self) -> None:
        self.grant = "g"
        self.cache = FakeCache()
        self.cache.values["notion_page_access:user@example.com:g:cached_ok"] = b"1"
        self.cache.values["notion_page_access:user@example.com:g:cached_no"] = b"0"
        self.chunks = [
            _chunk("cached_no"),
            _chunk("fresh_ok"),
            _chunk("cached_ok"),
            _chunk("fresh_no"),
            _chunk("fresh_ok", chunk_id=1),
            _chunk("fresh_unknown"),
        ]

    def _run(
        self,
        chunks: list[InferenceChunk],
        connection: tuple[MagicMock, MagicMock] | None,
        answers: list[PageAccess] | None,
    ) -> tuple[list[str], MagicMock]:
        with (
            patch(f"{_MODULE}.get_cache_backend", return_value=self.cache),
            patch(f"{_MODULE}._usable_notion_connection", return_value=connection),
            patch(f"{_MODULE}._grant_fingerprint", return_value=self.grant),
            patch(f"{_MODULE}._fetch_pages", return_value=answers) as fetch,
        ):
            result = censor_notion_chunks(chunks, _USER)
        return [chunk.document_id for chunk in result], fetch

    def test_answers_cached_under_another_grant_are_not_reused(self) -> None:
        self.grant = "reconnected"

        kept, fetch = self._run(
            [_chunk("cached_ok"), _chunk("cached_no")],
            _CONNECTION,
            [PageAccess.DENIED, PageAccess.ALLOWED],
        )

        assert kept == ["cached_no"]
        fetch.assert_called_once_with(
            _CONNECTION[0], _CONNECTION[1], ["cached_ok", "cached_no"]
        )

    def test_keeps_allowed_pages_in_order_and_caches_decided_answers(self) -> None:
        answers = [PageAccess.ALLOWED, PageAccess.DENIED, PageAccess.UNKNOWN]

        kept, fetch = self._run(self.chunks, _CONNECTION, answers)

        assert kept == ["fresh_ok", "cached_ok", "fresh_ok"]
        fetch.assert_called_once_with(
            _CONNECTION[0], _CONNECTION[1], ["fresh_ok", "fresh_no", "fresh_unknown"]
        )
        assert (
            self.cache.values["notion_page_access:user@example.com:g:fresh_ok"] == b"1"
        )
        assert (
            self.cache.values["notion_page_access:user@example.com:g:fresh_no"] == b"0"
        )
        assert (
            "notion_page_access:user@example.com:g:fresh_unknown"
            not in self.cache.values
        )
        assert (
            self.cache.ttls["notion_page_access:user@example.com:g:fresh_ok"]
            == ACCESS_CACHE_TTL_S
        )

    def test_checks_at_most_the_cap_and_drops_the_rest(self) -> None:
        chunks = [_chunk(f"page_{i}") for i in range(MAX_PAGES_PER_QUERY + 5)]

        kept, fetch = self._run(
            chunks, _CONNECTION, [PageAccess.ALLOWED] * MAX_PAGES_PER_QUERY
        )

        assert len(fetch.call_args.args[2]) == MAX_PAGES_PER_QUERY
        assert kept == [f"page_{i}" for i in range(MAX_PAGES_PER_QUERY)]

    def test_no_connection_hides_everything_including_cached_pages(self) -> None:
        kept, fetch = self._run(self.chunks, None, None)

        assert kept == []
        fetch.assert_not_called()

    def test_failed_session_hides_everything_including_cached_pages(self) -> None:
        kept, _ = self._run(self.chunks, _CONNECTION, None)

        assert kept == []
        assert "notion_page_access:user@example.com:g:fresh_ok" not in self.cache.values


class TestUsableNotionConnection:
    def _run(
        self, servers: list[MagicMock], credentials_by_server: dict[int, MagicMock]
    ) -> tuple[MCPServerConnection, ResolvedMCPCredentials] | None:
        with (
            patch(f"{_MODULE}.get_session_with_current_tenant"),
            patch(f"{_MODULE}.get_user_by_email", return_value=MagicMock()),
            patch(f"{_MODULE}.get_all_mcp_servers", return_value=servers),
            patch(
                f"{_MODULE}.resolve_mcp_credentials",
                side_effect=lambda server, *_: credentials_by_server[id(server)],
            ),
            patch(
                f"{_MODULE}.MCPServerConnection.model_validate",
                side_effect=lambda server: server,
            ),
        ):
            return _usable_notion_connection(_USER)

    def test_picks_the_per_user_notion_server_with_a_working_grant(self) -> None:
        wrong_host = _server(url="https://mcp.example.com/mcp")
        admin_level = _server(performer=MCPAuthenticationPerformer.ADMIN)
        dead_grant = _server()
        working = _server()
        credentials = {
            id(dead_grant): _credentials(False),
            id(working): _credentials(True),
        }

        connection = self._run(
            [wrong_host, admin_level, dead_grant, working], credentials
        )

        assert connection == (working, credentials[id(working)])

    def test_no_working_grant_is_none(self) -> None:
        dead_grant = _server()

        assert self._run([dead_grant], {id(dead_grant): _credentials(False)}) is None


class TestFetchPages:
    def test_forwards_the_user_auth_and_classifies_each_result(self) -> None:
        server = _server()
        credentials = _credentials(True)
        call = MagicMock(
            return_value=[
                _result("{}", False),
                _result('{"code":"object_not_found"}', True),
            ]
        )
        with (
            patch(f"{_MODULE}.mcp_call_auth", return_value="provider"),
            patch(f"{_MODULE}.call_mcp_tools_in_one_session", call),
        ):
            answers = _fetch_pages(server, credentials, ["p1", "p2"])

        assert answers == [PageAccess.ALLOWED, PageAccess.DENIED]
        call.assert_called_once_with(
            _NOTION_URL,
            [(NOTION_FETCH_TOOL, {"id": "p1"}), (NOTION_FETCH_TOOL, {"id": "p2"})],
            MAX_PARALLEL_FETCHES,
            connection_headers={"Authorization": "Bearer t"},
            transport=MCPTransport.STREAMABLE_HTTP,
            auth="provider",
        )

    def test_failed_session_is_none(self) -> None:
        with (
            patch(f"{_MODULE}.mcp_call_auth", return_value=None),
            patch(
                f"{_MODULE}.call_mcp_tools_in_one_session",
                side_effect=RuntimeError("HTTP 401"),
            ),
        ):
            assert _fetch_pages(_server(), _credentials(True), ["p1"]) is None


def test_grant_fingerprint_follows_the_bearer_token() -> None:
    first = _credentials(True)
    second = _credentials(True)
    second.build_headers.return_value = {"Authorization": "Bearer other"}

    assert _grant_fingerprint(first) == _grant_fingerprint(_credentials(True))
    assert _grant_fingerprint(first) != _grant_fingerprint(second)
