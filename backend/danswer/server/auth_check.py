from typing import cast

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.server.danswer_api.ingestion import api_key_dep


PUBLIC_ENDPOINT_SPECS = [
    # built-in documentation functions
    ("/openapi.json", {"GET", "HEAD"}),
    ("/docs", {"GET", "HEAD"}),
    ("/docs/oauth2-redirect", {"GET", "HEAD"}),
    ("/redoc", {"GET", "HEAD"}),
    # should always be callable, will just return 401 if not authenticated
    ("/manage/me", {"GET"}),
    # just returns 200 to validate that the server is up
    ("/health", {"GET"}),
    # just returns auth type, needs to be accessible before the user is logged
    # in to determine what flow to give the user
    ("/auth/type", {"GET"}),
    # just gets the version of Danswer (e.g. 0.3.11)
    ("/version", {"GET"}),
    # stuff related to basic auth
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
]


def check_router_auth(application: FastAPI) -> None:
    """Ensures that all endpoints on the passed in application either
    (1) have auth enabled OR
    (2) are explicitly marked as a public endpoint
    """
    for route in application.routes:
        # explicitly marked as public
        if (
            hasattr(route, "path")
            and hasattr(route, "methods")
            and (route.path, route.methods) in PUBLIC_ENDPOINT_SPECS
        ):
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
                    depends_fn == current_user
                    or depends_fn == current_admin_user
                    or depends_fn == api_key_dep
                ):
                    found_auth = True
                    break

        if not found_auth:
            # uncomment to print out all route(s) that are missing auth
            # print(f"(\"{route.path}\", {set(route.methods)}),")

            raise RuntimeError(
                f"Did not find current_user or current_admin_user dependency in route - {route}"
            )
