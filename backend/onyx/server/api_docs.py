"""Authenticated replacements for FastAPI's built-in documentation routes.

FastAPI normally serves ``/openapi.json``, ``/docs``, ``/redoc`` and
``/docs/oauth2-redirect`` to anyone. That discloses the full API surface to
unauthenticated clients (Oneleet pentest finding ON-010 / ENG-4131). We disable
the built-in routes (by passing ``openapi_url=None`` etc. to ``FastAPI(...)``)
and re-register them here behind ``current_curator_or_admin_user`` so only
logged-in admins/curators can reach them.

The offline schema generator (``backend/scripts/onyx_openapi_schema.py``) reads
the app object directly and does not hit these routes, so it is unaffected.
"""

from fastapi import Depends
from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse

from onyx.auth.users import current_curator_or_admin_user

# Keep these identical to FastAPI's defaults so existing nginx rules and any
# bookmarks/browser flows continue to resolve to the same paths.
OPENAPI_URL = "/openapi.json"
DOCS_URL = "/docs"
REDOC_URL = "/redoc"
OAUTH2_REDIRECT_URL = "/docs/oauth2-redirect"


def add_authenticated_docs_routes(application: FastAPI) -> None:
    """Register admin-gated ``/openapi.json``, ``/docs``, ``/redoc`` routes.

    Must be called with ``FastAPI(openapi_url=None, docs_url=None,
    redoc_url=None)`` so these custom routes are the only ones serving docs.
    """

    admin_only = [Depends(current_curator_or_admin_user)]

    def openapi() -> JSONResponse:
        return JSONResponse(application.openapi())

    def swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=OPENAPI_URL,
            title=f"{application.title} - Swagger UI",
            oauth2_redirect_url=OAUTH2_REDIRECT_URL,
        )

    def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()

    def redoc_html() -> HTMLResponse:
        return get_redoc_html(
            openapi_url=OPENAPI_URL,
            title=f"{application.title} - ReDoc",
        )

    application.add_api_route(
        OPENAPI_URL,
        openapi,
        methods=["GET"],
        include_in_schema=False,
        dependencies=admin_only,
    )
    application.add_api_route(
        DOCS_URL,
        swagger_ui_html,
        methods=["GET"],
        include_in_schema=False,
        dependencies=admin_only,
    )
    application.add_api_route(
        OAUTH2_REDIRECT_URL,
        swagger_ui_redirect,
        methods=["GET"],
        include_in_schema=False,
        dependencies=admin_only,
    )
    application.add_api_route(
        REDOC_URL,
        redoc_html,
        methods=["GET"],
        include_in_schema=False,
        dependencies=admin_only,
    )
