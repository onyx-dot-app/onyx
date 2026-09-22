"""Feature-owned data captured at safe execution boundaries."""

from typing import Protocol

from pydantic import BaseModel


class FeatureRestoration(Protocol):
    def capture_state(self) -> BaseModel: ...

    def restore_state(self, state: BaseModel) -> None: ...
