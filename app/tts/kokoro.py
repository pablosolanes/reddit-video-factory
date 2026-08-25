from __future__ import annotations

import hashlib
import logging
import wave
from pathlib import Path
from typing import Any

from app.config import TTSConfig
from app.tts.base import TTSProvider


logger = logging.getLogger(__name__)


KOKORO_SAMPLE_RATE = 24000
VOICE_LANGUAGE_PREFIXES = {
    "a": "a",
    "b": "b",
    "e": "e",
    "f": "f",
    "h": "h",
    "i": "i",
    "j": "j",
    "p": "p",
    "z": "z",
}


class TTSConfigurationError(RuntimeError):
    """Raised when local Kokoro TTS cannot be configured."""


class TTSGenerationError(RuntimeError):
    """Raised when local TTS generation fails."""


class KokoroTTSProvider(TTSProvider):
    def __init__(self, config: TTSConfig, cache_dir: str | Path) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._pipeline: Any | None = None

    def synthesize(self, text: str, output_path: Path) -> float:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists():
            duration = self.audio_duration(output_path)
            if duration > 0:
                logger.info("Using cached TTS audio: %s", output_path)
                return duration

        pipeline = self._get_pipeline()
        audio_chunks = []

        try:
            for result in pipeline(text, voice=self.config.voice, speed=self.config.speed):
                audio_chunks.append(self._audio_to_numpy(self._extract_audio(result)))
        except Exception as exc:
            raise TTSGenerationError(f"Kokoro failed to synthesize audio: {exc}") from exc

        if not audio_chunks:
            raise TTSGenerationError("Kokoro returned no audio chunks")

        audio = self._concatenate_audio(audio_chunks)
        self._write_wav(output_path, audio)
        duration = self.audio_duration(output_path)
        if duration <= 0:
            raise TTSGenerationError(f"Generated audio has invalid duration: {output_path}")
        return duration

    def cache_path_for_text(self, text: str, stem: str) -> Path:
        source = f"kokoro|{self.config.voice}|{self.config.speed}|{text}"
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        safe_stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in stem).strip("_")
        return self.cache_dir / f"{safe_stem}-{digest}.wav"

    def audio_duration(self, audio_path: str | Path) -> float:
        path = Path(audio_path)
        if not path.exists() or path.stat().st_size == 0:
            return 0.0
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return 0.0
            return frames / float(frame_rate)

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise TTSConfigurationError(
                "Kokoro is not installed. Install it with: python -m pip install kokoro soundfile"
            ) from exc

        lang_code = self._detect_lang_code(self.config.voice)
        try:
            self._pipeline = KPipeline(lang_code=lang_code)
        except Exception as exc:
            raise TTSConfigurationError(
                "Kokoro could not initialize. On Windows, install espeak-ng and ensure it is on PATH."
            ) from exc
        return self._pipeline

    def _detect_lang_code(self, voice: str) -> str:
        if not voice:
            return "e"
        return VOICE_LANGUAGE_PREFIXES.get(voice[0].lower(), "e")

    def _extract_audio(self, result):
        if hasattr(result, "audio"):
            return result.audio
        if isinstance(result, tuple) and result:
            return result[-1]
        raise TTSGenerationError("Kokoro result did not include audio")

    def _audio_to_numpy(self, audio):
        try:
            import numpy as np
        except ImportError as exc:
            raise TTSConfigurationError("NumPy is required for Kokoro audio processing.") from exc

        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        elif hasattr(audio, "cpu"):
            audio = audio.cpu().numpy()
        return np.asarray(audio, dtype="float32").reshape(-1)

    def _concatenate_audio(self, chunks: list):
        try:
            import numpy as np
        except ImportError as exc:
            raise TTSConfigurationError("NumPy is required for Kokoro audio processing.") from exc
        return np.concatenate(chunks)

    def _write_wav(self, output_path: Path, audio) -> None:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise TTSConfigurationError("soundfile is required to write Kokoro WAV output.") from exc
        sf.write(output_path, audio, KOKORO_SAMPLE_RATE)
