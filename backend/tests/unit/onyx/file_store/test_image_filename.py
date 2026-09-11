import re

from onyx.file_store.utils import filename_from_image_prompt, slugify_image_name

_FILENAME = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)-([0-9a-f]{8})(\.[a-z]+)$")


def test_slugify_image_name_is_short_kebab_case() -> None:
    assert slugify_image_name("Sweet cat on a bike") == "sweet-cat-on-a-bike"


def test_slugify_image_name_keeps_at_most_five_words() -> None:
    assert (
        slugify_image_name("a photorealistic image of a fluffy orange cat")
        == "a-photorealistic-image-of-a"
    )


def test_slugify_image_name_falls_back_when_empty() -> None:
    assert slugify_image_name("   ") == "generated-image"
    assert slugify_image_name("!!!") == "generated-image"


def test_filename_from_image_prompt_adds_random_id_and_extension() -> None:
    name = filename_from_image_prompt("Sweet cat on a bike", "image/png")
    match = _FILENAME.fullmatch(name)
    assert match is not None
    assert match.group(1) == "sweet-cat-on-a-bike"
    assert match.group(3) == ".png"


def test_filename_from_image_prompt_uses_jpeg_extension() -> None:
    name = filename_from_image_prompt("sunset", "image/jpeg")
    assert name.startswith("sunset-")
    assert name.endswith(".jpg")


def test_filename_from_image_prompt_ids_differ() -> None:
    first = filename_from_image_prompt("cat", "image/png")
    second = filename_from_image_prompt("cat", "image/png")
    assert first != second
