from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.config import WhisperConfig


logger = logging.getLogger(__name__)


class WhisperConfigurationError(RuntimeError):
    """Raised when local Whisper cannot be configured."""


class WhisperTranscriptionError(RuntimeError):
    """Raised when transcription fails or returns invalid data."""


class WhisperTranscriber:
    def __init__(self, config: WhisperConfig, cache_dir: str | Path) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = None

    def cache_path_for_audio(self, audio_path: str | Path) -> Path:
        path = Path(audio_path)
        stat = path.stat()
        source = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{self.config.model_size}"
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{path.stem}-{digest}.json"

    def transcribe(self, audio_path: str | Path) -> dict[str, Any]:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        cache_path = self.cache_path_for_audio(audio_path)
        if cache_path.exists():
            logger.info("Using cached transcript: %s", cache_path)
            with cache_path.open("r", encoding="utf-8") as file:
                cached = json.load(file)
            return self._validate_transcript(cached)

        model = self._get_model()
        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=self.config.language,
                beam_size=self.config.beam_size,
                word_timestamps=True,
                vad_filter=True,
            )
            segments = list(segments_iter)
        except Exception as exc:
            raise WhisperTranscriptionError(f"Whisper transcription failed: {exc}") from exc

        transcript = self._build_transcript(segments, info, audio_path)
        transcript = self._validate_transcript(transcript)
        with cache_path.open("w", encoding="utf-8") as file:
            json.dump(transcript, file, ensure_ascii=False, indent=2)
        return transcript

    def _get_model(self):
        if self._model is not None:
            return self._model

        if self.config.provider != "faster-whisper":
            raise WhisperConfigurationError(f"Unsupported Whisper provider: {self.config.provider}")

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise WhisperConfigurationError(
                "faster-whisper is not installed. Run: python -m pip install -r requirements.txt"
            ) from exc

        try:
            self._model = WhisperModel(
                self.config.model_size,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        except Exception as exc:
            raise WhisperConfigurationError(f"Could not initialize faster-whisper: {exc}") from exc
        return self._model

    def _build_transcript(self, segments: list[Any], info: Any, audio_path: Path) -> dict[str, Any]:
        segment_payloads: list[dict[str, Any]] = []
        words_payload: list[dict[str, Any]] = []

        for segment in segments:
            words = []
            for word in getattr(segment, "words", None) or []:
                word_payload = {
                    "start": round(float(word.start), 3),
                    "end": round(float(word.end), 3),
                    "word": str(word.word).strip(),
                    "probability": float(getattr(word, "probability", 0.0) or 0.0),
                }
                if word_payload["word"]:
                    words.append(word_payload)
                    words_payload.append(word_payload)

            segment_payloads.append(
                {
                    "id": int(getattr(segment, "id", len(segment_payloads))),
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                    "text": str(segment.text).strip(),
                    "words": words,
                }
            )

        return {
            "audio_path": str(audio_path),
            "language": str(getattr(info, "language", self.config.language)),
            "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
            "duration": float(getattr(info, "duration", 0.0) or 0.0),
            "segments": segment_payloads,
            "words": words_payload,
        }

    def _validate_transcript(self, transcript: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(transcript.get("segments"), list):
            raise WhisperTranscriptionError("Transcript missing segments list")
        if not isinstance(transcript.get("words"), list):
            transcript["words"] = []
        return transcript
