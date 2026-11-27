"""The validate route takes the same spec size limit as create and update."""

from unittest.mock import MagicMock

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool.api import ValidateToolRequest, validate_tool


def test_validate_refuses_a_spec_over_the_size_limit() -> None:
    definition = {
        "openapi": "3.0.0",
        "info": {
            "title": "big",
            "version": "1",
            "description": "x" * (6 * 1024 * 1024),
        },
        "paths": {},
    }
    with pytest.raises(OnyxError) as raised:
        validate_tool(ValidateToolRequest(definition=definition), MagicMock())
    assert raised.value.error_code is OnyxErrorCode.PAYLOAD_TOO_LARGE
