import asyncio
from collections.abc import AsyncIterator
from typing import Any
from xml.sax.saxutils import escape

import aiohttp

from onyx.voice.interface import StreamingSynthesizerProtocol
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
    """Streaming transcription using Azure Speech SDK.

    Note: Currently disabled (supports_streaming_stt returns False) because
    Azure STT requires 16kHz audio but clients send 24kHz. Needs audio
    resampling implementation before enabling.
    """

    def __init__(self, api_key: str, region: str):
        self.api_key = api_key
        self.region = region
        self._transcript_queue: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._accumulated_transcript = ""
        self._recognizer: Any = None
        self._audio_stream: Any = None
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Initialize Azure Speech recognizer with push stream."""
        import azure.cognitiveservices.speech as speechsdk

        self._loop = asyncio.get_running_loop()

        speech_config = speechsdk.SpeechConfig(
            subscription=self.api_key,
            region=self.region,
        )

        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=16000,
            bits_per_sample=16,
            channels=1,
        )
        self._audio_stream = speechsdk.audio.PushAudioInputStream(audio_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self._audio_stream)

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        transcriber = self

        def on_recognizing(evt: Any) -> None:
            if evt.result.text and transcriber._loop and not transcriber._closed:
                full_text = transcriber._accumulated_transcript
                if full_text:
                    full_text += " " + evt.result.text
                else:
                    full_text = evt.result.text
                transcriber._loop.call_soon_threadsafe(
                    transcriber._transcript_queue.put_nowait,
                    TranscriptResult(text=full_text, is_vad_end=False),
                )

        def on_recognized(evt: Any) -> None:
            if evt.result.text and transcriber._loop and not transcriber._closed:
                if transcriber._accumulated_transcript:
                    transcriber._accumulated_transcript += " " + evt.result.text
                else:
                    transcriber._accumulated_transcript = evt.result.text
                transcriber._loop.call_soon_threadsafe(
                    transcriber._transcript_queue.put_nowait,
                    TranscriptResult(
                        text=transcriber._accumulated_transcript, is_vad_end=True
                    ),
                )

        self._recognizer.recognizing.connect(on_recognizing)
        self._recognizer.recognized.connect(on_recognized)
        self._recognizer.start_continuous_recognition_async()

    async def send_audio(self, chunk: bytes) -> None:
        """Send audio chunk to Azure."""
        if self._audio_stream and not self._closed:
            self._audio_stream.write(chunk)

    async def receive_transcript(self) -> TranscriptResult | None:
        """Receive next transcript."""
        try:
            return await asyncio.wait_for(self._transcript_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return TranscriptResult(text="", is_vad_end=False)

    async def close(self) -> str:
        """Stop recognition and return final transcript."""
        self._closed = True
        if self._recognizer:
            self._recognizer.stop_continuous_recognition_async()
        if self._audio_stream:
            self._audio_stream.close()
        self._loop = None
        return self._accumulated_transcript

    def reset_transcript(self) -> None:
        """Reset accumulated transcript."""
        self._accumulated_transcript = ""


class AzureStreamingSynthesizer(StreamingSynthesizerProtocol):
    """Real-time streaming TTS using Azure Speech SDK."""

    def __init__(self, api_key: str, region: str, voice: str = "en-US-JennyNeural"):
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()
        self.api_key = api_key
        self.region = region
        self.voice = voice
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._synthesizer: Any = None
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Initialize Azure Speech synthesizer with push stream."""
        import azure.cognitiveservices.speech as speechsdk

        self._logger.info("AzureStreamingSynthesizer: connecting")

        # Store the event loop for thread-safe queue operations
        self._loop = asyncio.get_running_loop()

        speech_config = speechsdk.SpeechConfig(
            subscription=self.api_key,
            region=self.region,
        )
        speech_config.speech_synthesis_voice_name = self.voice
        # Use MP3 format for streaming - compatible with MediaSource Extensions
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz64KBitRateMonoMp3
        )

        # Create synthesizer with pull audio output stream
        self._synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None,  # We'll manually handle audio
        )

        # Connect to synthesis events
        self._synthesizer.synthesizing.connect(self._on_synthesizing)
        self._synthesizer.synthesis_completed.connect(self._on_completed)

        self._logger.info("AzureStreamingSynthesizer: connected")

    def _on_synthesizing(self, evt: Any) -> None:
        """Called when audio chunk is available (runs in Azure SDK thread)."""
        if evt.result.audio_data and self._loop and not self._closed:
            # Thread-safe way to put item in async queue
            self._loop.call_soon_threadsafe(
                self._audio_queue.put_nowait, evt.result.audio_data
            )

    def _on_completed(self, _evt: Any) -> None:
        """Called when synthesis is complete (runs in Azure SDK thread)."""
        if self._loop and not self._closed:
            self._loop.call_soon_threadsafe(self._audio_queue.put_nowait, None)

    async def send_text(self, text: str) -> None:
        """Send text to be synthesized."""
        if self._synthesizer and not self._closed:
            # Start synthesis asynchronously
            self._synthesizer.speak_text_async(text)

    async def receive_audio(self) -> bytes | None:
        """Receive next audio chunk."""
        try:
            return await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return b""  # No audio yet, but not done

    async def flush(self) -> None:
        """Signal end of text input - wait for pending audio."""
        # Azure SDK handles flushing automatically

    async def close(self) -> None:
        """Close the session."""
        self._closed = True
        if self._synthesizer:
            self._synthesizer.synthesis_completed.disconnect_all()
            self._synthesizer.synthesizing.disconnect_all()
        self._loop = None


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
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """
        Convert text to audio using Azure TTS with streaming.

        Args:
            text: Text to convert to speech
            voice: Voice name (defaults to provider's default voice)
            speed: Playback speed multiplier (0.5 to 2.0)

        Yields:
            Audio data chunks (mp3 format)
        """
        if not self.api_key:
            raise ValueError("Azure API key required for TTS")

        if not self.speech_region:
            raise ValueError("Azure speech region required for TTS")

        voice_name = voice or self.default_voice

        # Clamp speed to valid range and convert to rate format
        speed = max(0.5, min(2.0, speed))
        rate = f"{int((speed - 1) * 100):+d}%"  # e.g., 1.0 -> "+0%", 1.5 -> "+50%"

        # Build SSML with escaped text to prevent injection
        escaped_text = escape(text)
        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>
            <voice name='{voice_name}'>
                <prosody rate='{rate}'>{escaped_text}</prosody>
            </voice>
        </speak>"""

        url = f"https://{self.speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            "User-Agent": "Onyx",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=ssml) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"Azure TTS failed: {error_text}")

                # Use 8192 byte chunks for smoother streaming
                async for chunk in response.content.iter_chunked(8192):
                    if chunk:
                        yield chunk

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
        """Disabled until audio resampling is implemented (24kHz -> 16kHz)."""
        return False

    def supports_streaming_tts(self) -> bool:
        """Azure supports real-time streaming TTS via Speech SDK."""
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

    async def create_streaming_synthesizer(
        self, voice: str | None = None, _speed: float = 1.0
    ) -> AzureStreamingSynthesizer:
        """Create a streaming TTS session."""
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        if not self.speech_region:
            raise ValueError("Speech region required for Azure streaming TTS")
        synthesizer = AzureStreamingSynthesizer(
            api_key=self.api_key,
            region=self.speech_region,
            voice=voice or self.default_voice or "en-US-JennyNeural",
        )
        await synthesizer.connect()
        return synthesizer
