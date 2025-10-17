from typing import cast

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from starlette.routing import BaseRoute

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_chat_accessible_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_limited_user
from onyx.auth.users import current_user
from onyx.auth.users import current_user_with_expired_token
from onyx.configs.app_configs import APP_API_PREFIX
from onyx.server.onyx_api.ingestion import api_key_dep
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


PUBLIC_ENDPOINT_SPECS = [
    # built-in documentation functions
    ("/openapi.json", {"GET", "HEAD"}),
    ("/docs", {"GET", "HEAD"}),
    ("/docs/oauth2-redirect", {"GET", "HEAD"}),
    ("/redoc", {"GET", "HEAD"}),
    # should always be callable, will just return 401 if not authenticated
    ("/me", {"GET"}),
    # just returns 200 to validate that the server is up
    ("/health", {"GET"}),
    # just returns auth type, needs to be accessible before the user is logged
    # in to determine what flow to give the user
    ("/auth/type", {"GET"}),
    # just gets the version of Onyx (e.g. 0.3.11)
    ("/version", {"GET"}),
    # Gets stable and beta versions for Onyx docker images
    ("/versions", {"GET"}),
    # stuff related to basic auth
    ("/auth/refresh", {"POST"}),
    ("/auth/register", {"POST"}),
    ("/auth/login", {"POST"}),
    ("/auth/logout", {"POST"}),
    ("/auth/forgot-password", {"POST"}),
    ("/auth/reset-password", {"POST"}),
    ("/auth/request-verify-token", {"POST"}),
    ("/auth/verify", {"POST"}),
    ("/users/me", {"GET"}),
    ("/users/me", {"PATCH"}),
    ("/users/{id}", {"GET"}),
    ("/users/{id}", {"PATCH"}),
    ("/users/{id}", {"DELETE"}),
    # oauth
    ("/auth/oauth/authorize", {"GET"}),
    ("/auth/oauth/callback", {"GET"}),
    # oidc
    ("/auth/oidc/authorize", {"GET"}),
    ("/auth/oidc/callback", {"GET"}),
    # saml
    ("/auth/saml/authorize", {"GET"}),
    ("/auth/saml/callback", {"POST"}),
    ("/auth/saml/callback", {"GET"}),
    ("/auth/saml/logout", {"POST"}),
    # anonymous user on cloud
    ("/tenants/anonymous-user", {"POST"}),
    ("/metrics", {"GET"}),  # added by prometheus_fastapi_instrumentator
]


def is_route_in_spec_list(
    route: BaseRoute, public_endpoint_specs: list[tuple[str, set[str]]]
) -> bool:
    if not hasattr(route, "path") or not hasattr(route, "methods"):
        return False

    # try adding the prefix AND not adding the prefix, since some endpoints
    # are not prefixed (e.g. /openapi.json)
    if (route.path, route.methods) in public_endpoint_specs:
        return True

    processed_global_prefix = f"/{APP_API_PREFIX.strip('/')}" if APP_API_PREFIX else ""
    if not processed_global_prefix:
        return False

    for endpoint_spec in public_endpoint_specs:
        base_path, methods = endpoint_spec
        prefixed_path = f"{processed_global_prefix}/{base_path.strip('/')}"

        if prefixed_path == route.path and route.methods == methods:
            return True

    return False


def check_router_auth(
    application: FastAPI,
    public_endpoint_specs: list[tuple[str, set[str]]] = PUBLIC_ENDPOINT_SPECS,
) -> None:
    """Ensures that all endpoints on the passed in application either
    (1) have auth enabled OR
    (2) are explicitly marked as a public endpoint
    """

    control_plane_dep = fetch_ee_implementation_or_noop(
        "onyx.server.tenants.access", "control_plane_dep"
    )
    current_cloud_superuser = fetch_ee_implementation_or_noop(
        "onyx.auth.users", "current_cloud_superuser"
    )

    for route in application.routes:
        # explicitly marked as public
        if is_route_in_spec_list(route, public_endpoint_specs):
            continue

        # check for auth
        found_auth = False
        route_dependant_obj = cast(
            Dependant | None, route.dependant if hasattr(route, "dependant") else None
        )
        if route_dependant_obj:
            for dependency in route_dependant_obj.dependencies:
                depends_fn = dependency.cache_key[0]
                if (
                    depends_fn == current_limited_user
                    or depends_fn == current_user
                    or depends_fn == current_admin_user
                    or depends_fn == current_curator_or_admin_user
                    or depends_fn == api_key_dep
                    or depends_fn == current_user_with_expired_token
                    or depends_fn == current_chat_accessible_user
                    or depends_fn == control_plane_dep
                    or depends_fn == current_cloud_superuser
                ):
                    found_auth = True
                    break

        if not found_auth:
            # uncomment to print out all route(s) that are missing auth
            # print(f"(\"{route.path}\", {set(route.methods)}),")

            raise RuntimeError(
                f"Did not find user dependency in private route - {route}"
            )
