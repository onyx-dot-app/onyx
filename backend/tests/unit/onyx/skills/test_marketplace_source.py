import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.marketplace_models import MarketplaceSourceRequest


def test_owner_and_repository_are_stored_in_lower_case() -> None:
    config = MarketplaceSourceRequest(repository="ACME/Plugin-Tools").to_config()
    assert (config.owner, config.repo) == ("acme", "plugin-tools")


def test_bad_folder_gives_a_plain_message() -> None:
    with pytest.raises(OnyxError) as exc:
        MarketplaceSourceRequest(repository="acme/tools", folder="../up").to_config()
    assert (
        exc.value.detail == "Use a folder path in the repository, with no '.' or '..'."
    )
