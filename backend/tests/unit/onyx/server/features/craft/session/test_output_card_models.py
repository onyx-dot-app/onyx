"""Viewed acknowledgements fit the maximum live output inventory."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    MANIFEST_MAX_ENTRIES,
)
from onyx.server.features.build.session.models import OutputsViewedRequest


@pytest.mark.parametrize("count", [0, MANIFEST_MAX_ENTRIES])
def test_viewed_request_accepts_a_complete_live_inventory(count: int) -> None:
    revisions = {UUID(int=index): 1 for index in range(count)}
    assert OutputsViewedRequest(revisions=revisions).revisions == revisions


def test_viewed_request_rejects_oversized_inventory() -> None:
    revisions = {UUID(int=index): 1 for index in range(MANIFEST_MAX_ENTRIES + 1)}
    with pytest.raises(ValidationError) as error:
        OutputsViewedRequest(revisions=revisions)
    assert error.value.errors()[0]["type"] == "too_long"
