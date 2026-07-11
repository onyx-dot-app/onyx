"""WebSocket API for streaming speech-to-text and text-to-speech."""

import asyncio
import io
import json
import os
from collections.abc import MutableMapping
from typing import Any

import numpy as np
from fastapi import APIRouter
from fastapi import Depends
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from sqlalchemy.orm import Session

from onyx.auth.users import current_user_from_websocket
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.models import User
from onyx.db.voice import fetch_default_stt_provider
from onyx.db.voice import fetch_default_tts_provider
from onyx.server.manage.voice.text_utils import strip_markdown_for_tts
from onyx.utils.logger import setup_logger
from onyx.voice.factory import get_voice_provider
from onyx.voice.interface import StreamingSynthesizerProtocol
from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult

logger = setup_logger()

router = APIRouter(prefix="/voice")


# Byte threshold for non-PCM formats, where the audio can't be analyzed server-side
MIN_CHUNK_BYTES = 1500

# The browser recorder sends raw PCM16 mono at 24kHz
PCM_SAMPLE_RATE = 24000
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * 2

# Whisper-style models pad short inputs to a 30s window and hallucinate
# training-data boilerplate (e.g. broadcast sign-offs) on silence/padding, so
# PCM audio is transcribed in multi-second windows and windows without speech
# are dropped without calling the provider.
PCM_TRANSCRIBE_WINDOW_BYTES = PCM_BYTES_PER_SECOND * 3

# int16 RMS below this (~-46 dBFS) is treated as silence. Speech is typically
# an order of magnitude above; quiet-room mic noise well below.
SILENCE_RMS_THRESHOLD = 150.0

# Absolute floor (~-61 dBFS) for the low-gain fallback in
# _speech_rms_threshold — audio quieter than this everywhere is silence.
MIN_SPEECH_RMS = 30.0

# Low-gain fallback: quiet audio counts as speech only when its loudest
# frames stand at least this far (~8dB) above the recording's own noise
# floor. Speech has strong dynamics (pauses between words); steady mic noise
# stays near 1x. Below this, an empty transcript (visible, recoverable) is
# deliberately preferred over risking hallucinated text.
SPEECH_DYNAMICS_RATIO = 2.5

# Audio kept around detected speech when trimming silence off a full recording
SILENCE_TRIM_PADDING_SECONDS = 0.5


def pcm16_rms(audio: bytes) -> float:
    """RMS amplitude of raw little-endian PCM16 audio (0.0 for empty input)."""
    usable = len(audio) - (len(audio) % 2)
    if usable == 0:
        return 0.0
    samples = np.frombuffer(audio[:usable], dtype=np.int16).astype(np.float64)
    return float(np.sqrt(np.mean(samples * samples)))


def _speech_rms_threshold(frame_rms_values: list[float]) -> float | None:
    """RMS threshold separating speech frames from silence for a recording.

    Uses SILENCE_RMS_THRESHOLD when the recording reaches it. Otherwise falls
    back to a relative test so quiet input from a low-gain microphone still
    counts as speech when it stands well out of the recording's own noise
    floor. Returns None when the recording contains no speech-like content.
    """
    if not frame_rms_values:
        return None
    peak = max(frame_rms_values)
    if peak >= SILENCE_RMS_THRESHOLD:
        return SILENCE_RMS_THRESHOLD
    if peak < MIN_SPEECH_RMS:
        return None
    noise_floor = max(
        sorted(frame_rms_values)[len(frame_rms_values) // 10], 1.0
    )  # 10th percentile
    if peak >= SPEECH_DYNAMICS_RATIO * noise_floor:
        return max(MIN_SPEECH_RMS, peak / SPEECH_DYNAMICS_RATIO)
    return None


def trim_pcm16_silence(audio: bytes) -> bytes:
    """Trim leading/trailing silence from raw PCM16 audio.

    Analyzes the audio in 100ms frames and keeps everything from the first to
    the last speech frame (per _speech_rms_threshold), plus padding. Returns
    b"" if no frame contains speech.
    """
    frame_bytes = PCM_BYTES_PER_SECOND // 10
    if frame_bytes == 0 or not audio:
        return audio

    frame_offsets = range(0, len(audio), frame_bytes)
    frame_rms_values = [
        pcm16_rms(audio[idx : idx + frame_bytes]) for idx in frame_offsets
    ]
    threshold = _speech_rms_threshold(frame_rms_values)
    if threshold is None:
        return b""

    speech_frame_indices = [
        idx
        for idx, frame_rms in zip(frame_offsets, frame_rms_values)
        if frame_rms >= threshold
    ]
    if not speech_frame_indices:
        return b""

    padding_bytes = int(PCM_BYTES_PER_SECOND * SILENCE_TRIM_PADDING_SECONDS)
    start = max(0, speech_frame_indices[0] - padding_bytes)
    end = min(len(audio), speech_frame_indices[-1] + frame_bytes + padding_bytes)
    # Keep sample alignment
    start -= start % 2
    return audio[start:end]


VOICE_DISABLE_STREAMING_FALLBACK = (
    os.environ.get("VOICE_DISABLE_STREAMING_FALLBACK", "").lower() == "true"
)
# Force STT onto the chunked/REST path where a provider's native streaming SDK
# transport is unavailable in the runtime (else it yields empty transcripts).
VOICE_DISABLE_STREAMING_STT = (
    os.environ.get("VOICE_DISABLE_STREAMING_STT", "").lower() == "true"
)

# WebSocket size limits to prevent memory exhaustion attacks
WS_MAX_MESSAGE_SIZE = 64 * 1024  # 64KB per message (OWASP recommendation)
WS_MAX_TOTAL_BYTES = 25 * 1024 * 1024  # 25MB total per connection (matches REST API)
WS_MAX_TEXT_MESSAGE_SIZE = 16 * 1024  # 16KB for text/JSON messages
WS_MAX_TTS_TEXT_LENGTH = 4096  # Max text length per synthesize call (matches REST API)


class ChunkedTranscriber:
    """Fallback transcriber for providers without streaming support.

    For raw PCM16 input, audio is transcribed in multi-second windows and
    silence is never sent to the provider — STT models hallucinate on
    silent/near-silent audio instead of returning an empty transcript.
    """

    def __init__(self, provider: Any, audio_format: str = "webm"):
        self.provider = provider
        self.audio_format = audio_format
        self.is_pcm = audio_format == "pcm16"
        self.window_bytes = (
            PCM_TRANSCRIBE_WINDOW_BYTES if self.is_pcm else MIN_CHUNK_BYTES
        )
        self.chunk_buffer = io.BytesIO()
        self.full_audio = io.BytesIO()
        self.chunk_bytes = 0
        self.window_has_speech = False
        self.transcripts: list[str] = []

    async def add_chunk(self, chunk: bytes) -> str | None:
        """Add audio chunk. Returns transcript if enough audio accumulated."""
        self.chunk_buffer.write(chunk)
        self.full_audio.write(chunk)
        self.chunk_bytes += len(chunk)

        if (
            self.is_pcm
            and not self.window_has_speech
            and pcm16_rms(chunk) >= SILENCE_RMS_THRESHOLD
        ):
            self.window_has_speech = True

        if self.chunk_bytes >= self.window_bytes:
            if self.is_pcm and not self.window_has_speech:
                logger.debug(
                    "Chunked transcription: dropping silent window (%s bytes)",
                    self.chunk_bytes,
                )
                self._reset_window()
                return None
            return await self._transcribe_chunk()
        return None

    def _reset_window(self) -> None:
        self.chunk_buffer = io.BytesIO()
        self.chunk_bytes = 0
        self.window_has_speech = False

    async def _transcribe_chunk(self) -> str | None:
        """Transcribe current chunk and append to running transcript."""
        audio_data = self.chunk_buffer.getvalue()
        if not audio_data:
            return None

        try:
            transcript = await self.provider.transcribe(audio_data, self.audio_format)
            self._reset_window()

            if transcript and transcript.strip():
                self.transcripts.append(transcript.strip())
                return " ".join(self.transcripts)
            return None
        except Exception as e:
            logger.error("Transcription error: %s", e)
            self._reset_window()
            return None

    async def flush(self) -> str:
        """Get final transcript from full audio for best accuracy."""
        full_audio_data = self.full_audio.getvalue()
        if self.is_pcm:
            full_audio_data = trim_pcm16_silence(full_audio_data)
            if not full_audio_data:
                # No speech detected in the recording; empty unless earlier
                # windows produced transcripts
                return " ".join(self.transcripts)
        if full_audio_data:
            try:
                transcript = await self.provider.transcribe(
                    full_audio_data, self.audio_format
                )
                if transcript and transcript.strip():
                    return transcript.strip()
            except Exception as e:
                logger.error("Final transcription error: %s", e)
        return " ".join(self.transcripts)


async def handle_streaming_transcription(
    websocket: WebSocket,
    transcriber: StreamingTranscriberProtocol,
) -> None:
    """Handle transcription using native streaming API."""
    logger.info("Streaming transcription: starting handler")
    last_transcript = ""
    chunk_count = 0
    total_bytes = 0

    async def receive_transcripts() -> None:
        """Background task to receive and send transcripts."""
        nonlocal last_transcript
        logger.info("Streaming transcription: starting transcript receiver")
        while True:
            result: TranscriptResult | None = await transcriber.receive_transcript()
            if result is None:  # End of stream
                logger.info("Streaming transcription: transcript stream ended")
                break
            # Send if text changed OR if VAD detected end of speech (for auto-send trigger)
            if result.text and (result.text != last_transcript or result.is_vad_end):
                last_transcript = result.text
                logger.debug(
                    "Streaming transcription: got transcript: %s... (is_vad_end=%s)",
                    result.text[:50],
                    result.is_vad_end,
                )
                await websocket.send_json(
                    {
                        "type": "transcript",
                        "text": result.text,
                        "is_final": result.is_vad_end,
                    }
                )

    # Start receiving transcripts in background
    receive_task = asyncio.create_task(receive_transcripts())

    try:
        while True:
            message = await websocket.receive()
            msg_type = message.get("type", "unknown")

            if msg_type == "websocket.disconnect":
                logger.info(
                    "Streaming transcription: client disconnected after %s chunks (%s bytes)",
                    chunk_count,
                    total_bytes,
                )
                break

            if "bytes" in message:
                chunk_size = len(message["bytes"])

                # Enforce per-message size limit
                if chunk_size > WS_MAX_MESSAGE_SIZE:
                    logger.warning(
                        "Streaming transcription: message too large (%s bytes)",
                        chunk_size,
                    )
                    await websocket.send_json(
                        {"type": "error", "message": "Message too large"}
                    )
                    break

                # Enforce total connection size limit
                if total_bytes + chunk_size > WS_MAX_TOTAL_BYTES:
                    logger.warning(
                        "Streaming transcription: total size limit exceeded (%s bytes)",
                        total_bytes + chunk_size,
                    )
                    await websocket.send_json(
                        {"type": "error", "message": "Total size limit exceeded"}
                    )
                    break

                chunk_count += 1
                total_bytes += chunk_size
                logger.debug(
                    "Streaming transcription: received chunk %s (%s bytes, total: %s)",
                    chunk_count,
                    chunk_size,
                    total_bytes,
                )
                await transcriber.send_audio(message["bytes"])

            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                    logger.debug(
                        "Streaming transcription: received text message: %s", data
                    )
                    if data.get("type") == "end":
                        logger.info(
                            "Streaming transcription: end signal received, closing transcriber"
                        )
                        final_transcript = await transcriber.close()
                        receive_task.cancel()
                        logger.info(
                            "Streaming transcription: final transcript: %s...",
                            final_transcript[:100] if final_transcript else "(empty)",
                        )
                        await websocket.send_json(
                            {
                                "type": "transcript",
                                "text": final_transcript,
                                "is_final": True,
                            }
                        )
                        break
                    elif data.get("type") == "reset":
                        # Reset accumulated transcript after auto-send
                        logger.info(
                            "Streaming transcription: reset signal received, clearing transcript"
                        )
                        transcriber.reset_transcript()
                except json.JSONDecodeError:
                    logger.warning(
                        "Streaming transcription: failed to parse JSON: %s",
                        message.get("text", "")[:100],
                    )
    except Exception as e:
        logger.error("Streaming transcription: error: %s", e, exc_info=True)
        raise
    finally:
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        logger.info(
            "Streaming transcription: handler finished. Processed %s chunks, %s total bytes",
            chunk_count,
            total_bytes,
        )


async def handle_chunked_transcription(
    websocket: WebSocket,
    transcriber: ChunkedTranscriber,
) -> None:
    """Handle transcription using chunked batch API."""
    logger.info("Chunked transcription: starting handler")
    chunk_count = 0
    total_bytes = 0

    while True:
        message = await websocket.receive()
        msg_type = message.get("type", "unknown")

        if msg_type == "websocket.disconnect":
            logger.info(
                "Chunked transcription: client disconnected after %s chunks (%s bytes)",
                chunk_count,
                total_bytes,
            )
            break

        if "bytes" in message:
            chunk_size = len(message["bytes"])

            # Enforce per-message size limit
            if chunk_size > WS_MAX_MESSAGE_SIZE:
                logger.warning(
                    "Chunked transcription: message too large (%s bytes)", chunk_size
                )
                await websocket.send_json(
                    {"type": "error", "message": "Message too large"}
                )
                break

            # Enforce total connection size limit
            if total_bytes + chunk_size > WS_MAX_TOTAL_BYTES:
                logger.warning(
                    "Chunked transcription: total size limit exceeded (%s bytes)",
                    total_bytes + chunk_size,
                )
                await websocket.send_json(
                    {"type": "error", "message": "Total size limit exceeded"}
                )
                break

            chunk_count += 1
            total_bytes += chunk_size
            logger.debug(
                "Chunked transcription: received chunk %s (%s bytes, total: %s)",
                chunk_count,
                chunk_size,
                total_bytes,
            )

            transcript = await transcriber.add_chunk(message["bytes"])
            if transcript:
                logger.debug(
                    "Chunked transcription: got transcript: %s...", transcript[:50]
                )
                await websocket.send_json(
                    {
                        "type": "transcript",
                        "text": transcript,
                        "is_final": False,
                    }
                )

        elif "text" in message:
            try:
                data = json.loads(message["text"])
                logger.debug("Chunked transcription: received text message: %s", data)
                if data.get("type") == "end":
                    logger.info("Chunked transcription: end signal received, flushing")
                    final_transcript = await transcriber.flush()
                    logger.info(
                        "Chunked transcription: final transcript: %s...",
                        final_transcript[:100] if final_transcript else "(empty)",
                    )
                    await websocket.send_json(
                        {
                            "type": "transcript",
                            "text": final_transcript,
                            "is_final": True,
                        }
                    )
                    break
            except json.JSONDecodeError:
                logger.warning(
                    "Chunked transcription: failed to parse JSON: %s",
                    message.get("text", "")[:100],
                )

    logger.info(
        "Chunked transcription: handler finished. Processed %s chunks, %s total bytes",
        chunk_count,
        total_bytes,
    )


@router.websocket("/transcribe/stream")
async def websocket_transcribe(
    websocket: WebSocket,
    _user: User = Depends(current_user_from_websocket),
) -> None:
    """
    WebSocket endpoint for streaming speech-to-text.

    Protocol:
    - Client sends binary audio chunks
    - Server sends JSON: {"type": "transcript", "text": "...", "is_final": false}
    - Client sends JSON {"type": "end"} to signal end
    - Server responds with final transcript and closes

    Authentication:
        Requires `token` query parameter (e.g., /voice/transcribe/stream?token=xxx).
        Applies same auth checks as HTTP endpoints (verification, role checks).
    """
    logger.info("WebSocket transcribe: connection request received (authenticated)")

    try:
        await websocket.accept()
        logger.info("WebSocket transcribe: connection accepted")
    except Exception as e:
        logger.error("WebSocket transcribe: failed to accept connection: %s", e)
        return

    streaming_transcriber = None
    provider = None

    try:
        # Get STT provider
        logger.info("WebSocket transcribe: fetching STT provider from database")
        engine = get_sqlalchemy_engine()
        with Session(engine) as db_session:
            provider_db = fetch_default_stt_provider(db_session)
            if provider_db is None:
                logger.warning(
                    "WebSocket transcribe: no default STT provider configured"
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "No speech-to-text provider configured",
                    }
                )
                return

            if not provider_db.api_key:
                logger.warning("WebSocket transcribe: STT provider has no API key")
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Speech-to-text provider has no API key configured",
                    }
                )
                return

            logger.info(
                "WebSocket transcribe: creating voice provider: %s",
                provider_db.provider_type,
            )
            try:
                provider = get_voice_provider(provider_db)
                logger.info(
                    "WebSocket transcribe: voice provider created, streaming supported: %s",
                    provider.supports_streaming_stt(),
                )
            except ValueError as e:
                logger.error(
                    "WebSocket transcribe: failed to create voice provider: %s", e
                )
                await websocket.send_json({"type": "error", "message": str(e)})
                return

        # Prefer native streaming; use the chunked/REST path when the provider
        # lacks it or it's disabled via VOICE_DISABLE_STREAMING_STT.
        use_streaming = (
            provider.supports_streaming_stt() and not VOICE_DISABLE_STREAMING_STT
        )

        if use_streaming:
            try:
                streaming_transcriber = await provider.create_streaming_transcriber()
                logger.info("WebSocket transcribe: streaming transcriber created")
                await handle_streaming_transcription(websocket, streaming_transcriber)
                return
            except Exception as e:
                logger.error("WebSocket transcribe: streaming STT failed: %s", e)
                if VOICE_DISABLE_STREAMING_FALLBACK:
                    await websocket.send_json(
                        {"type": "error", "message": f"Streaming STT failed: {e}"}
                    )
                    return
                logger.info("WebSocket transcribe: falling back to chunked STT")
        elif VOICE_DISABLE_STREAMING_FALLBACK and not VOICE_DISABLE_STREAMING_STT:
            # Provider can't stream and chunked fallback is disabled.
            await websocket.send_json(
                {"type": "error", "message": "Provider doesn't support streaming STT"}
            )
            return

        # Chunked/REST path; browser sends raw PCM16 chunks.
        chunked_transcriber = ChunkedTranscriber(provider, audio_format="pcm16")
        await handle_chunked_transcription(websocket, chunked_transcriber)

    except WebSocketDisconnect:
        logger.debug("WebSocket transcribe: client disconnected")
    except Exception as e:
        logger.error("WebSocket transcribe: unhandled error: %s", e, exc_info=True)
        try:
            # Send generic error to avoid leaking sensitive details
            await websocket.send_json(
                {"type": "error", "message": "An unexpected error occurred"}
            )
        except Exception:
            pass
    finally:
        if streaming_transcriber:
            try:
                await streaming_transcriber.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("WebSocket transcribe: connection closed")


async def handle_streaming_synthesis(
    websocket: WebSocket,
    synthesizer: StreamingSynthesizerProtocol,
) -> None:
    """Handle TTS using native streaming API."""
    logger.info("Streaming synthesis: starting handler")

    async def send_audio() -> None:
        """Background task to send audio chunks to client."""
        chunk_count = 0
        total_bytes = 0
        try:
            while True:
                audio_chunk = await synthesizer.receive_audio()
                if audio_chunk is None:
                    logger.info(
                        "Streaming synthesis: audio stream ended, sent %s chunks, %s bytes",
                        chunk_count,
                        total_bytes,
                    )
                    try:
                        await websocket.send_json({"type": "audio_done"})
                        logger.info("Streaming synthesis: sent audio_done to client")
                    except Exception as e:
                        logger.warning(
                            "Streaming synthesis: failed to send audio_done: %s", e
                        )
                    break
                if audio_chunk:  # Skip empty chunks
                    chunk_count += 1
                    total_bytes += len(audio_chunk)
                    try:
                        await websocket.send_bytes(audio_chunk)
                    except Exception as e:
                        logger.warning(
                            "Streaming synthesis: failed to send chunk: %s", e
                        )
                        break
        except asyncio.CancelledError:
            logger.info(
                "Streaming synthesis: send_audio cancelled after %s chunks", chunk_count
            )
        except Exception as e:
            logger.error("Streaming synthesis: send_audio error: %s", e)

    send_task: asyncio.Task | None = None
    disconnected = False

    try:
        while not disconnected:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                logger.info("Streaming synthesis: client disconnected")
                break

            msg_type = message.get("type", "unknown")

            if msg_type == "websocket.disconnect":
                logger.info("Streaming synthesis: client disconnected")
                disconnected = True
                break

            if "text" in message:
                # Enforce text message size limit
                msg_size = len(message["text"])
                if msg_size > WS_MAX_TEXT_MESSAGE_SIZE:
                    logger.warning(
                        "Streaming synthesis: text message too large (%s bytes)",
                        msg_size,
                    )
                    await websocket.send_json(
                        {"type": "error", "message": "Message too large"}
                    )
                    break

                try:
                    data = json.loads(message["text"])

                    if data.get("type") == "synthesize":
                        text = data.get("text", "")
                        # Enforce per-text size limit
                        if len(text) > WS_MAX_TTS_TEXT_LENGTH:
                            logger.warning(
                                "Streaming synthesis: text too long (%s chars)",
                                len(text),
                            )
                            await websocket.send_json(
                                {"type": "error", "message": "Text too long"}
                            )
                            continue
                        if text:
                            # Start audio receiver on first text chunk so playback
                            # can begin before the full assistant response completes.
                            if send_task is None:
                                send_task = asyncio.create_task(send_audio())
                            logger.debug(
                                "Streaming synthesis: forwarding text chunk (%s chars)",
                                len(text),
                            )
                            await synthesizer.send_text(strip_markdown_for_tts(text))

                    elif data.get("type") == "end":
                        logger.info("Streaming synthesis: end signal received")

                        # Ensure receiver is active even if no prior text chunks arrived.
                        if send_task is None:
                            send_task = asyncio.create_task(send_audio())

                        # Signal end of input
                        if hasattr(synthesizer, "flush"):
                            await synthesizer.flush()

                        # Wait for all audio to be sent
                        logger.info(
                            "Streaming synthesis: waiting for audio stream to complete"
                        )
                        try:
                            await asyncio.wait_for(send_task, timeout=60.0)
                        except asyncio.TimeoutError:
                            logger.warning(
                                "Streaming synthesis: timeout waiting for audio"
                            )
                        break

                except json.JSONDecodeError:
                    logger.warning(
                        "Streaming synthesis: failed to parse JSON: %s",
                        message.get("text", "")[:100],
                    )

    except WebSocketDisconnect:
        logger.debug("Streaming synthesis: client disconnected during synthesis")
    except Exception as e:
        logger.error("Streaming synthesis: error: %s", e, exc_info=True)
    finally:
        if send_task and not send_task.done():
            logger.info("Streaming synthesis: waiting for send_task to finish")
            try:
                await asyncio.wait_for(send_task, timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Streaming synthesis: timeout waiting for send_task")
                send_task.cancel()
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        logger.info("Streaming synthesis: handler finished")


async def handle_chunked_synthesis(
    websocket: WebSocket,
    provider: Any,
    first_message: MutableMapping[str, Any] | None = None,
) -> None:
    """Fallback TTS handler using provider.synthesize_stream.

    Args:
        websocket: The WebSocket connection
        provider: Voice provider instance
        first_message: Optional first message already received (used when falling
            back from streaming mode, where the first message was already consumed)
    """
    logger.info("Chunked synthesis: starting handler")
    text_buffer: list[str] = []
    voice: str | None = None
    speed = 1.0

    # Process pre-received message if provided
    pending_message = first_message

    try:
        while True:
            if pending_message is not None:
                message = pending_message
                pending_message = None
            else:
                message = await websocket.receive()
            msg_type = message.get("type", "unknown")

            if msg_type == "websocket.disconnect":
                logger.info("Chunked synthesis: client disconnected")
                break

            if "text" not in message:
                continue

            # Enforce text message size limit
            msg_size = len(message["text"])
            if msg_size > WS_MAX_TEXT_MESSAGE_SIZE:
                logger.warning(
                    "Chunked synthesis: text message too large (%s bytes)", msg_size
                )
                await websocket.send_json(
                    {"type": "error", "message": "Message too large"}
                )
                break

            try:
                data = json.loads(message["text"])
            except json.JSONDecodeError:
                logger.warning(
                    "Chunked synthesis: failed to parse JSON: %s",
                    message.get("text", "")[:100],
                )
                continue

            msg_data_type = data.get("type")
            if msg_data_type == "synthesize":
                text = data.get("text", "")
                # Enforce per-text size limit
                if len(text) > WS_MAX_TTS_TEXT_LENGTH:
                    logger.warning(
                        "Chunked synthesis: text too long (%s chars)", len(text)
                    )
                    await websocket.send_json(
                        {"type": "error", "message": "Text too long"}
                    )
                    continue
                if text:
                    text_buffer.append(text)
                    logger.debug(
                        "Chunked synthesis: buffered text (%s chars), total buffered: %s chunks",
                        len(text),
                        len(text_buffer),
                    )
                if isinstance(data.get("voice"), str) and data["voice"]:
                    voice = data["voice"]
                if isinstance(data.get("speed"), (int, float)):
                    speed = float(data["speed"])
            elif msg_data_type == "end":
                logger.info("Chunked synthesis: end signal received")
                full_text = strip_markdown_for_tts(" ".join(text_buffer))
                if not full_text:
                    await websocket.send_json({"type": "audio_done"})
                    logger.info("Chunked synthesis: no text, sent audio_done")
                    break

                chunk_count = 0
                total_bytes = 0
                logger.info(
                    "Chunked synthesis: sending full text (%s chars)", len(full_text)
                )
                async for audio_chunk in provider.synthesize_stream(
                    full_text, voice=voice, speed=speed
                ):
                    if not audio_chunk:
                        continue
                    chunk_count += 1
                    total_bytes += len(audio_chunk)
                    await websocket.send_bytes(audio_chunk)
                await websocket.send_json({"type": "audio_done"})
                logger.info(
                    "Chunked synthesis: sent audio_done after %s chunks, %s bytes",
                    chunk_count,
                    total_bytes,
                )
                break
    except WebSocketDisconnect:
        logger.debug("Chunked synthesis: client disconnected")
    except Exception as e:
        logger.error("Chunked synthesis: error: %s", e, exc_info=True)
        raise
    finally:
        logger.info("Chunked synthesis: handler finished")


@router.websocket("/synthesize/stream")
async def websocket_synthesize(
    websocket: WebSocket,
    _user: User = Depends(current_user_from_websocket),
) -> None:
    """
    WebSocket endpoint for streaming text-to-speech.

    Protocol:
    - Client sends JSON: {"type": "synthesize", "text": "...", "voice": "...", "speed": 1.0}
    - Server sends binary audio chunks
    - Server sends JSON: {"type": "audio_done"} when synthesis completes
    - Client sends JSON {"type": "end"} to close connection

    Authentication:
        Requires `token` query parameter (e.g., /voice/synthesize/stream?token=xxx).
        Applies same auth checks as HTTP endpoints (verification, role checks).
    """
    logger.info("WebSocket synthesize: connection request received (authenticated)")

    try:
        await websocket.accept()
        logger.info("WebSocket synthesize: connection accepted")
    except Exception as e:
        logger.error("WebSocket synthesize: failed to accept connection: %s", e)
        return

    streaming_synthesizer: StreamingSynthesizerProtocol | None = None
    provider = None

    try:
        # Get TTS provider
        logger.info("WebSocket synthesize: fetching TTS provider from database")
        engine = get_sqlalchemy_engine()
        with Session(engine) as db_session:
            provider_db = fetch_default_tts_provider(db_session)
            if provider_db is None:
                logger.warning(
                    "WebSocket synthesize: no default TTS provider configured"
                )
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "No text-to-speech provider configured",
                    }
                )
                return

            if not provider_db.api_key:
                logger.warning("WebSocket synthesize: TTS provider has no API key")
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Text-to-speech provider has no API key configured",
                    }
                )
                return

            logger.info(
                "WebSocket synthesize: creating voice provider: %s",
                provider_db.provider_type,
            )
            try:
                provider = get_voice_provider(provider_db)
                logger.info(
                    "WebSocket synthesize: voice provider created, streaming TTS supported: %s",
                    provider.supports_streaming_tts(),
                )
            except ValueError as e:
                logger.error(
                    "WebSocket synthesize: failed to create voice provider: %s", e
                )
                await websocket.send_json({"type": "error", "message": str(e)})
                return

        # Use native streaming if provider supports it
        if provider.supports_streaming_tts():
            logger.info("WebSocket synthesize: using native streaming TTS")
            message = None  # Initialize to avoid UnboundLocalError in except block
            try:
                # Wait for initial config message with voice/speed
                message = await websocket.receive()
                voice = None
                speed = 1.0
                if "text" in message:
                    try:
                        data = json.loads(message["text"])
                        voice = data.get("voice")
                        speed = data.get("speed", 1.0)
                    except json.JSONDecodeError:
                        pass

                streaming_synthesizer = await provider.create_streaming_synthesizer(
                    voice=voice, speed=speed
                )
                logger.info(
                    "WebSocket synthesize: streaming synthesizer created successfully"
                )
                await handle_streaming_synthesis(websocket, streaming_synthesizer)
            except Exception as e:
                logger.error(
                    "WebSocket synthesize: failed to create streaming synthesizer: %s",
                    e,
                )
                if VOICE_DISABLE_STREAMING_FALLBACK:
                    await websocket.send_json(
                        {"type": "error", "message": f"Streaming TTS failed: {e}"}
                    )
                    return
                logger.info(
                    "WebSocket synthesize: falling back to chunked TTS synthesis"
                )
                # Pass the first message so it's not lost in the fallback
                await handle_chunked_synthesis(
                    websocket, provider, first_message=message
                )
        else:
            if VOICE_DISABLE_STREAMING_FALLBACK:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Provider doesn't support streaming TTS",
                    }
                )
                return
            logger.info(
                "WebSocket synthesize: using chunked TTS (provider doesn't support streaming)"
            )
            await handle_chunked_synthesis(websocket, provider)

    except WebSocketDisconnect:
        logger.debug("WebSocket synthesize: client disconnected")
    except Exception as e:
        logger.error("WebSocket synthesize: unhandled error: %s", e, exc_info=True)
        try:
            # Send generic error to avoid leaking sensitive details
            await websocket.send_json(
                {"type": "error", "message": "An unexpected error occurred"}
            )
        except Exception:
            pass
    finally:
        if streaming_synthesizer:
            try:
                await streaming_synthesizer.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("WebSocket synthesize: connection closed")
