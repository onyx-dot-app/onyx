"""Guards how the public branding routes serve whatever is stored.

The file store sniffs the media type back out of the bytes, so a logo written
before the upload allowlist existed can still come back as an active type. These
routes are unauthenticated and share the app origin, so they run the same
inline-disposition policy as the chat and user-file routes.
"""

from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock, patch

from fastapi import Response
from sqlalchemy.orm import Session

from ee.onyx.server.enterprise_settings.api import (
    fetch_logo_helper,
    fetch_logotype_helper,
)
from onyx.utils.file import FileWithMimeType


def _serve(helper: Callable[[Session], Response], mime_type: str) -> Response:
    file_store = MagicMock()
    file_store.get_file_with_mime_type.return_value = FileWithMimeType(
        data=b"stored-bytes", mime_type=mime_type
    )
    with patch(
        "ee.onyx.server.enterprise_settings.api.get_default_file_store",
        return_value=file_store,
    ):
        return helper(cast(Session, MagicMock()))


def test_an_allowed_raster_is_served_as_stored() -> None:
    response = _serve(fetch_logo_helper, "image/jpeg")

    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "no-cache"


def test_an_active_type_is_clamped_to_an_inert_image() -> None:
    response = _serve(fetch_logo_helper, "image/svg+xml")

    assert response.media_type == "image/png"
    assert response.headers["content-disposition"] == 'inline; filename="logo.png"'
    assert response.headers["x-content-type-options"] == "nosniff"
    # These routes have never sent a CSP, and the logo is embedded as an <img>.
    assert "content-security-policy" not in response.headers


def test_the_logotype_route_applies_the_same_policy() -> None:
    response = _serve(fetch_logotype_helper, "text/html")

    assert response.media_type == "image/png"
    assert response.headers["content-disposition"] == 'inline; filename="logo.png"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "cache-control" not in response.headers
