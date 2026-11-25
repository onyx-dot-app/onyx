"""The playground restricts features. A router declares its feature, the one
list in onyx/server/playground.py decides, and the feature closest to the
route wins. Reads pass so a restricted page renders; writes are refused with
PLAYGROUND_RESTRICTED. Off the playground nothing changes."""

import inspect
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx import Response

from ee.onyx.server.enterprise_settings import api as enterprise_settings_api
from ee.onyx.server.features.hooks import api as hooks_api
from ee.onyx.server.log_export import api as log_export_api
from ee.onyx.server.manage import standard_answer
from ee.onyx.server.tenants import anonymous_users_api
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server import playground
from onyx.server.api_key import api as api_key_api
from onyx.server.manage import search_settings
from onyx.server.manage.embedding import api as embedding_api
from onyx.server.manage.image_generation import api as image_generation_api
from onyx.server.manage.llm import api as llm_api
from onyx.server.manage.sso import api as sso_api
from onyx.server.pat import api as pat_api
from onyx.server.playground import (
    PlaygroundRestrictedFeature,
    PlaygroundRestriction,
    is_restricted_in_playground,
    playground_restrictions,
    restrict_in_playground,
)

ROUTER_FEATURE = PlaygroundRestrictedFeature.SSO
ROUTE_FEATURE = PlaygroundRestrictedFeature.SCIM


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    playground_on: bool,
    restricted: frozenset[PlaygroundRestrictedFeature],
) -> TestClient:
    monkeypatch.setattr(playground, "IS_PLAYGROUND", playground_on)
    monkeypatch.setattr(playground, "PLAYGROUND_RESTRICTIONS", restricted)

    router = APIRouter(
        prefix="/thing", dependencies=[Depends(restrict_in_playground(ROUTER_FEATURE))]
    )

    @router.get("")
    def read() -> dict[str, str]:
        return {"ok": "read"}

    @router.post("")
    def create() -> dict[str, str]:
        return {"ok": "create"}

    @router.delete("/1")
    def remove() -> dict[str, str]:
        return {"ok": "remove"}

    # This route has its own feature, so the router's does not apply to it.
    @router.post(
        "/own-feature", dependencies=[Depends(restrict_in_playground(ROUTE_FEATURE))]
    )
    def own_feature() -> dict[str, str]:
        return {"ok": "own-feature"}

    hidden = APIRouter(
        prefix="/hidden",
        dependencies=[
            Depends(restrict_in_playground(ROUTER_FEATURE, block_reads=True))
        ],
    )

    @hidden.get("")
    def hidden_read() -> dict[str, str]:
        return {"ok": "hidden"}

    app = FastAPI()
    app.include_router(router)
    app.include_router(hidden)
    register_onyx_exception_handlers(app)
    return TestClient(app)


def _is_restricted(response: Response) -> bool:
    status = response.status_code
    if status != 403:
        return False
    body = response.json()
    return body["error_code"] == OnyxErrorCode.PLAYGROUND_RESTRICTED.code


def test_restricted_feature_refuses_writes_and_keeps_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        monkeypatch,
        playground_on=True,
        restricted=frozenset({ROUTER_FEATURE, ROUTE_FEATURE}),
    )

    assert client.get("/thing").status_code == 200
    assert _is_restricted(client.post("/thing"))
    assert _is_restricted(client.delete("/thing/1"))
    assert _is_restricted(client.post("/thing/own-feature"))


def test_block_reads_hides_the_whole_router(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        monkeypatch, playground_on=True, restricted=frozenset({ROUTER_FEATURE})
    )

    assert _is_restricted(client.get("/hidden"))


def test_route_feature_wins_over_router_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow one action on a restricted page: give its route a feature that is
    not in the list. Restrict one action on an open page: the other way round."""
    client = _client(
        monkeypatch, playground_on=True, restricted=frozenset({ROUTER_FEATURE})
    )
    assert _is_restricted(client.post("/thing"))
    assert client.post("/thing/own-feature").status_code == 200

    client = _client(
        monkeypatch, playground_on=True, restricted=frozenset({ROUTE_FEATURE})
    )
    assert client.post("/thing").status_code == 200
    assert _is_restricted(client.post("/thing/own-feature"))


def test_unrestricted_feature_lets_everything_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, playground_on=True, restricted=frozenset())

    assert client.post("/thing").status_code == 200
    assert client.post("/thing/own-feature").status_code == 200
    assert client.get("/hidden").status_code == 200


def test_cloud_lets_everything_through(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(
        monkeypatch,
        playground_on=False,
        restricted=frozenset(PlaygroundRestrictedFeature),
    )

    assert client.post("/thing").status_code == 200
    assert client.delete("/thing/1").status_code == 200
    assert client.get("/hidden").status_code == 200


@pytest.mark.parametrize("playground_on", [False, True])
def test_settings_report_the_restrictions_only_on_the_playground(
    playground_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(playground, "IS_PLAYGROUND", playground_on)

    reported = playground_restrictions()

    if playground_on:
        assert set(reported) == set(playground.PLAYGROUND_RESTRICTIONS)
        assert is_restricted_in_playground(PlaygroundRestrictedFeature.LLM_GATEWAY)
    else:
        assert reported == []
        assert not is_restricted_in_playground(PlaygroundRestrictedFeature.LLM_GATEWAY)


def test_restriction_runs_inline_not_in_the_threadpool() -> None:
    """A sync dependency costs a thread hop on every request, on every
    deployment. The restriction must stay async so cloud pays nothing for it."""
    assert inspect.iscoroutinefunction(restrict_in_playground(ROUTER_FEATURE).__call__)


def test_every_feature_is_restricted_today() -> None:
    """The ticket restricts the whole list. Allowing one is a deliberate edit here."""
    assert playground.PLAYGROUND_RESTRICTIONS == frozenset(PlaygroundRestrictedFeature)


# ---------------------------------------------------------------------------
# The production routers and the feature each one declares.
# ---------------------------------------------------------------------------


def _router_features(router: APIRouter) -> list[PlaygroundRestrictedFeature]:
    return [
        dependency.dependency.feature
        for dependency in router.dependencies
        if isinstance(dependency.dependency, PlaygroundRestriction)
    ]


def _route(router: APIRouter, path: str, method: str) -> APIRoute:
    for route in router.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in route.methods
        ):
            return route
    raise AssertionError(f"{method} {path} not found")


def _route_features(route: APIRoute) -> list[PlaygroundRestrictedFeature]:
    return [
        dependency.call.feature
        for dependency in route.dependant.dependencies
        if isinstance(dependency.call, PlaygroundRestriction)
    ]


ROUTER_FEATURES = [
    pytest.param(
        llm_api.admin_router, PlaygroundRestrictedFeature.LLM_PROVIDERS, id="llm"
    ),
    pytest.param(
        image_generation_api.admin_router,
        PlaygroundRestrictedFeature.LLM_PROVIDERS,
        id="image-providers",
    ),
    pytest.param(sso_api.admin_router, PlaygroundRestrictedFeature.SSO, id="sso"),
    pytest.param(
        embedding_api.admin_router,
        PlaygroundRestrictedFeature.EMBEDDING,
        id="embedding",
    ),
    pytest.param(
        search_settings.router,
        PlaygroundRestrictedFeature.EMBEDDING,
        id="search-settings",
    ),
    pytest.param(
        api_key_api.router,
        PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS,
        id="api-keys",
    ),
    pytest.param(
        enterprise_settings_api.admin_router,
        PlaygroundRestrictedFeature.WHITELABEL,
        id="whitelabel",
    ),
    pytest.param(
        standard_answer.router,
        PlaygroundRestrictedFeature.STANDARD_ANSWERS,
        id="standard",
    ),
    pytest.param(
        log_export_api.router, PlaygroundRestrictedFeature.LOG_EXPORT, id="export"
    ),
    pytest.param(hooks_api.router, PlaygroundRestrictedFeature.HOOKS, id="hooks"),
]


@pytest.mark.parametrize(("router", "feature"), ROUTER_FEATURES)
def test_router_declares_its_feature(
    router: APIRouter, feature: PlaygroundRestrictedFeature
) -> None:
    assert _router_features(router) == [feature]


def test_scim_token_has_its_own_feature_on_the_whitelabel_router() -> None:
    route = _route(
        enterprise_settings_api.admin_router,
        "/admin/enterprise-settings/scim/token",
        "POST",
    )
    assert _route_features(route) == [
        PlaygroundRestrictedFeature.WHITELABEL,
        PlaygroundRestrictedFeature.SCIM,
    ]


def test_anonymous_user_path_write_has_a_feature_and_the_read_does_not() -> None:
    write = _route(anonymous_users_api.router, "/tenants/anonymous-user-path", "POST")
    read = _route(anonymous_users_api.router, "/tenants/anonymous-user-path", "GET")

    assert _route_features(write) == [PlaygroundRestrictedFeature.ANONYMOUS_ACCESS]
    assert _route_features(read) == []


def test_personal_access_tokens_have_no_restriction() -> None:
    """Personal tokens stay on: only service-account keys are off."""
    assert _router_features(pat_api.router) == []


@pytest.mark.parametrize("playground_on", [False, True])
def test_anonymous_login_check_follows_the_restriction(
    playground_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The login path reads the cache directly, so the restriction sits there too."""
    from onyx.auth import users

    cache = MagicMock()
    cache.get.return_value = b"1"
    monkeypatch.setattr("onyx.cache.factory.get_cache_backend", lambda **_k: cache)
    monkeypatch.setattr(playground, "IS_PLAYGROUND", playground_on)

    assert users.anonymous_user_enabled() is not playground_on
