from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from local_tts_stt.server import DEFAULT_STT_MODEL, SpeechRequest, _synthesize


def _warm_stt() -> None:
    import mlx_whisper

    model = os.environ.get("LOCAL_STT_MODEL", DEFAULT_STT_MODEL)
    audio = np.zeros(24_000, dtype=np.float32)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = Path(tmp.name)
        sf.write(tmp, audio, 24_000, format="WAV")

    try:
        mlx_whisper.transcribe(str(path), path_or_hf_repo=model)
    finally:
        path.unlink(missing_ok=True)


def _warm_tts() -> None:
    _synthesize(
        SpeechRequest(
            input="Voice model ready.",
            response_format="wav",
        )
    )


def main() -> None:
    print("Warming STT model...")
    _warm_stt()
    print("Warming TTS model...")
    _warm_tts()
    print("Local voice models ready.")


if __name__ == "__main__":
    main()
