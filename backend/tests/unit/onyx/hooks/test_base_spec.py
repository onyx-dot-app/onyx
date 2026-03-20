import pytest
from pydantic import BaseModel

from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


def test_init_subclass_raises_for_missing_attrs() -> None:
    with pytest.raises(TypeError, match="must define class attributes"):

        class IncompleteSpec(HookPointSpec):
            hook_point = HookPoint.QUERY_PROCESSING
            # missing display_name, description, payload_model, response_model, etc.

            class _Payload(BaseModel):
                pass

            payload_model = _Payload
            response_model = _Payload
