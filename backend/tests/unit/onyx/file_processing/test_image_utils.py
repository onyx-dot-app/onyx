from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.models import ImageSection
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection
from onyx.file_processing.image_utils import make_image_callback

# Minimal valid file headers for testing magic-byte detection
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 50
_GIF_BYTES = b"GIF89a" + b"\x00" * 50  # recognized but excluded
_UNKNOWN_BYTES = b"\x00\x00\x00\x00" + b"\x00" * 50


class TestMakeImageCallback:
    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_valid_png_appends_section(self, mock_store: MagicMock) -> None:
        mock_store.return_value = (
            ImageSection(image_file_id="stored_id"),
            "stored_id",
        )
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(
            sections,
            file_id="doc1",
            file_name="slides.pptx",
            link="https://example.com",
        )

        callback(_PNG_BYTES, "image1.png")

        assert len(sections) == 1
        assert isinstance(sections[0], ImageSection)
        assert sections[0].image_file_id == "stored_id"
        assert sections[0].link == "https://example.com"
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args
        assert call_kwargs.kwargs["file_id"] == "doc1_img_0"
        assert call_kwargs.kwargs["display_name"] == "image1.png"

    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_valid_jpeg_appends_section(self, mock_store: MagicMock) -> None:
        mock_store.return_value = (
            ImageSection(image_file_id="stored_id"),
            "stored_id",
        )
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(sections, "doc1", "slides.pptx")

        callback(_JPEG_BYTES, "photo.jpg")

        assert len(sections) == 1

    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_unknown_format_skipped(self, mock_store: MagicMock) -> None:
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(sections, "doc1", "slides.pptx")

        callback(_UNKNOWN_BYTES, "mystery.bin")

        assert len(sections) == 0
        mock_store.assert_not_called()

    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_excluded_type_skipped(self, mock_store: MagicMock) -> None:
        """GIF is recognized by magic bytes but is in EXCLUDED_IMAGE_TYPES."""
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(sections, "doc1", "slides.pptx")

        callback(_GIF_BYTES, "animation.gif")

        assert len(sections) == 0
        mock_store.assert_not_called()

    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_file_id_increments_with_section_count(self, mock_store: MagicMock) -> None:
        mock_store.return_value = (
            ImageSection(image_file_id="stored_id"),
            "stored_id",
        )
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(sections, "doc1", "slides.pptx")

        callback(_PNG_BYTES, "img1.png")
        callback(_PNG_BYTES, "img2.png")

        assert len(sections) == 2
        calls = mock_store.call_args_list
        assert calls[0].kwargs["file_id"] == "doc1_img_0"
        assert calls[1].kwargs["file_id"] == "doc1_img_1"

    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_fallback_display_name_when_img_name_empty(
        self, mock_store: MagicMock
    ) -> None:
        mock_store.return_value = (
            ImageSection(image_file_id="stored_id"),
            "stored_id",
        )
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(sections, "doc1", "slides.pptx")

        callback(_PNG_BYTES, "")

        call_kwargs = mock_store.call_args
        assert call_kwargs.kwargs["display_name"] == "slides.pptx - image 0"

    @patch("onyx.file_processing.image_utils.store_image_and_create_section")
    def test_link_is_none_when_not_provided(self, mock_store: MagicMock) -> None:
        mock_store.return_value = (
            ImageSection(image_file_id="stored_id"),
            "stored_id",
        )
        sections: list[TextSection | ImageSection | TabularSection] = []
        callback = make_image_callback(sections, "doc1", "slides.pptx")

        callback(_PNG_BYTES, "img.png")

        assert sections[0].link is None
