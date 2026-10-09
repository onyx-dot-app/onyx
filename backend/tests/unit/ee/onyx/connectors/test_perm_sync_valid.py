from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.connectors.perm_sync_valid import (
    source_has_perm_sync_probe,
    validate_perm_sync,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.zoom.connector import ZoomConnector


def test_probe_bearing_sources_derive_from_the_dispatch_table() -> None:
    """
    Verifies the predicate mirrors ``validate_perm_sync``'s dispatch for every
    sync-capable source: True iff the blob reaches a real probe.
    """
    # Under test and postcondition.
    probe_bearing = {
        source
        for source in (
            DocumentSource.BOX,
            DocumentSource.CANVAS,
            DocumentSource.CONFLUENCE,
            DocumentSource.GITHUB,
            DocumentSource.GMAIL,
            DocumentSource.GOOGLE_DRIVE,
            DocumentSource.JIRA,
            DocumentSource.LINEAR,
            DocumentSource.ONEDRIVE,
            DocumentSource.SHAREPOINT,
            DocumentSource.SLACK,
            DocumentSource.TEAMS,
            DocumentSource.ZOOM,
        )
        if source_has_perm_sync_probe(source)
    }
    assert probe_bearing == {
        DocumentSource.BOX,
        DocumentSource.CANVAS,
        DocumentSource.CONFLUENCE,
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.ONEDRIVE,
        DocumentSource.SHAREPOINT,
        DocumentSource.ZOOM,
    }


@pytest.mark.parametrize(
    "connector_class, probes",
    [
        (
            CanvasConnector,
            [
                "probe_course_user_email_visibility",
                "probe_account_user_listing_permission",
            ],
        ),
        (ZoomConnector, ["probe_recording_access_permissions"]),
    ],
    ids=["canvas", "zoom"],
)
def test_dispatch_reaches_the_matching_validator(
    connector_class: type[BaseConnector], probes: list[str]
) -> None:
    """Verifies the dict dispatch preserves the old isinstance behavior."""
    # Precondition.
    connector = MagicMock(spec=connector_class)

    # Under test.
    validate_perm_sync(connector)

    # Postcondition.
    assert sorted(name for name, _, _ in connector.method_calls) == sorted(probes)


def test_dispatch_is_a_noop_for_probeless_connectors() -> None:
    """Verifies connectors outside the dispatch table validate as a no-op."""
    # Under test and postcondition (nothing raises, nothing is probed).
    validate_perm_sync(MagicMock(spec=BaseConnector))


def test_linear_probes_the_viewer_on_the_connectors_own_credential() -> None:
    """The EE twin reads the factory-built connector's credential: a guest
    token fails before a scheduled sync hides every issue outside its teams."""
    connector = LinearConnector(team_keys=["ENG"])
    connector.load_credentials({"linear_api_key": "lin_api_test"})
    guest = MagicMock()
    guest.json.return_value = {"data": {"viewer": {"guest": True}}}

    with (
        patch("onyx.connectors.linear.connector._make_query", return_value=guest),
        pytest.raises(InsufficientPermissionsError, match="guest"),
    ):
        validate_perm_sync(connector)
