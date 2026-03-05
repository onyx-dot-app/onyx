"""WebSocket API for streaming speech-to-text and text-to-speech."""

import asyncio
import io
import json
from typing import Any

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
from onyx.utils.logger import setup_logger
from onyx.voice.factory import get_voice_provider
from onyx.voice.interface import StreamingSynthesizerProtocol
from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult

logger = setup_logger()

router = APIRouter(prefix="/voice")


# Transcribe every ~0.5 seconds of audio (webm/opus is ~2-4KB/s, so ~1-2KB per 0.5s)
MIN_CHUNK_BYTES = 1500


class ChunkedTranscriber:
    """Fallback transcriber for providers without streaming support."""

    def __init__(self, provider: Any, audio_format: str = "webm"):
        self.provider = provider
        self.audio_format = audio_format
        self.chunk_buffer = io.BytesIO()
        self.full_audio = io.BytesIO()
        self.chunk_bytes = 0
        self.transcripts: list[str] = []

    async def add_chunk(self, chunk: bytes) -> str | None:
        """Add audio chunk. Returns transcript if enough audio accumulated."""
        self.chunk_buffer.write(chunk)
        self.full_audio.write(chunk)
        self.chunk_bytes += len(chunk)

        if self.chunk_bytes >= MIN_CHUNK_BYTES:
            return await self._transcribe_chunk()
        return None

    async def _transcribe_chunk(self) -> str | None:
        """Transcribe current chunk and append to running transcript."""
        audio_data = self.chunk_buffer.getvalue()
        if not audio_data:
            return None

        try:
            transcript = await self.provider.transcribe(audio_data, self.audio_format)
            self.chunk_buffer = io.BytesIO()
            self.chunk_bytes = 0

            if transcript and transcript.strip():
                self.transcripts.append(transcript.strip())
                return " ".join(self.transcripts)
            return None
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self.chunk_buffer = io.BytesIO()
            self.chunk_bytes = 0
            return None

    async def flush(self) -> str:
        """Get final transcript from full audio for best accuracy."""
        full_audio_data = self.full_audio.getvalue()
        if full_audio_data:
            try:
                transcript = await self.provider.transcribe(
                    full_audio_data, self.audio_format
                )
                if transcript and transcript.strip():
                    return transcript.strip()
            except Exception as e:
                logger.error(f"Final transcription error: {e}")
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
                logger.info(
                    f"Streaming transcription: got transcript: {result.text[:50]}... "
                    f"(is_vad_end={result.is_vad_end})"
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
                    f"Streaming transcription: client disconnected after {chunk_count} chunks ({total_bytes} bytes)"
                )
                break

            if "bytes" in message:
                chunk_size = len(message["bytes"])
                chunk_count += 1
                total_bytes += chunk_size
                logger.debug(
                    f"Streaming transcription: received chunk {chunk_count} ({chunk_size} bytes, total: {total_bytes})"
                )
                await transcriber.send_audio(message["bytes"])

            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                    logger.info(
                        f"Streaming transcription: received text message: {data}"
                    )
                    if data.get("type") == "end":
                        logger.info(
                            "Streaming transcription: end signal received, closing transcriber"
                        )
                        final_transcript = await transcriber.close()
                        receive_task.cancel()
                        logger.info(
                            "Streaming transcription: final transcript: "
                            f"{final_transcript[:100] if final_transcript else '(empty)'}..."
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
                        f"Streaming transcription: failed to parse JSON: {message.get('text', '')[:100]}"
                    )
    except Exception as e:
        logger.error(f"Streaming transcription: error: {e}", exc_info=True)
        raise
    finally:
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        logger.info(
            f"Streaming transcription: handler finished. Processed {chunk_count} chunks, {total_bytes} total bytes"
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
                f"Chunked transcription: client disconnected after {chunk_count} chunks ({total_bytes} bytes)"
            )
            break

        if "bytes" in message:
            chunk_size = len(message["bytes"])
            chunk_count += 1
            total_bytes += chunk_size
            logger.debug(
                f"Chunked transcription: received chunk {chunk_count} ({chunk_size} bytes, total: {total_bytes})"
            )

            transcript = await transcriber.add_chunk(message["bytes"])
            if transcript:
                logger.info(
                    f"Chunked transcription: got transcript: {transcript[:50]}..."
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
                logger.info(f"Chunked transcription: received text message: {data}")
                if data.get("type") == "end":
                    logger.info("Chunked transcription: end signal received, flushing")
                    final_transcript = await transcriber.flush()
                    logger.info(
                        f"Chunked transcription: final transcript: {final_transcript[:100] if final_transcript else '(empty)'}..."
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
                    f"Chunked transcription: failed to parse JSON: {message.get('text', '')[:100]}"
                )

    logger.info(
        f"Chunked transcription: handler finished. Processed {chunk_count} chunks, {total_bytes} total bytes"
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
        logger.error(f"WebSocket transcribe: failed to accept connection: {e}")
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
                f"WebSocket transcribe: creating voice provider: {provider_db.provider_type}"
            )
            try:
                provider = get_voice_provider(provider_db)
                logger.info(
                    f"WebSocket transcribe: voice provider created, streaming supported: {provider.supports_streaming_stt()}"
                )
            except ValueError as e:
                logger.error(
                    f"WebSocket transcribe: failed to create voice provider: {e}"
                )
                await websocket.send_json({"type": "error", "message": str(e)})
                return

        # Use native streaming if provider supports it
        if provider.supports_streaming_stt():
            logger.info("WebSocket transcribe: using native streaming STT")
            try:
                streaming_transcriber = await provider.create_streaming_transcriber()
                logger.info(
                    "WebSocket transcribe: streaming transcriber created successfully"
                )
                await handle_streaming_transcription(websocket, streaming_transcriber)
            except Exception as e:
                logger.error(
                    f"WebSocket transcribe: failed to create streaming transcriber: {e}"
                )
                logger.info("WebSocket transcribe: falling back to chunked STT")
                chunked_transcriber = ChunkedTranscriber(provider)
                await handle_chunked_transcription(websocket, chunked_transcriber)
        else:
            # Fall back to chunked transcription
            logger.info(
                "WebSocket transcribe: using chunked STT (provider doesn't support streaming)"
            )
            chunked_transcriber = ChunkedTranscriber(provider)
            await handle_chunked_transcription(websocket, chunked_transcriber)

    except WebSocketDisconnect:
        logger.debug("WebSocket transcribe: client disconnected")
    except Exception as e:
        logger.error(f"WebSocket transcribe: unhandled error: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
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
    """Handle TTS using native streaming API.

    Buffers all text, then sends to ElevenLabs when complete.
    This is more reliable than streaming chunks incrementally.
    """
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
                        f"Streaming synthesis: audio stream ended, sent {chunk_count} chunks, {total_bytes} bytes"
                    )
                    try:
                        await websocket.send_json({"type": "audio_done"})
                        logger.info("Streaming synthesis: sent audio_done to client")
                    except Exception as e:
                        logger.warning(
                            f"Streaming synthesis: failed to send audio_done: {e}"
                        )
                    break
                if audio_chunk:  # Skip empty chunks
                    chunk_count += 1
                    total_bytes += len(audio_chunk)
                    try:
                        await websocket.send_bytes(audio_chunk)
                    except Exception as e:
                        logger.warning(
                            f"Streaming synthesis: failed to send chunk: {e}"
                        )
                        break
        except asyncio.CancelledError:
            logger.info(
                f"Streaming synthesis: send_audio cancelled after {chunk_count} chunks"
            )
        except Exception as e:
            logger.error(f"Streaming synthesis: send_audio error: {e}")

    send_task: asyncio.Task | None = None
    text_buffer: list[str] = []  # Buffer text chunks until "end"
    disconnected = False

    try:
        while not disconnected:
            try:
                message = await websocket.receive()
            except RuntimeError as e:
                if "disconnect" in str(e).lower():
                    logger.info("Streaming synthesis: client disconnected")
                    break
                raise

            msg_type = message.get("type", "unknown")

            if msg_type == "websocket.disconnect":
                logger.info("Streaming synthesis: client disconnected")
                disconnected = True
                break

            if "text" in message:
                try:
                    data = json.loads(message["text"])

                    if data.get("type") == "synthesize":
                        text = data.get("text", "")
                        if not text:
                            for key, value in data.items():
                                if key != "type" and isinstance(value, str) and value:
                                    text = value
                                    break
                        if text:
                            # Buffer text instead of sending immediately
                            text_buffer.append(text)
                            logger.info(
                                f"Streaming synthesis: buffered text ({len(text)} chars), "
                                f"total buffered: {len(text_buffer)} chunks"
                            )

                    elif data.get("type") == "end":
                        logger.info("Streaming synthesis: end signal received")

                        if text_buffer:
                            # Combine all buffered text
                            full_text = " ".join(text_buffer)
                            logger.info(
                                f"Streaming synthesis: sending full text ({len(full_text)} chars): "
                                f"'{full_text[:100]}...'"
                            )

                            # Start audio receiver
                            send_task = asyncio.create_task(send_audio())

                            # Send all text at once
                            await synthesizer.send_text(full_text)
                            logger.info(
                                "Streaming synthesis: full text sent to synthesizer"
                            )

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
                        f"Streaming synthesis: failed to parse JSON: {message.get('text', '')[:100]}"
                    )

    except Exception as e:
        if "disconnect" not in str(e).lower():
            logger.error(f"Streaming synthesis: error: {e}", exc_info=True)
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
        logger.error(f"WebSocket synthesize: failed to accept connection: {e}")
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
                f"WebSocket synthesize: creating voice provider: {provider_db.provider_type}"
            )
            try:
                provider = get_voice_provider(provider_db)
                logger.info(
                    f"WebSocket synthesize: voice provider created, streaming TTS supported: {provider.supports_streaming_tts()}"
                )
            except ValueError as e:
                logger.error(
                    f"WebSocket synthesize: failed to create voice provider: {e}"
                )
                await websocket.send_json({"type": "error", "message": str(e)})
                return

        # Use native streaming if provider supports it
        if provider.supports_streaming_tts():
            logger.info("WebSocket synthesize: using native streaming TTS")
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
                    f"WebSocket synthesize: failed to create streaming synthesizer: {e}"
                )
                await websocket.send_json(
                    {"type": "error", "message": f"Streaming TTS failed: {e}"}
                )
        else:
            logger.warning(
                "WebSocket synthesize: provider doesn't support streaming TTS"
            )
            await websocket.send_json(
                {"type": "error", "message": "Provider doesn't support streaming TTS"}
            )

    except WebSocketDisconnect:
        logger.debug("WebSocket synthesize: client disconnected")
    except RuntimeError as e:
        if "disconnect" in str(e).lower():
            logger.debug("WebSocket synthesize: client disconnected")
        else:
            logger.error(f"WebSocket synthesize: runtime error: {e}")
    except Exception as e:
        error_str = str(e).lower()
        if "disconnect" in error_str or "websocket.close" in error_str:
            logger.debug("WebSocket synthesize: client disconnected")
        else:
            logger.error(f"WebSocket synthesize: unhandled error: {e}", exc_info=True)
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
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
