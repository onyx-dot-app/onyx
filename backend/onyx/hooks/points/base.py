from abc import ABC
from abc import abstractmethod
from typing import Any

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint


_REQUIRED_ATTRS = (
    "hook_point",
    "display_name",
    "description",
    "default_timeout_seconds",
    "fail_hard_description",
    "default_fail_strategy",
)


class HookPointSpec(ABC):
    """Static metadata and contract for a pipeline hook point.

    Each hook point is a concrete subclass of this class. Onyx engineers
    own these definitions — customers never touch this code.

    Instances are registered in onyx.hooks.registry._REGISTRY and served
    via GET /api/admin/hook-points.

    Subclasses must define all attributes as class-level constants.
    """

    hook_point: HookPoint
    display_name: str
    description: str
    default_timeout_seconds: float
    fail_hard_description: str
    default_fail_strategy: HookFailStrategy
    docs_url: str | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Skip intermediate abstract subclasses — they may still be partially defined.
        if getattr(cls, "__abstractmethods__", None):
            return
        missing = [attr for attr in _REQUIRED_ATTRS if not hasattr(cls, attr)]
        if missing:
            raise TypeError(f"{cls.__name__} must define class attributes: {missing}")

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON schema describing the request payload sent to the customer's endpoint."""

    @property
    @abstractmethod
    def output_schema(self) -> dict[str, Any]:
        """JSON schema describing the expected response from the customer's endpoint."""
