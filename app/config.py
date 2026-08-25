from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    daily_videos: int
    language: str
    output_dir: Path


@dataclass(frozen=True)
class RedditConfig:
    subreddits: list[str]
    sort: str
    time_filter: str
    limit_per_subreddit: int
    min_score: int
    min_length: int
    max_length: int
    request_delay_seconds: float
    max_retries: int


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    temperature: float
    max_output_tokens: int
    request_timeout_seconds: int
    max_retries: int


@dataclass(frozen=True)
class TTSConfig:
    provider: str
    voice: str
    speed: float


@dataclass(frozen=True)
class VideoConfig:
    width: int
    height: int
    fps: int
    min_duration_seconds: int
    max_duration_seconds: int
    duration_tolerance_seconds: int
    ffmpeg_path: str
    ffprobe_path: str
    styles: list[str]


@dataclass(frozen=True)
class SubtitlesConfig:
    max_chars_per_line: int
    max_lines: int
    font_size: int
    output_dir: Path


@dataclass(frozen=True)
class WhisperConfig:
    provider: str
    model_size: str
    device: str
    compute_type: str
    language: str
    beam_size: int


@dataclass(frozen=True)
class BackgroundsConfig:
    directory: Path
    avoid_consecutive_repeats: bool
    min_duration_seconds: int
    min_width: int
    min_height: int
    default_category: str
    default_style: str


@dataclass(frozen=True)
class BackgroundDownloadConfig:
    enabled: bool
    min_items_per_category: int
    allowed_sources: list[str]


@dataclass(frozen=True)
class PublishingConfig:
    enabled: bool
    provider: str
    mode: str
    privacy_level: str
    disable_duet: bool
    disable_comment: bool
    disable_stitch: bool
    is_aigc: bool
    chunk_size_bytes: int
    request_timeout_seconds: int


@dataclass(frozen=True)
class Settings:
    app: AppConfig
    reddit: RedditConfig
    llm: LLMConfig
    tts: TTSConfig
    video: VideoConfig
    subtitles: SubtitlesConfig
    whisper: WhisperConfig
    backgrounds: BackgroundsConfig
    background_download: BackgroundDownloadConfig
    publishing: PublishingConfig
    database_path: Path
    logs_dir: Path
    cache_dir: Path


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _require_section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"Missing or invalid config section: {name}")
    return section


def load_settings(config_path: str | Path = "config.yaml") -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    resolved_config_path = _resolve_path(config_path)
    if not resolved_config_path.exists():
        raise FileNotFoundError(f"Config file not found: {resolved_config_path}")

    with resolved_config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    app = _require_section(raw, "app")
    reddit = _require_section(raw, "reddit")
    llm = _require_section(raw, "llm")
    tts = _require_section(raw, "tts")
    video = _require_section(raw, "video")
    subtitles = _require_section(raw, "subtitles")
    whisper = _require_section(raw, "whisper")
    backgrounds = _require_section(raw, "backgrounds")
    background_download = raw.get("background_download", {})
    publishing = raw.get("publishing", {})
    storage = raw.get("storage", {})

    return Settings(
        app=AppConfig(
            daily_videos=int(app.get("daily_videos", 3)),
            language=str(app.get("language", "es")),
            output_dir=_resolve_path(app.get("output_dir", "output")),
        ),
        reddit=RedditConfig(
            subreddits=list(reddit.get("subreddits", [])),
            sort=str(reddit.get("sort", "hot")),
            time_filter=str(reddit.get("time_filter", "day")),
            limit_per_subreddit=int(reddit.get("limit_per_subreddit", 25)),
            min_score=int(reddit.get("min_score", 100)),
            min_length=int(reddit.get("min_length", 500)),
            max_length=int(reddit.get("max_length", 15000)),
            request_delay_seconds=float(reddit.get("request_delay_seconds", 1.0)),
            max_retries=int(reddit.get("max_retries", 3)),
        ),
        llm=LLMConfig(
            provider=str(llm.get("provider", "deepseek")),
            model=str(llm.get("model", "deepseek-v4-flash")),
            base_url=str(llm.get("base_url", "https://api.deepseek.com")),
            temperature=float(llm.get("temperature", 0.7)),
            max_output_tokens=int(llm.get("max_output_tokens", 4000)),
            request_timeout_seconds=int(llm.get("request_timeout_seconds", 120)),
            max_retries=int(llm.get("max_retries", 3)),
        ),
        tts=TTSConfig(
            provider=str(tts.get("provider", "kokoro")),
            voice=str(tts.get("voice", "es")),
            speed=float(tts.get("speed", 1.0)),
        ),
        video=VideoConfig(
            width=int(video.get("width", 1080)),
            height=int(video.get("height", 1920)),
            fps=int(video.get("fps", 30)),
            min_duration_seconds=int(video.get("min_duration_seconds", 60)),
            max_duration_seconds=int(video.get("max_duration_seconds", 120)),
            duration_tolerance_seconds=int(video.get("duration_tolerance_seconds", 5)),
            ffmpeg_path=str(video.get("ffmpeg_path", "ffmpeg")),
            ffprobe_path=str(video.get("ffprobe_path", "ffprobe")),
            styles=list(video.get("styles", ["style_01", "style_02", "style_03"])),
        ),
        subtitles=SubtitlesConfig(
            max_chars_per_line=int(subtitles.get("max_chars_per_line", 32)),
            max_lines=int(subtitles.get("max_lines", 2)),
            font_size=int(subtitles.get("font_size", 65)),
            output_dir=_resolve_path(subtitles.get("output_dir", "cache/subtitles")),
        ),
        whisper=WhisperConfig(
            provider=str(whisper.get("provider", "faster-whisper")),
            model_size=str(whisper.get("model_size", "small")),
            device=str(whisper.get("device", "auto")),
            compute_type=str(whisper.get("compute_type", "default")),
            language=str(whisper.get("language", "es")),
            beam_size=int(whisper.get("beam_size", 5)),
        ),
        backgrounds=BackgroundsConfig(
            directory=_resolve_path(backgrounds.get("directory", "backgrounds")),
            avoid_consecutive_repeats=bool(backgrounds.get("avoid_consecutive_repeats", True)),
            min_duration_seconds=int(backgrounds.get("min_duration_seconds", 30)),
            min_width=int(backgrounds.get("min_width", 720)),
            min_height=int(backgrounds.get("min_height", 720)),
            default_category=str(backgrounds.get("default_category", "minecraft")),
            default_style=str(backgrounds.get("default_style", "parkour")),
        ),
        background_download=BackgroundDownloadConfig(
            enabled=bool(background_download.get("enabled", False)),
            min_items_per_category=int(background_download.get("min_items_per_category", 5)),
            allowed_sources=list(background_download.get("allowed_sources", [])),
        ),
        publishing=PublishingConfig(
            enabled=bool(publishing.get("enabled", False)),
            provider=str(publishing.get("provider", "tiktok")),
            mode=str(publishing.get("mode", "upload")),
            privacy_level=str(publishing.get("privacy_level", "SELF_ONLY")),
            disable_duet=bool(publishing.get("disable_duet", False)),
            disable_comment=bool(publishing.get("disable_comment", False)),
            disable_stitch=bool(publishing.get("disable_stitch", False)),
            is_aigc=bool(publishing.get("is_aigc", True)),
            chunk_size_bytes=int(publishing.get("chunk_size_bytes", 10_000_000)),
            request_timeout_seconds=int(publishing.get("request_timeout_seconds", 120)),
        ),
        database_path=_resolve_path(storage.get("database_path", "data/database.db")),
        logs_dir=_resolve_path(storage.get("logs_dir", "logs")),
        cache_dir=_resolve_path(storage.get("cache_dir", "cache")),
    )
