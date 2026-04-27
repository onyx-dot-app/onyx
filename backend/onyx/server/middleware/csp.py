"""Content-Security-Policy middleware for iframe embedding (LTI)."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from onyx.configs.lti_configs import LTI_FRAME_ANCESTORS


class CSPMiddleware(BaseHTTPMiddleware):
    """Add a Content-Security-Policy header with frame-ancestors to every
    API response so that Canvas (or another LMS) can embed the /tutor
    page in an iframe and the browser allows the fetch requests back to
    the API server.

    Only adds the header when LTI_FRAME_ANCESTORS is configured.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        if LTI_FRAME_ANCESTORS:
            response.headers["Content-Security-Policy"] = (
                f"frame-ancestors 'self' {LTI_FRAME_ANCESTORS}"
            )

        return response
