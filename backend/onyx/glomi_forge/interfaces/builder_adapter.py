from collections.abc import Iterator
from typing import Protocol

from onyx.glomi_forge.schemas.builder import StartBuildInput
from onyx.glomi_forge.schemas.builder import StartBuildResult
from onyx.glomi_forge.schemas.events import ForgeEvent


class BuilderAdapter(Protocol):
    def start_build(self, input: StartBuildInput) -> StartBuildResult: ...

    def subscribe(self, builder_session_id: str) -> Iterator[ForgeEvent]: ...

    def stop(self, builder_session_id: str) -> None: ...
