from typing import Final

import pytest
from pytest_mock import MockFixture
from pywikibot.families.wikipedia_family import Family as WikipediaFamily  # type: ignore[import-untyped]
from pywikibot.family import Family  # type: ignore[import-untyped]

from onyx.connectors.mediawiki import family


# Disabling these tests as they are flaky and rely on external wikis that are maintained by just fan communities


NON_BUILTIN_WIKIS: Final[list[tuple[str, str]]] = [
    ("https://fallout.fandom.com", "falloutwiki"),
    ("https://harrypotter.fandom.com/wiki/", "harrypotterwiki"),
    # ("https://artofproblemsolving.com/wiki", "artofproblemsolving"),  # FLAKY
    ("https://www.bogleheads.org/wiki/Main_Page", "bogleheadswiki"),
    ("https://bogleheads.org/wiki/Main_Page", "bogleheadswiki"),
    ("https://www.dandwiki.com/wiki/", "dungeonsanddragons"),
    ("https://wiki.factorio.com/", "factoriowiki"),
]


# TODO: Add support for more builtin family types from `pywikibot.families`.
@pytest.mark.skip(reason="Temporarily skipped")
@pytest.mark.parametrize(
    "url, name, expected",
    [
        (
            "https://en.wikipedia.org",
            "wikipedia",
            WikipediaFamily,
        ),  # Support urls with protocol
        (
            "wikipedia.org",
            "wikipedia",
            WikipediaFamily,
        ),  # Support urls without subdomain
        (
            "en.wikipedia.org",
            "wikipedia",
            WikipediaFamily,
        ),  # Support urls with subdomain
        ("m.wikipedia.org", "wikipedia", WikipediaFamily),
        ("de.wikipedia.org", "wikipedia", WikipediaFamily),
    ],
)
def test_family_class_dispatch_builtins(
    url: str, name: str, expected: type[Family]
) -> None:
    """Test that the family class dispatch function returns the correct family class in several scenarios."""
    assert family.family_class_dispatch(url, name) == expected


@pytest.mark.skip(reason="Temporarily skipped")
@pytest.mark.parametrize("url, name", NON_BUILTIN_WIKIS)
def test_family_class_dispatch_on_non_builtins_generates_new_class_fast(
    url: str, name: str, mocker: MockFixture
) -> None:
    """Test that using the family class dispatch function on an unknown url generates a new family class."""
    mock_generate_family_class = mocker.patch.object(family, "generate_family_class")
    family.family_class_dispatch(url, name)
    mock_generate_family_class.assert_called_once_with(url, name)


@pytest.mark.skip(reason="Temporarily skipped")
@pytest.mark.slow
@pytest.mark.parametrize("url, name", NON_BUILTIN_WIKIS)
def test_family_class_dispatch_on_non_builtins_generates_new_class_slow(
    url: str, name: str
) -> None:
    """Test that using the family class dispatch function on an unknown url generates a new family class.

    This test is slow because it actually performs the network calls to generate the family classes.
    """
    generated_family_class = family.generate_family_class(url, name)
    assert issubclass(generated_family_class, Family)
    dispatch_family_class = family.family_class_dispatch(url, name)
    assert dispatch_family_class == generated_family_class
