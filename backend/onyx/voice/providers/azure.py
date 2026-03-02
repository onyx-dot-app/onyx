import asyncio
from collections.abc import AsyncIterator
from typing import Any

from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult
from onyx.voice.interface import VoiceProviderInterface

# Common Azure Neural voices
AZURE_VOICES = [
    {"id": "en-US-JennyNeural", "name": "Jenny (en-US, Female)"},
    {"id": "en-US-GuyNeural", "name": "Guy (en-US, Male)"},
    {"id": "en-US-AriaNeural", "name": "Aria (en-US, Female)"},
    {"id": "en-US-DavisNeural", "name": "Davis (en-US, Male)"},
    {"id": "en-US-AmberNeural", "name": "Amber (en-US, Female)"},
    {"id": "en-US-AnaNeural", "name": "Ana (en-US, Female)"},
    {"id": "en-US-BrandonNeural", "name": "Brandon (en-US, Male)"},
    {"id": "en-US-ChristopherNeural", "name": "Christopher (en-US, Male)"},
    {"id": "en-US-CoraNeural", "name": "Cora (en-US, Female)"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (en-GB, Female)"},
    {"id": "en-GB-RyanNeural", "name": "Ryan (en-GB, Male)"},
]


class AzureStreamingTranscriber(StreamingTranscriberProtocol):
    """Streaming transcription using Azure Speech SDK."""

    def __init__(self, api_key: str, region: str):
        self.api_key = api_key
        self.region = region
        self._transcript_queue: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._accumulated_transcript = ""
        self._recognizer: Any = None
        self._audio_stream: Any = None
        self._closed = False

    async def connect(self) -> None:
        """Initialize Azure Speech recognizer with push stream."""
        import azure.cognitiveservices.speech as speechsdk

        # Create speech config
        speech_config = speechsdk.SpeechConfig(
            subscription=self.api_key,
            region=self.region,
        )

        # Create push stream for audio input
        # Using 16kHz, 16-bit mono PCM format
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=16000,
            bits_per_sample=16,
            channels=1,
        )
        self._audio_stream = speechsdk.audio.PushAudioInputStream(audio_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self._audio_stream)

        # Create recognizer
        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        # Set up event handlers
        def on_recognizing(evt: Any) -> None:
            """Handle partial recognition results."""
            if evt.result.text:
                # Show accumulated + current partial
                full_text = self._accumulated_transcript
                if full_text:
                    full_text += " " + evt.result.text
                else:
                    full_text = evt.result.text
                asyncio.get_event_loop().call_soon_threadsafe(
                    self._transcript_queue.put_nowait,
                    TranscriptResult(text=full_text, is_vad_end=False),
                )

        def on_recognized(evt: Any) -> None:
            """Handle final recognition results (VAD detected end of utterance)."""
            if evt.result.text:
                # Accumulate this utterance
                if self._accumulated_transcript:
                    self._accumulated_transcript += " " + evt.result.text
                else:
                    self._accumulated_transcript = evt.result.text
                asyncio.get_event_loop().call_soon_threadsafe(
                    self._transcript_queue.put_nowait,
                    TranscriptResult(
                        text=self._accumulated_transcript, is_vad_end=True
                    ),
                )

        self._recognizer.recognizing.connect(on_recognizing)
        self._recognizer.recognized.connect(on_recognized)

        # Start continuous recognition
        self._recognizer.start_continuous_recognition_async()

    async def send_audio(self, chunk: bytes) -> None:
        """Send audio chunk to Azure."""
        if self._audio_stream and not self._closed:
            # Azure expects raw PCM audio, but we might receive webm
            # For now, just write the bytes - proper format conversion may be needed
            self._audio_stream.write(chunk)

    async def receive_transcript(self) -> TranscriptResult | None:
        """Receive next transcript."""
        try:
            return await asyncio.wait_for(self._transcript_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return TranscriptResult(text="", is_vad_end=False)  # No transcript yet

    async def close(self) -> str:
        """Stop recognition and return final transcript."""
        self._closed = True
        if self._recognizer:
            self._recognizer.stop_continuous_recognition_async()
        if self._audio_stream:
            self._audio_stream.close()
        return self._accumulated_transcript

    def reset_transcript(self) -> None:
        """Reset accumulated transcript. Call after auto-send to start fresh."""
        self._accumulated_transcript = ""


class AzureVoiceProvider(VoiceProviderInterface):
    """Azure Speech Services voice provider."""

    def __init__(
        self,
        api_key: str | None,
        custom_config: dict[str, Any],
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.custom_config = custom_config
        self.speech_region = custom_config.get("speech_region", "")
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.default_voice = default_voice or "en-US-JennyNeural"

    async def transcribe(self, _audio_data: bytes, _audio_format: str) -> str:
        raise NotImplementedError("Azure STT not yet implemented")

    async def synthesize_stream(
        self, _text: str, _voice: str | None = None, _speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("Azure TTS not yet implemented")
        yield b""  # Required for async generator

    def get_available_voices(self) -> list[dict[str, str]]:
        """Return common Azure Neural voices."""
        return AZURE_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [
            {"id": "default", "name": "Azure Speech Recognition"},
        ]

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return [
            {"id": "neural", "name": "Neural TTS"},
        ]

    def supports_streaming_stt(self) -> bool:
        return True

    async def create_streaming_transcriber(
        self, _audio_format: str = "webm"
    ) -> AzureStreamingTranscriber:
        """Create a streaming transcription session."""
        if not self.api_key:
            raise ValueError("API key required for streaming transcription")
        if not self.speech_region:
            raise ValueError("Speech region required for Azure streaming transcription")
        transcriber = AzureStreamingTranscriber(
            api_key=self.api_key,
            region=self.speech_region,
        )
        await transcriber.connect()
        return transcriber
