from typing import Any

import pytest

from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec


def test_init_subclass_raises_for_missing_attrs() -> None:
    with pytest.raises(TypeError, match="must define class attributes"):

        class IncompleteSpec(HookPointSpec):
            hook_point = HookPoint.QUERY_PROCESSING
            # missing display_name, description, etc.

            @property
            def input_schema(self) -> dict[str, Any]:
                return {}

            @property
            def output_schema(self) -> dict[str, Any]:
                return {}
