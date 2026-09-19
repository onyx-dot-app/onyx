import re

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.url_glob import UrlGlob


def _matches(glob: str, url: str) -> bool:
    return re.fullmatch(UrlGlob(value=glob).to_regex(), url) is not None


def test_dot_is_literal_not_wildcard() -> None:
    # The dot in the host must not match arbitrary characters.
    assert _matches("https://discord.com/api/v10", "https://discord.com/api/v10")
    assert not _matches("https://discord.com/api/v10", "https://discordxcom/api/v10")


def test_star_matches_full_path_including_slashes() -> None:
    # Regression: `/api/*` must cover deep paths, not just one segment — this is
    # the bug that caused Discord 401s when the glob was matched as a raw regex.
    assert _matches(
        "https://discord.com/api/*", "https://discord.com/api/v10/users/@me"
    )
    assert _matches("https://discord.com/api/*", "https://discord.com/api/")
    # The literal prefix is still required.
    assert not _matches("https://discord.com/api/*", "https://discord.com/apiv2/users")


def test_star_in_middle() -> None:
    glob = "https://api.github.com/repos/*/issues"
    assert _matches(glob, "https://api.github.com/repos/onyx/issues")
    assert not _matches(glob, "https://api.github.com/repos/onyx/pulls")


def test_exact_pattern_matches_only_itself() -> None:
    glob = "https://api.example.com/health"
    assert _matches(glob, "https://api.example.com/health")
    assert not _matches(glob, "https://api.example.com/health/sub")


def test_query_string_metachars_are_literal() -> None:
    glob = "https://api.example.com/search?q=*"
    assert _matches(glob, "https://api.example.com/search?q=anything")
    # `?` is literal, so a URL without it doesn't match.
    assert not _matches(glob, "https://api.example.com/searchXq=anything")


@pytest.mark.parametrize(
    "bad_glob",
    [
        "",
        "   ",
        "discord.com/api/*",  # no scheme
        "ftp://discord.com/*",  # wrong scheme
        "https://*.example.com/*",  # wildcard host
        "https://*/api",  # wildcard host
        "https:///api",  # missing host
    ],
)
def test_parse_rejects_unsafe_globs(bad_glob: str) -> None:
    with pytest.raises(OnyxError):
        UrlGlob.parse(bad_glob)


def test_parse_accepts_literal_host_globs() -> None:
    assert (
        UrlGlob.parse("https://api.example.com/*").value == "https://api.example.com/*"
    )
    UrlGlob.parse("http://localhost:8080/v1/*")
