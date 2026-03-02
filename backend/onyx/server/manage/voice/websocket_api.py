"""WebSocket API for streaming speech-to-text."""

import asyncio
import io
import json
from typing import Any

from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.voice import fetch_default_stt_provider
from onyx.utils.logger import setup_logger
from onyx.voice.factory import get_voice_provider
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
async def websocket_transcribe(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for streaming speech-to-text.

    Protocol:
    - Client sends binary audio chunks
    - Server sends JSON: {"type": "transcript", "text": "...", "is_final": false}
    - Client sends JSON {"type": "end"} to signal end
    - Server responds with final transcript and closes
    """
    logger.info("WebSocket transcribe: connection request received")

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
