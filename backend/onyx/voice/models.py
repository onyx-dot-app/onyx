from pydantic import BaseModel, ConfigDict, JsonValue


class InworldAudioResult(BaseModel):
    model_config = ConfigDict(strict=True)

    audioContent: str = ""


class InworldAudioResponse(BaseModel):
    result: InworldAudioResult | None = None
    error: JsonValue = None


class InworldTranscription(BaseModel):
    model_config = ConfigDict(strict=True)

    transcript: str


class InworldTranscribeResponse(BaseModel):
    transcription: InworldTranscription
