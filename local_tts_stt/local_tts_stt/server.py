from __future__ import annotations

import argparse
import asyncio
import io
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

SAMPLE_RATE = 24_000
DEFAULT_STT_MODEL = "mlx-community/whisper-large-v3-turbo"
DEFAULT_TTS_MODEL = "kokoro"
DEFAULT_VOICE = "af_heart"
STT_MODEL_ALIASES = {"mlx-whisper", "whisper-1"}


class SpeechRequest(BaseModel):
    model: str = DEFAULT_TTS_MODEL
    input: str = Field(min_length=1)
    voice: str = DEFAULT_VOICE
    response_format: Literal["mp3", "wav"] = "mp3"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


def _voice_to_lang_code(voice: str) -> str:
    # Kokoro voice IDs start with the language code used by KPipeline.
    return voice.split("_", 1)[0][:1] or "a"


@lru_cache(maxsize=8)
def _kokoro_pipeline(lang_code: str):
    from kokoro import KPipeline

    return KPipeline(lang_code=lang_code)


def _wav_bytes(audio: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, audio, SAMPLE_RATE, format="WAV")
    return buffer.getvalue()


def _mp3_bytes(audio: np.ndarray) -> bytes:
    wav = _wav_bytes(audio)
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "mp3",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "pipe:1",
            ],
            input=wav,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg is required for MP3 output. Install with `brew install ffmpeg`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg failed to encode MP3: {message}") from exc
    return proc.stdout


def _synthesize(body: SpeechRequest) -> tuple[bytes, str]:
    pipeline = _kokoro_pipeline(_voice_to_lang_code(body.voice))
    chunks: list[np.ndarray] = []
    for _, _, audio in pipeline(body.input, voice=body.voice, speed=body.speed):
        chunks.append(np.asarray(audio, dtype=np.float32))

    if not chunks:
        raise RuntimeError("Kokoro returned no audio.")

    audio = np.concatenate(chunks)
    if body.response_format == "wav":
        return _wav_bytes(audio), "audio/wav"
    return _mp3_bytes(audio), "audio/mpeg"


def _transcribe(
    audio_path: Path,
    model: str,
    language: str | None,
    prompt: str | None,
) -> dict[str, object]:
    import mlx_whisper

    kwargs: dict[str, object] = {"path_or_hf_repo": model}
    if language:
        kwargs["language"] = language
    if prompt:
        kwargs["initial_prompt"] = prompt
    return mlx_whisper.transcribe(str(audio_path), **kwargs)


def _resolve_stt_model(model: str) -> str:
    if model in STT_MODEL_ALIASES:
        return os.environ.get("LOCAL_STT_MODEL", DEFAULT_STT_MODEL)
    return model


def create_app(mode: Literal["stt", "tts", "all"]) -> FastAPI:
    app = FastAPI(title="Onyx Local Voice Server")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": mode}

    @app.post("/audio/transcriptions")
    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        file: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = os.environ.get(
            "LOCAL_STT_MODEL", DEFAULT_STT_MODEL
        ),
        language: Annotated[str | None, Form()] = None,
        prompt: Annotated[str | None, Form()] = None,
        response_format: Annotated[str, Form()] = "json",
    ) -> dict[str, object] | str:
        if mode not in {"stt", "all"}:
            raise HTTPException(
                status_code=404, detail="STT is not enabled on this server."
            )

        suffix = Path(file.filename or "audio.webm").suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(await file.read())

        try:
            result = await asyncio.to_thread(
                _transcribe, tmp_path, _resolve_stt_model(model), language, prompt
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        text = str(result.get("text", "")).strip()
        if response_format == "text":
            return text
        return {"text": text}

    @app.post("/audio/speech")
    @app.post("/v1/audio/speech")
    async def speech(body: SpeechRequest) -> Response:
        if mode not in {"tts", "all"}:
            raise HTTPException(
                status_code=404, detail="TTS is not enabled on this server."
            )

        try:
            audio, media_type = await asyncio.to_thread(_synthesize, body)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return Response(content=audio, media_type=media_type)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a local OpenAI-compatible voice server."
    )
    parser.add_argument("--mode", choices=("stt", "tts", "all"), default="all")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6600)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(args.mode), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
