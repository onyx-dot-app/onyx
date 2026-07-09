"""Per-file extracted-text cap for connector conversions: sources that can't be
size-checked before fetch (e.g. Google-native files carry no `size` metadata)
must still have the text they retain per file bounded."""

from unittest.mock import patch

from onyx.connectors.cross_connector_utils.section_utils import cap_sections_text
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection

_CAP_PATH = (
    "onyx.connectors.cross_connector_utils.section_utils."
    "CONNECTOR_MAX_EXTRACTED_TEXT_CHARS"
)


def test_under_cap_returns_sections_unchanged() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        TextSection(text="b" * 100, link="l2"),
    ]
    with patch(_CAP_PATH, 1000):
        assert cap_sections_text(sections, "f") is sections


def test_over_cap_truncates_and_drops_tail() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        TextSection(text="b" * 100, link="l2"),
        TextSection(text="c" * 100, link="l3"),
    ]
    with patch(_CAP_PATH, 150):
        capped = cap_sections_text(sections, "f")

    assert len(capped) == 2
    assert isinstance(capped[0], TextSection) and capped[0].text == "a" * 100
    assert isinstance(capped[1], TextSection) and capped[1].text == "b" * 50


def test_exact_boundary_drops_section_without_partial() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        TextSection(text="b" * 100, link="l2"),
    ]
    with patch(_CAP_PATH, 100):
        capped = cap_sections_text(sections, "f")

    assert len(capped) == 1
    assert isinstance(capped[0], TextSection) and capped[0].text == "a" * 100


def test_non_positive_cap_disables_capping() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
    ]
    with patch(_CAP_PATH, 0):
        assert cap_sections_text(sections, "f") is sections


def test_image_sections_do_not_count_toward_cap() -> None:
    sections: list[TextSection | ImageSection | TabularSection] = [
        TextSection(text="a" * 100, link="l1"),
        ImageSection(image_file_id="img1", link="l2"),
        TextSection(text="b" * 100, link="l3"),
    ]
    with patch(_CAP_PATH, 200):
        assert cap_sections_text(sections, "f") is sections
