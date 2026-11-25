import importlib
import inspect
import pkgutil

import onyx.tools.tool_implementations as tool_implementations
from onyx.tools.interface import Tool
from onyx.tools.ordering import ToolRank


def _subclasses(cls: type[Tool]) -> list[type[Tool]]:
    return [
        found
        for subclass in cls.__subclasses__()
        for found in (subclass, *_subclasses(subclass))
    ]


def test_every_tool_class_declares_its_rank() -> None:
    for module in pkgutil.walk_packages(
        tool_implementations.__path__, f"{tool_implementations.__name__}."
    ):
        importlib.import_module(module.name)
    tool_classes = [
        cls
        for cls in _subclasses(Tool)
        if cls.__module__.startswith(("onyx.", "ee.")) and not inspect.isabstract(cls)
    ]

    assert tool_classes
    unranked = [
        cls.__qualname__
        for cls in tool_classes
        if not any(isinstance(vars(base).get("rank"), ToolRank) for base in cls.__mro__)
    ]
    assert not unranked, f"Tool classes without a rank: {unranked}"
