from unittest.mock import Mock
from unittest.mock import patch

import pytest
from requests import HTTPError

from danswer.connectors.confluence.rate_limit_handler import (
    make_confluence_call_handle_rate_limit,
)


@pytest.fixture
def mock_confluence_call() -> Mock:
    return Mock()


@pytest.mark.parametrize(
    "status_code,text,retry_after",
    [
        (429, "Rate limit exceeded", "5"),
        (200, "Rate limit exceeded", None),
        (429, "Some other error", "5"),
    ],
)
def test_rate_limit_handling(
    mock_confluence_call: Mock, status_code: int, text: str, retry_after: str | None
) -> None:
    with patch("time.sleep") as mock_sleep:
        mock_confluence_call.side_effect = [
            HTTPError(
                response=Mock(
                    status_code=status_code,
                    text=text,
                    headers={"Retry-After": retry_after} if retry_after else {},
                )
            ),
        ] * 2 + ["Success"]

        handled_call = make_confluence_call_handle_rate_limit(mock_confluence_call)
        result = handled_call()

        assert result == "Success"
        assert mock_confluence_call.call_count == 3
        assert mock_sleep.call_count == 2
        if retry_after:
            mock_sleep.assert_called_with(int(retry_after))


def test_non_rate_limit_error(mock_confluence_call: Mock) -> None:
    mock_confluence_call.side_effect = HTTPError(
        response=Mock(status_code=500, text="Internal Server Error")
    )

    handled_call = make_confluence_call_handle_rate_limit(mock_confluence_call)

    with pytest.raises(HTTPError):
        handled_call()

    assert mock_confluence_call.call_count == 1
