"""Unit tests for the fail-closed scoped-PAT route gate.

`_scoped_pat_permitted_on_route` decides whether a PAT-authenticated request may
proceed past `optional_user`: an unrestricted token (None scopes) always may; a
scoped token may only reach routes that declare a `require_permission` (which
then adjudicates coverage) or are marked `scope_exempt` (identity endpoints).
Routes with neither are denied outright.

Uses real APIRoutes + real require_permission / scope_exempt so the dependant
introspection is exercised exactly as it is at runtime.
"""

from fastapi import Depends
from fastapi.routing import APIRoute

from onyx.auth.permissions import require_permission
from onyx.auth.users import _scoped_pat_permitted_on_route
from onyx.auth.users import scope_exempt
from onyx.db.enums import Permission


async def _endpoint() -> None: ...


def _guarded_route() -> APIRoute:
    return APIRoute(
        "/x",
        _endpoint,
        dependencies=[Depends(require_permission(Permission.READ_SEARCH))],
    )


def _scope_exempt_route() -> APIRoute:
    return APIRoute("/x", _endpoint, dependencies=[Depends(scope_exempt)])


def _unguarded_route() -> APIRoute:
    return APIRoute("/x", _endpoint)


class TestScopedPatPermittedOnRoute:
    def test_unrestricted_token_always_permitted(self) -> None:
        # None scopes == session / unrestricted PAT / API key — gate is a no-op,
        # even on an unguarded route.
        assert _scoped_pat_permitted_on_route(None, _unguarded_route())

    def test_scoped_token_allowed_on_require_permission_route(self) -> None:
        # The gate only checks a guard exists; require_permission adjudicates coverage.
        assert _scoped_pat_permitted_on_route(
            [Permission.READ_SEARCH], _guarded_route()
        )

    def test_scoped_token_allowed_on_scope_exempt_route(self) -> None:
        assert _scoped_pat_permitted_on_route(
            [Permission.READ_SEARCH], _scope_exempt_route()
        )

    def test_scoped_token_denied_on_unguarded_route(self) -> None:
        assert not _scoped_pat_permitted_on_route(
            [Permission.READ_SEARCH], _unguarded_route()
        )

    def test_scoped_token_denied_when_route_missing(self) -> None:
        assert not _scoped_pat_permitted_on_route([Permission.READ_SEARCH], None)
