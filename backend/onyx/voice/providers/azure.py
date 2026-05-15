"""Azure Speech Services voice provider for STT and TTS.

Azure supports:
- **STT**: Batch transcription via REST API (audio/wav POST) and real-time
  streaming via the Azure Speech SDK (push audio stream with continuous
  recognition). The SDK handles VAD natively through its recognizing/recognized
  events.
- **TTS**: SSML-based synthesis via REST API (streaming response) and real-time
  synthesis via the Speech SDK. Text is escaped with ``xml.sax.saxutils.escape``
  and attributes with ``quoteattr`` to prevent SSML injection.

Both modes support Azure cloud endpoints (region-based URLs) and self-hosted
Speech containers (custom endpoint URLs). The ``speech_region`` is validated to
contain only ``[a-z0-9-]`` to prevent URL injection.

The Azure Speech SDK (``azure-cognitiveservices-speech``) is an optional C
extension dependency — it is imported lazily inside streaming methods so the
provider can still be instantiated and used for REST-based operations without it.

See https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/
for API reference.
"""

import asyncio
import io
import re
import struct
import wave
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse
from xml.sax.saxutils import escape
from xml.sax.saxutils import quoteattr

import aiohttp

from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.utils.logger import setup_logger
from onyx.voice.interface import StreamingSynthesizerProtocol
from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult
from onyx.voice.interface import VoiceProviderInterface

# SSML namespace — W3C standard for Speech Synthesis Markup Language.
# This is a fixed W3C specification and will not change.
SSML_NAMESPACE = "http://www.w3.org/2001/10/synthesis"

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

    def __init__(
        self,
        api_key: str,
        region: str | None = None,
        endpoint: str | None = None,
        input_sample_rate: int = 24000,
        target_sample_rate: int = 16000,
    ):
        self.api_key = api_key
        self.region = region
        self.endpoint = endpoint
        self.input_sample_rate = input_sample_rate
        self.target_sample_rate = target_sample_rate
        self._transcript_queue: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._accumulated_transcript = ""
        self._recognizer: Any = None
        self._audio_stream: Any = None
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Initialize Azure Speech recognizer with push stream."""
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as e:
            raise RuntimeError(
                "Azure Speech SDK is required for streaming STT. Install `azure-cognitiveservices-speech`."
            ) from e

        self._loop = asyncio.get_running_loop()

        # Use endpoint for self-hosted containers, region for Azure cloud
        if self.endpoint:
            speech_config = speechsdk.SpeechConfig(
                subscription=self.api_key,
                endpoint=self.endpoint,
            )
        else:
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
            self._audio_stream.write(self._resample_pcm16(chunk))

    def _resample_pcm16(self, data: bytes) -> bytes:
        """Resample PCM16 audio from input_sample_rate to target_sample_rate."""
        if self.input_sample_rate == self.target_sample_rate:
            return data

        num_samples = len(data) // 2
        if num_samples == 0:
            return b""

        samples = list(struct.unpack(f"<{num_samples}h", data))
        ratio = self.input_sample_rate / self.target_sample_rate
        new_length = int(num_samples / ratio)

        resampled: list[int] = []
        for i in range(new_length):
            src_idx = i * ratio
            idx_floor = int(src_idx)
            idx_ceil = min(idx_floor + 1, num_samples - 1)
            frac = src_idx - idx_floor
            sample = int(samples[idx_floor] * (1 - frac) + samples[idx_ceil] * frac)
            sample = max(-32768, min(32767, sample))
            resampled.append(sample)

        return struct.pack(f"<{len(resampled)}h", *resampled)

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

    def __init__(
        self,
        api_key: str,
        region: str | None = None,
        endpoint: str | None = None,
        voice: str = "en-US-JennyNeural",
        speed: float = 1.0,
    ):
        self._logger = setup_logger()
        self.api_key = api_key
        self.region = region
        self.endpoint = endpoint
        self.voice = voice
        self.speed = max(0.5, min(2.0, speed))
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._synthesizer: Any = None
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Initialize Azure Speech synthesizer with push stream."""
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as e:
            raise RuntimeError(
                "Azure Speech SDK is required for streaming TTS. Install `azure-cognitiveservices-speech`."
            ) from e

        self._logger.info("AzureStreamingSynthesizer: connecting")

        # Store the event loop for thread-safe queue operations
        self._loop = asyncio.get_running_loop()

        # Use endpoint for self-hosted containers, region for Azure cloud
        if self.endpoint:
            speech_config = speechsdk.SpeechConfig(
                subscription=self.api_key,
                endpoint=self.endpoint,
            )
        else:
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
        """Send text to be synthesized using SSML for prosody control."""
        if self._synthesizer and not self._closed:
            # Build SSML with prosody for speed control
            rate = f"{int((self.speed - 1) * 100):+d}%"
            escaped_text = escape(text)
            ssml = f"""<speak version='1.0' xmlns='{SSML_NAMESPACE}' xml:lang='en-US'>
                <voice name={quoteattr(self.voice)}>
                    <prosody rate='{rate}'>{escaped_text}</prosody>
                </voice>
            </speak>"""
            # Use speak_ssml_async for SSML support (includes speed/prosody)
            self._synthesizer.speak_ssml_async(ssml)

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
        api_base: str | None,
        custom_config: dict[str, Any],
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base
        self.custom_config = custom_config
        raw_speech_region = (
            custom_config.get("speech_region")
            or self._extract_speech_region_from_uri(api_base)
            or ""
        )
        self.speech_region = self._validate_speech_region(raw_speech_region)
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.default_voice = default_voice or "en-US-JennyNeural"

    @staticmethod
    def _is_azure_cloud_url(uri: str | None) -> bool:
        """Check if URI is an Azure cloud endpoint (vs custom/self-hosted)."""
        if not uri:
            return False
        try:
            hostname = (urlparse(uri).hostname or "").lower()
        except ValueError:
            return False
        return hostname.endswith(
            (
                ".speech.microsoft.com",
                ".api.cognitive.microsoft.com",
                ".cognitiveservices.azure.com",
            )
        )

    @staticmethod
    def _extract_speech_region_from_uri(uri: str | None) -> str | None:
        """Extract Azure speech region from endpoint URI.

        Note: Custom domains (*.cognitiveservices.azure.com) contain the resource
        name, not the region. For custom domains, the region must be specified
        explicitly via custom_config["speech_region"].
        """
        if not uri:
            return None
        # Accepted examples:
        # - https://eastus.tts.speech.microsoft.com/cognitiveservices/v1
        # - https://eastus.stt.speech.microsoft.com/speech/recognition/...
        # - https://westus.api.cognitive.microsoft.com/
        #
        # NOT supported (requires explicit speech_region config):
        # - https://<resource>.cognitiveservices.azure.com/ (resource name != region)
        try:
            hostname = (urlparse(uri).hostname or "").lower()
        except ValueError:
            return None

        stt_tts_match = re.match(
            r"^([a-z0-9-]+)\.(?:tts|stt)\.speech\.microsoft\.com$", hostname
        )
        if stt_tts_match:
            return stt_tts_match.group(1)

        api_match = re.match(
            r"^([a-z0-9-]+)\.api\.cognitive\.microsoft\.com$", hostname
        )
        if api_match:
            return api_match.group(1)

        return None

    @staticmethod
    def _validate_speech_region(speech_region: str) -> str:
        normalized_region = speech_region.strip().lower()
        if not normalized_region:
            return ""
        if not re.fullmatch(r"[a-z0-9-]+", normalized_region):
            raise ValueError(
                "Invalid Azure speech_region. Use lowercase letters, digits, and hyphens only."
            )
        return normalized_region

    def _get_stt_url(self) -> str:
        """Get the STT endpoint URL (auto-detects cloud vs self-hosted)."""
        if self.api_base and not self._is_azure_cloud_url(self.api_base):
            # Self-hosted container endpoint
            return f"{self.api_base.rstrip('/')}/speech/recognition/conversation/cognitiveservices/v1"
        # Azure cloud endpoint
        return f"https://{self.speech_region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"

    def _get_tts_url(self) -> str:
        """Get the TTS endpoint URL (auto-detects cloud vs self-hosted)."""
        if self.api_base and not self._is_azure_cloud_url(self.api_base):
            # Self-hosted container endpoint
            return f"{self.api_base.rstrip('/')}/cognitiveservices/v1"
        # Azure cloud endpoint
        return f"https://{self.speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def _is_self_hosted(self) -> bool:
        """Check if using self-hosted container vs Azure cloud."""
        return bool(self.api_base and not self._is_azure_cloud_url(self.api_base))

    @staticmethod
    def _pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
        """Wrap raw PCM16 mono bytes into a WAV container."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return buffer.getvalue()

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        if not self.api_key:
            raise ValueError("Azure API key required for STT")
        if not self._is_self_hosted() and not self.speech_region:
            raise ValueError("Azure speech region required for STT (cloud mode)")

        normalized_format = audio_format.lower()
        payload = audio_data
        content_type = f"audio/{normalized_format}"

        # WebSocket chunked fallback sends raw PCM16 bytes.
        if normalized_format in {"pcm", "pcm16", "raw"}:
            payload = self._pcm16_to_wav(audio_data, sample_rate=24000)
            content_type = "audio/wav"
        elif normalized_format in {"wav", "wave"}:
            content_type = "audio/wav"
        elif normalized_format == "webm":
            content_type = "audio/webm; codecs=opus"

        url = self._get_stt_url()
        params = {"language": "en-US", "format": "detailed"}
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": content_type,
            "Accept": "application/json",
        }

        with traced_llm_call(
            flow=LLMFlow.STT,
            model=self.stt_model or "azure-speech-stt",
            provider="azure",
        ):
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, params=params, headers=headers, data=payload
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"Azure STT failed: {error_text}")
                    result = await response.json()

        if result.get("RecognitionStatus") != "Success":
            return ""
        nbest = result.get("NBest") or []
        if nbest and isinstance(nbest, list):
            display = nbest[0].get("Display")
            if isinstance(display, str):
                return display
        display_text = result.get("DisplayText", "")
        return display_text if isinstance(display_text, str) else ""

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

        if not self._is_self_hosted() and not self.speech_region:
            raise ValueError("Azure speech region required for TTS (cloud mode)")

        voice_name = voice or self.default_voice

        # Clamp speed to valid range and convert to rate format
        speed = max(0.5, min(2.0, speed))
        rate = f"{int((speed - 1) * 100):+d}%"  # e.g., 1.0 -> "+0%", 1.5 -> "+50%"

        # Build SSML with escaped text and quoted attributes to prevent injection
        escaped_text = escape(text)
        ssml = f"""<speak version='1.0' xmlns='{SSML_NAMESPACE}' xml:lang='en-US'>
            <voice name={quoteattr(voice_name)}>
                <prosody rate='{rate}'>{escaped_text}</prosody>
            </voice>
        </speak>"""

        url = self._get_tts_url()

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
            "User-Agent": "Onyx",
        }

        with traced_llm_call(
            flow=LLMFlow.TTS,
            model=self.tts_model or "azure-speech-tts",
            provider="azure",
            input_messages=[{"role": "user", "content": text}],
        ):
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=ssml) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"Azure TTS failed: {error_text}")

                    # Use 8192 byte chunks for smoother streaming
                    async for chunk in response.content.iter_chunked(8192):
                        if chunk:
                            yield chunk

    async def validate_credentials(self) -> None:
        """Validate Azure credentials by listing available voices."""
        if not self.api_key:
            raise ValueError("Azure API key required")
        if not self._is_self_hosted() and not self.speech_region:
            raise ValueError("Azure speech region required (cloud mode)")

        url = f"https://{self.speech_region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        if self._is_self_hosted():
            url = f"{(self.api_base or '').rstrip('/')}/cognitiveservices/voices/list"

        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status in (401, 403):
                    raise RuntimeError("Invalid Azure API key.")
                if response.status != 200:
                    raise RuntimeError("Azure credential validation failed.")

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
        """Azure supports streaming STT via Speech SDK."""
        return True

    def supports_streaming_tts(self) -> bool:
        """Azure supports real-time streaming TTS via Speech SDK."""
        return True

    async def create_streaming_transcriber(  # ty: ignore[invalid-method-override]
        self, _audio_format: str = "webm"
    ) -> AzureStreamingTranscriber:
        """Create a streaming transcription session."""
        if not self.api_key:
            raise ValueError("API key required for streaming transcription")
        if not self._is_self_hosted() and not self.speech_region:
            raise ValueError(
                "Speech region required for Azure streaming transcription (cloud mode)"
            )

        # Use endpoint for self-hosted, region for cloud
        transcriber = AzureStreamingTranscriber(
            api_key=self.api_key,
            region=self.speech_region if not self._is_self_hosted() else None,
            endpoint=self.api_base if self._is_self_hosted() else None,
            input_sample_rate=24000,
            target_sample_rate=16000,
        )
        await transcriber.connect()
        return transcriber

    async def create_streaming_synthesizer(
        self, voice: str | None = None, speed: float = 1.0
    ) -> AzureStreamingSynthesizer:
        """Create a streaming TTS session."""
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        if not self._is_self_hosted() and not self.speech_region:
            raise ValueError(
                "Speech region required for Azure streaming TTS (cloud mode)"
            )

        # Use endpoint for self-hosted, region for cloud
        synthesizer = AzureStreamingSynthesizer(
            api_key=self.api_key,
            region=self.speech_region if not self._is_self_hosted() else None,
            endpoint=self.api_base if self._is_self_hosted() else None,
            voice=voice or self.default_voice or "en-US-JennyNeural",
            speed=speed,
        )
        await synthesizer.connect()
        return synthesizer
