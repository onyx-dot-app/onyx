from pathlib import Path

import pytest

from onyx.configs.constants import DocumentSource
from onyx.onyxbot.slack.icons import _DEFAULT_SOURCE_IMAGE_FILENAME
from onyx.onyxbot.slack.icons import _PUBLIC_SOURCE_IMAGE_BASE_URL
from onyx.onyxbot.slack.icons import _SOURCE_IMAGE_FILENAMES
from onyx.onyxbot.slack.icons import source_to_github_img_link

SLACK_SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif"}
SOURCE_ICON_DIR = (
    Path(__file__).resolve().parents[5] / "web/public/slackbot-source-icons"
)


@pytest.mark.parametrize(
    ("source", "filename"), sorted(_SOURCE_IMAGE_FILENAMES.items())
)
def test_source_to_github_img_link_uses_public_images(
    source: DocumentSource,
    filename: str,
) -> None:
    img_link = source_to_github_img_link(source)

    assert img_link == f"{_PUBLIC_SOURCE_IMAGE_BASE_URL}/{filename}"


def test_all_document_sources_have_explicit_images() -> None:
    assert set(_SOURCE_IMAGE_FILENAMES) == set(DocumentSource)


def test_mapped_source_images_are_slack_compatible_public_assets() -> None:
    filenames = set(_SOURCE_IMAGE_FILENAMES.values()) | {_DEFAULT_SOURCE_IMAGE_FILENAME}

    for filename in filenames:
        asset_path = SOURCE_ICON_DIR / filename

        assert asset_path.suffix.lower() in SLACK_SUPPORTED_IMAGE_EXTENSIONS
        assert asset_path.is_file()
        assert asset_path.stat().st_size > 0
