"""Per-file extracted-text cap for Drive conversions: Google-native files carry
no `size` metadata and bypass the download size threshold, so the connector must
bound the text it retains per file."""

from unittest.mock import patch

from onyx.connectors.google_drive.doc_conversion import _cap_extracted_text
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection


def test_under_cap_returns_sections_unchanged() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        TextSection(text="b" * 100, link="l2"),
    ]
    with patch(
        "onyx.connectors.google_drive.doc_conversion.GOOGLE_DRIVE_MAX_EXTRACTED_TEXT_CHARS",
        1000,
    ):
        assert _cap_extracted_text(sections, "f") is sections


def test_over_cap_truncates_and_drops_tail() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        TextSection(text="b" * 100, link="l2"),
        TextSection(text="c" * 100, link="l3"),
    ]
    with patch(
        "onyx.connectors.google_drive.doc_conversion.GOOGLE_DRIVE_MAX_EXTRACTED_TEXT_CHARS",
        150,
    ):
        capped = _cap_extracted_text(sections, "f")

    assert len(capped) == 2
    assert isinstance(capped[0], TextSection) and capped[0].text == "a" * 100
    assert isinstance(capped[1], TextSection) and capped[1].text == "b" * 50


def test_exact_boundary_drops_section_without_partial() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        TextSection(text="b" * 100, link="l2"),
    ]
    with patch(
        "onyx.connectors.google_drive.doc_conversion.GOOGLE_DRIVE_MAX_EXTRACTED_TEXT_CHARS",
        100,
    ):
        capped = _cap_extracted_text(sections, "f")

    assert len(capped) == 1
    assert isinstance(capped[0], TextSection) and capped[0].text == "a" * 100


def test_non_positive_cap_disables_capping() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
    ]
    with patch(
        "onyx.connectors.google_drive.doc_conversion.GOOGLE_DRIVE_MAX_EXTRACTED_TEXT_CHARS",
        0,
    ):
        assert _cap_extracted_text(sections, "f") is sections


def test_image_sections_do_not_count_toward_cap() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        ImageSection(image_file_id="img1", link="l2"),
        TextSection(text="b" * 100, link="l3"),
    ]
    with patch(
        "onyx.connectors.google_drive.doc_conversion.GOOGLE_DRIVE_MAX_EXTRACTED_TEXT_CHARS",
        200,
    ):
        capped = _cap_extracted_text(sections, "f")

    assert capped is sections
