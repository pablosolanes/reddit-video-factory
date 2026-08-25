from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    ok: bool
    detail: str


def check_dependencies(settings: Settings) -> list[DependencyStatus]:
    checks = [
        _python_version(),
        _python_package("yaml", "PyYAML"),
        _python_package("dotenv", "python-dotenv"),
        _python_package("praw", "praw"),
        _python_package("requests", "requests"),
        _python_package("kokoro", "kokoro"),
        _python_package("soundfile", "soundfile"),
        _python_package("faster_whisper", "faster-whisper"),
        _executable("ffmpeg", settings.video.ffmpeg_path),
        _executable("ffprobe", settings.video.ffprobe_path),
        _executable("espeak-ng", "espeak-ng"),
        _env_var("DEEPSEEK_API_KEY"),
        _env_var("REDDIT_CLIENT_ID"),
        _env_var("REDDIT_CLIENT_SECRET"),
        _env_var("REDDIT_USER_AGENT"),
        _env_var("TIKTOK_CLIENT_KEY"),
        _env_var("TIKTOK_CLIENT_SECRET"),
        _env_var("TIKTOK_ACCESS_TOKEN"),
        _env_var("TIKTOK_REFRESH_TOKEN"),
    ]
    return checks


def print_dependency_report(statuses: list[DependencyStatus]) -> None:
    for status in statuses:
        marker = "OK" if status.ok else "MISSING"
        print(f"[CHECK] {marker} {status.name}: {status.detail}")


def has_missing_required_runtime(statuses: list[DependencyStatus]) -> bool:
    required = {"Python", "PyYAML", "python-dotenv", "praw", "requests", "ffmpeg", "ffprobe"}
    return any(status.name in required and not status.ok for status in statuses)


def _python_version() -> DependencyStatus:
    version = sys.version_info
    ok = (3, 11) <= (version.major, version.minor) < (3, 13)
    detail = (
        f"{version.major}.{version.minor}.{version.micro}"
        if ok
        else f"{version.major}.{version.minor}.{version.micro}; install Python 3.11 or 3.12 for Kokoro compatibility"
    )
    return DependencyStatus("Python", ok, detail)


def _python_package(module_name: str, display_name: str) -> DependencyStatus:
    ok = importlib.util.find_spec(module_name) is not None
    detail = "installed" if ok else "install with: python -m pip install -r requirements.txt"
    return DependencyStatus(display_name, ok, detail)


def _executable(display_name: str, executable: str) -> DependencyStatus:
    resolved = shutil.which(executable)
    return DependencyStatus(display_name, bool(resolved), resolved or f"not found on PATH: {executable}")


def _env_var(name: str) -> DependencyStatus:
    ok = bool(os.getenv(name))
    detail = "configured" if ok else "not configured in .env"
    return DependencyStatus(name, ok, detail)
