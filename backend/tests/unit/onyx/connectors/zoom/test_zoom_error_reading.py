"""How pruning reads a Zoom error, one answer at a time."""

import pytest
import requests

from onyx.connectors.zoom.recordings.models import (
    definitely_absent,
    user_does_not_exist,
    zoom_cannot_reach_back,
)
from tests.unit.onyx.connectors.zoom.helpers import http_error


class TestHowPruningReadsAZoomError:
    """A deletion and a retention refusal both mean nobody can be named, but
    pruning deletes on these answers, so it has to tell them apart, and a whole
    host may only go on Zoom's own no-such-user code, never on a bare 404."""

    @pytest.mark.parametrize(
        ("error", "session_absent", "user_gone", "too_old"),
        [
            (http_error(404, 1001), True, True, False),  # no such user
            (http_error(404), True, False, False),  # no code, such as from a proxy
            (http_error(404, 3301), True, False, False),  # never recorded
            (http_error(400, 3001), True, False, False),  # session was deleted
            (http_error(400, 12702), False, False, True),  # Zoom will not say
            (http_error(400, 200), False, False, False),  # the plan does not allow it
            (http_error(400, 300), False, False, False),  # some other bad request
            (http_error(429), False, False, False),
            (http_error(500), False, False, False),
        ],
    )
    def test_each_answer_is_read_one_way(
        self,
        error: requests.HTTPError,
        session_absent: bool,
        user_gone: bool,
        too_old: bool,
    ) -> None:
        assert definitely_absent(error) is session_absent
        assert user_does_not_exist(error) is user_gone
        assert zoom_cannot_reach_back(error) is too_old
