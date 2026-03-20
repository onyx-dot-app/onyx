from typing import Any
from typing import ClassVar

from pydantic import BaseModel

from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint


_REQUIRED_ATTRS = (
    "hook_point",
    "display_name",
    "description",
    "default_timeout_seconds",
    "fail_hard_description",
    "default_fail_strategy",
    "payload_model",
    "response_model",
)


class HookPointSpec:
    """Static metadata and contract for a pipeline hook point.

    Each concrete subclass represents exactly one hook point and is instantiated
    once at startup, registered in onyx.hooks.registry._REGISTRY. Prefer
    get_hook_point_spec() or get_all_specs() from the registry over direct
    instantiation.

    Each hook point is a concrete subclass of this class. Onyx engineers
    own these definitions — customers never touch this code.

    Subclasses must define all attributes as class-level constants.
    payload_model and response_model must be Pydantic BaseModel subclasses;
    input_schema and output_schema are derived from them automatically.
    """

    hook_point: HookPoint
    display_name: str
    description: str
    default_timeout_seconds: float
    fail_hard_description: str
    default_fail_strategy: HookFailStrategy
    docs_url: str | None = None

    payload_model: ClassVar[type[BaseModel]]
    response_model: ClassVar[type[BaseModel]]

    # Computed once at class definition time from payload_model / response_model.
    input_schema: ClassVar[dict[str, Any]]
    output_schema: ClassVar[dict[str, Any]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        missing = [attr for attr in _REQUIRED_ATTRS if not hasattr(cls, attr)]
        if missing:
            raise TypeError(f"{cls.__name__} must define class attributes: {missing}")
        for attr in ("payload_model", "response_model"):
            val = getattr(cls, attr, None)
            if val is None or not (
                isinstance(val, type) and issubclass(val, BaseModel)
            ):
                raise TypeError(
                    f"{cls.__name__}.{attr} must be a Pydantic BaseModel subclass, got {val!r}"
                )
        cls.input_schema = cls.payload_model.model_json_schema()
        cls.output_schema = cls.response_model.model_json_schema()
