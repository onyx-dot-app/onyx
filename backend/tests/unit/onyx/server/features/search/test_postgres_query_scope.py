"""POST /search/postgres-query: chat history needs read:chat, not only read:search."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import JsonValue

from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.search import api
from onyx.server.features.search.models import PostgresQueryRequest


class _PastTheGate(Exception):
    """Raised where the endpoint starts its work, after the scope check."""


def _call(table: JsonValue, token_scopes: list[Permission] | None) -> None:
    http_request = MagicMock()
    http_request.state = SimpleNamespace(token_scopes=token_scopes)
    with (
        patch.object(api, "has_global_permission", return_value=True),
        patch.object(api, "_load_persona", side_effect=_PastTheGate),
    ):
        api.postgres_query(
            PostgresQueryRequest(arguments={"table": table}),
            http_request,
            user=MagicMock(),
            db_session=MagicMock(),
        )


@pytest.mark.parametrize("table", ["chat_session", "chat_message", "search_doc"])
def test_search_scoped_token_cannot_read_chat_history(table: str) -> None:
    with pytest.raises(OnyxError) as error:
        _call(table, [Permission.READ_SEARCH])
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.parametrize(
    ("table", "token_scopes"),
    [
        ("document", [Permission.READ_SEARCH]),
        ("hierarchy_node", [Permission.READ_SEARCH]),
        ("chat_session", [Permission.READ_SEARCH, Permission.READ_CHAT]),
        # A session or an unrestricted token has no cap.
        ("chat_message", None),
        # Not a table name: the tool rejects it.
        ([], [Permission.READ_SEARCH]),
        ({"name": "chat_message"}, [Permission.READ_SEARCH]),
    ],
)
def test_allowed_queries_pass_the_gate(
    table: JsonValue, token_scopes: list[Permission] | None
) -> None:
    with pytest.raises(_PastTheGate):
        _call(table, token_scopes)
