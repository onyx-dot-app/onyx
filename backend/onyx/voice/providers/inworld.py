"""Inworld file STT and HTTP-streamed MP3, including Onyx's chunked fallbacks."""

import base64
import binascii
from collections.abc import AsyncIterator, Iterator

import aiohttp
from pydantic import ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.voice.audio_utils import pcm16_to_wav
from onyx.voice.interface import VoiceProviderInterface
from onyx.voice.models import InworldAudioResponse, InworldTranscribeResponse

INWORLD_API_BASE = "https://api.inworld.ai"
INWORLD_STT_MODEL = "inworld/inworld-stt-1"
INWORLD_TTS_MODEL = "inworld-tts-2"
INWORLD_FLASH_MODEL = "inworld-tts-2-flash"
INWORLD_DEFAULT_VOICE = "Ashley"
MAX_TEXT_UNITS = 4000
# Leave room for Base64 and JSON below the sync API's documented ~16 MB limit.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_LINE_BYTES = 2 * 1024 * 1024


def split_inworld_text(text: str) -> Iterator[str]:
    """Keep every character while splitting at whitespace within the UTF-16 limit."""
    start = 0
    while start < len(text):
        end, units, boundary = start, 0, start
        while end < len(text):
            width = 2 if ord(text[end]) > 0xFFFF else 1
            if units + width > MAX_TEXT_UNITS:
                break
            units += width
            end += 1
            if text[end - 1].isspace():
                boundary = end
        if end < len(text) and boundary > start:
            end = boundary
        yield text[start:end]
        start = end


class InworldVoiceProvider(VoiceProviderInterface):
    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = (api_base or INWORLD_API_BASE).rstrip("/")
        self.stt_model = stt_model or INWORLD_STT_MODEL
        self.tts_model = tts_model or INWORLD_TTS_MODEL
        self.default_voice = default_voice or INWORLD_DEFAULT_VOICE
        if self.stt_model != INWORLD_STT_MODEL or self.tts_model not in {
            INWORLD_TTS_MODEL,
            INWORLD_FLASH_MODEL,
        }:
            raise ValueError("Unsupported Inworld speech model")

    def _session(self) -> aiohttp.ClientSession:
        if not self.api_key:
            raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "Inworld API key required")
        return aiohttp.ClientSession(
            headers={"Authorization": f"Basic {self.api_key}"},
            timeout=aiohttp.ClientTimeout(total=120, connect=10, sock_read=30),
            read_bufsize=MAX_RESPONSE_LINE_BYTES // 2,
        )

    @staticmethod
    def _check_response(response: aiohttp.ClientResponse) -> None:
        if response.status != 200:
            # Upstream bodies can contain request content; do not forward them.
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"Inworld request failed (HTTP {response.status}). Check credentials and quota.",
            )

    async def validate_credentials(self) -> None:
        async with self._session() as session:
            async with session.get(
                f"{self.api_base}/tts/v1/voices", allow_redirects=False
            ) as response:
                self._check_response(response)

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        if audio_format.lower() in {"pcm", "pcm16", "raw"}:
            audio_data = pcm16_to_wav(audio_data, sample_rate=24000)
        if not audio_data or len(audio_data) > MAX_AUDIO_BYTES:
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "Inworld requires nonempty audio up to 10 MiB.",
            )
        payload = {
            "transcribeConfig": {
                "modelId": self.stt_model,
                "audioEncoding": "AUTO_DETECT",
            },
            "audioData": {"content": base64.b64encode(audio_data).decode("ascii")},
        }
        with traced_llm_call(
            flow=LLMFlow.STT, model=self.stt_model, provider="inworld"
        ):
            async with self._session() as session:
                async with session.post(
                    f"{self.api_base}/stt/v1/transcribe",
                    json=payload,
                    allow_redirects=False,
                ) as response:
                    self._check_response(response)
                    try:
                        result = InworldTranscribeResponse.model_validate_json(
                            await response.read()
                        )
                    except ValidationError:
                        raise OnyxError(
                            OnyxErrorCode.BAD_GATEWAY,
                            "Invalid Inworld transcript response",
                        ) from None
                    return result.transcription.transcript

    def get_tts_max_speed(self) -> float:
        return 1.5

    async def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        if not 0.5 <= speed <= self.get_tts_max_speed():
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "Inworld supports playback speed from 0.5 to 1.5. Update your voice settings.",
            )
        with traced_llm_call(
            flow=LLMFlow.TTS, model=self.tts_model, provider="inworld"
        ):
            async with self._session() as session:
                for segment in split_inworld_text(text):
                    if not segment.strip():
                        continue
                    payload = {
                        "text": segment,
                        "voiceId": voice or self.default_voice,
                        "modelId": self.tts_model,
                        "audioConfig": {"audioEncoding": "MP3", "speakingRate": speed},
                    }
                    async with session.post(
                        f"{self.api_base}/tts/v1/voice:stream",
                        json=payload,
                        allow_redirects=False,
                    ) as response:
                        self._check_response(response)
                        received_audio = False
                        # aiohttp joins partial reads into lines and returns the final
                        # nonempty line at EOF. Its high-water limit bounds each line.
                        async for line in response.content:
                            if not line.strip():
                                continue
                            try:
                                packet = InworldAudioResponse.model_validate_json(line)
                                if packet.error is not None or packet.result is None:
                                    raise OnyxError(
                                        OnyxErrorCode.BAD_GATEWAY,
                                        "Inworld synthesis failed",
                                    )
                                audio = base64.b64decode(
                                    packet.result.audioContent, validate=True
                                )
                            except (ValidationError, binascii.Error, ValueError):
                                raise OnyxError(
                                    OnyxErrorCode.BAD_GATEWAY,
                                    "Invalid Inworld audio response",
                                ) from None
                            if audio:
                                received_audio = True
                                yield audio
                        if not received_audio:
                            raise OnyxError(
                                OnyxErrorCode.BAD_GATEWAY, "Inworld returned no audio"
                            )

    def get_available_voices(self) -> list[dict[str, str]]:
        return [{"id": INWORLD_DEFAULT_VOICE, "name": "Ashley"}]

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [{"id": INWORLD_STT_MODEL, "name": "Inworld STT"}]

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return [
            {"id": INWORLD_TTS_MODEL, "name": "Realtime TTS-2"},
            {"id": INWORLD_FLASH_MODEL, "name": "Realtime TTS-2 Flash"},
        ]
