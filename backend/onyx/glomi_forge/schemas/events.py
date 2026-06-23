"""Forge builder events normalized by the in-sandbox launcher."""

from typing import Annotated
from typing import Literal
from typing import TypeAlias
from typing import Union

from pydantic import BaseModel
from pydantic import Field
from pydantic import TypeAdapter


class BuilderStarted(BaseModel):
    type: Literal["builder_started"] = "builder_started"
    at: str


class MessageDelta(BaseModel):
    type: Literal["message_delta"] = "message_delta"
    at: str
    text: str


class FileChanged(BaseModel):
    type: Literal["file_changed"] = "file_changed"
    at: str
    path: str


class PreviewReady(BaseModel):
    type: Literal["preview_ready"] = "preview_ready"
    at: str
    port: int
    route: str | None = None


class ArtifactReady(BaseModel):
    type: Literal["artifact_ready"] = "artifact_ready"
    at: str
    manifest_path: str


class BuildBlocked(BaseModel):
    type: Literal["build_blocked"] = "build_blocked"
    at: str
    reason: str


class BuilderFailed(BaseModel):
    type: Literal["builder_failed"] = "builder_failed"
    at: str
    error: str


class BuilderFinished(BaseModel):
    type: Literal["builder_finished"] = "builder_finished"
    at: str
    success: bool = True


ForgeEvent: TypeAlias = Annotated[
    Union[
        BuilderStarted,
        MessageDelta,
        FileChanged,
        PreviewReady,
        ArtifactReady,
        BuildBlocked,
        BuilderFailed,
        BuilderFinished,
    ],
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[ForgeEvent] = TypeAdapter(ForgeEvent)


def parse_builder_event(raw: dict[str, object]) -> ForgeEvent:
    return _ADAPTER.validate_python(raw)
