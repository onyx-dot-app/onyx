from onyx.file_processing.file_types import is_allowed_avatar_content_type


def test_allows_configured_raster_image_types() -> None:
    assert is_allowed_avatar_content_type("image/png")
    assert is_allowed_avatar_content_type("image/jpeg")
    assert is_allowed_avatar_content_type("image/jpg")
    assert is_allowed_avatar_content_type("image/webp")


def test_allows_missing_content_type() -> None:
    # Callers fall back to a default file type when the client sends none.
    assert is_allowed_avatar_content_type(None)


def test_rejects_html_content_type() -> None:
    assert not is_allowed_avatar_content_type("text/html")


def test_rejects_svg_content_type() -> None:
    # SVG can carry inline <script>; it is deliberately excluded from
    # OnyxMimeTypes.IMAGE_MIME_TYPES.
    assert not is_allowed_avatar_content_type("image/svg+xml")


def test_rejects_other_excluded_image_types() -> None:
    assert not is_allowed_avatar_content_type("image/gif")
    assert not is_allowed_avatar_content_type("image/bmp")
