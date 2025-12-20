from __future__ import annotations

import builtins
import functools
import itertools
import tempfile
from typing import Any
from unittest import mock
from urllib.parse import urlparse
from urllib.parse import urlunparse

from pywikibot import family  # type: ignore[import-untyped]
from pywikibot import pagegenerators  # type: ignore[import-untyped]
from pywikibot.scripts import generate_family_file  # type: ignore[import-untyped]
from pywikibot.scripts.generate_user_files import pywikibot  # type: ignore[import-untyped]

from onyx.utils.logger import setup_logger


logger = setup_logger()

pywikibot.config.base_dir = tempfile.TemporaryDirectory().name


@mock.patch.object(
    builtins, "print", lambda *args: logger.info("\t".join(map(str, args)))
)
class FamilyFileGeneratorInMemory(generate_family_file.FamilyFileGenerator):
    """A subclass of FamilyFileGenerator that writes the family file to memory instead of to disk."""

    def __init__(
        self,
        url: str,
        name: str,
        dointerwiki: str | bool = True,
        verify: str | bool = True,
    ):
        """Initialize the FamilyFileGeneratorInMemory."""

        url_parse = urlparse(url, "https")
        if not url_parse.netloc and url_parse.path:
            url = urlunparse(
                (url_parse.scheme, url_parse.path, url_parse.netloc, *url_parse[3:])
            )
        else:
            url = urlunparse(url_parse)
        assert isinstance(url, str)

        if any(x not in generate_family_file.NAME_CHARACTERS for x in name):
            raise ValueError(
                f'ERROR: Name of family "{name}" must be ASCII letters and digits [a-zA-Z0-9]',
            )

        if isinstance(dointerwiki, bool):
            dointerwiki = "Y" if dointerwiki else "N"
        assert isinstance(dointerwiki, str)

        if isinstance(verify, bool):
            verify = "Y" if verify else "N"
        assert isinstance(verify, str)

        super().__init__(url, name, dointerwiki, verify)
        self.family_definition: type[family.Family] | None = None

    def get_params(self) -> bool:
        """Get the parameters for the family class definition.

        This override prevents the method from prompting the user for input (which would be impossible in this context).
        We do all the input validation in the constructor.
        """
        return True

    def writefile(self, verify: Any) -> None:
        """Write the family file.

        This overrides the method in the parent class to write the family definition to memory instead of to disk.

        Args:
            verify: unused argument necessary to match the signature of the method in the parent class.
        """
        code_hostname_pairs = {
            f"{k}": f"{urlparse(w.server).netloc}" for k, w in self.wikis.items()
        }

        code_path_pairs = {f"{k}": f"{w.scriptpath}" for k, w in self.wikis.items()}

        code_protocol_pairs = {
            f"{k}": f"{urlparse(w.server).scheme}" for k, w in self.wikis.items()
        }

        class Family(family.Family):  # noqa: D101
            """The family definition for the wiki."""

            name = "%(name)s"
            langs = code_hostname_pairs

            def scriptpath(self, code: str) -> str:
                return code_path_pairs[code]

            def protocol(self, code: str) -> str:
                return code_protocol_pairs[code]

        self.family_definition = Family


@functools.lru_cache(maxsize=None)
def generate_family_class(url: str, name: str) -> type[family.Family]:
    """Generate a family file for a given URL and name.

    Args:
        url: The URL of the wiki.
        name: The short name of the wiki (customizable by the user).

    Returns:
        The family definition.

    Raises:
        ValueError: If the family definition was not generated.
    """

    generator = FamilyFileGeneratorInMemory(url, name, "Y", "Y")
    generator.run()
    if generator.family_definition is None:
        raise ValueError("Family definition was not generated.")
    return generator.family_definition


def family_class_dispatch(url: str, name: str) -> type[family.Family]:
    """Find or generate a family class for a given URL and name.

    Args:
        url: The URL of the wiki.
        name: The short name of the wiki (customizable by the user).

    """
    if "wikipedia" in url:
        import pywikibot.families.wikipedia_family  # type: ignore[import-untyped]

        return pywikibot.families.wikipedia_family.Family
    # TODO: Support additional families pre-defined in `pywikibot.families.*_family.py` files
    return generate_family_class(url, name)


if __name__ == "__main__":
    url = "fallout.fandom.com/wiki/Fallout_Wiki"
    name = "falloutfandom"

    categories: list[str] = []
    pages = ["Fallout: New Vegas"]
    recursion_depth = 1
    family_type = generate_family_class(url, name)

    site = pywikibot.Site(fam=family_type(), code="en")
    categories = [
        pywikibot.Category(site, f"Category:{category.replace(' ', '_')}")
        for category in categories
    ]
    pages = [pywikibot.Page(site, page) for page in pages]
    all_pages = itertools.chain(
        pages,
        *[
            pagegenerators.CategorizedPageGenerator(category, recurse=recursion_depth)
            for category in categories
        ],
    )
    for page in all_pages:
        print(page.title())
        print(page.text[:1000])
