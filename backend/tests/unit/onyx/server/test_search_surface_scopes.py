"""
Pins the search surface's route gates to READ_SEARCH so a read:search-scoped
PAT can reach every endpoint the scope's description promises ("Use search and
query endpoints"). Scoped PATs can never satisfy BASIC_ACCESS (implication
only flows basic -> read:search), so a route in this surface regressing to
BASIC_ACCESS silently locks out scoped tokens while unscoped ones still work.
"""

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from ee.onyx.server.query_and_chat.search_backend import (
    get_search_history,
    handle_send_search_message,
    search_flow_classification,
)
from onyx.db.enums import Permission
from onyx.server.features.web_search.api import (
    execute_open_urls,
    execute_web_search,
    execute_web_search_lite,
)
from onyx.server.query_and_chat.query_backend import get_tags

_SEARCH_SURFACE_HANDLERS: list[Callable[..., Any]] = [
    handle_send_search_message,
    get_search_history,
    search_flow_classification,
    get_tags,
    execute_web_search,
    execute_web_search_lite,
    execute_open_urls,
]


def _permission_gates(handler: Callable[..., Any]) -> list[Permission | None]:
    gates: list[Permission | None] = []
    for param in inspect.signature(handler).parameters.values():
        dependency = getattr(param.default, "dependency", None)  # ods: ignore[getattr]
        if dependency is not None and getattr(  # ods: ignore[getattr]
            dependency, "_is_require_permission", False
        ):
            gates.append(
                getattr(  # ods: ignore[getattr]
                    dependency, "_required_permission", None
                )
            )
    return gates


@pytest.mark.parametrize("handler", _SEARCH_SURFACE_HANDLERS, ids=lambda h: h.__name__)
def test_search_surface_route_admits_read_search_scope(
    handler: Callable[..., Any],
) -> None:
    gates = _permission_gates(handler)
    assert gates == [Permission.READ_SEARCH]
