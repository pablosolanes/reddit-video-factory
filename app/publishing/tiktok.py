from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from app.config import PublishingConfig
from app.publishing.base import Publisher


TIKTOK_BASE_URL = "https://open.tiktokapis.com"


class TikTokConfigurationError(RuntimeError):
    """Raised when TikTok publishing is not configured."""


class TikTokPublishingError(RuntimeError):
    """Raised when TikTok publishing fails."""


@dataclass(frozen=True)
class TikTokPublishResult:
    publish_id: str
    status: str
    raw_response: dict[str, Any]


class TikTokPublisher(Publisher):
    def __init__(self, config: PublishingConfig) -> None:
        self.config = config

    @staticmethod
    def credentials_available() -> bool:
        return bool(os.getenv("TIKTOK_ACCESS_TOKEN"))

    def publish(self, video_path: Path, title: str, description: str) -> TikTokPublishResult:
        if not self.config.enabled:
            raise TikTokConfigurationError("publishing.enabled is false")
        if not self.credentials_available():
            raise TikTokConfigurationError("Missing TIKTOK_ACCESS_TOKEN in .env")
        if self.config.provider != "tiktok":
            raise TikTokConfigurationError(f"Unsupported publishing provider: {self.config.provider}")

        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        caption = self._caption(title, description)
        init_response = self._initialize_upload(video_path, caption)
        upload_url = init_response.get("data", {}).get("upload_url")
        publish_id = init_response.get("data", {}).get("publish_id")
        if not publish_id:
            raise TikTokPublishingError(f"TikTok did not return publish_id: {init_response}")
        if self.config.mode in {"upload", "direct_post"} and not upload_url:
            raise TikTokPublishingError(f"TikTok did not return upload_url for FILE_UPLOAD: {init_response}")

        self._upload_file(video_path, upload_url)
        return TikTokPublishResult(
            publish_id=str(publish_id),
            status="published" if self.config.mode == "direct_post" else "uploaded",
            raw_response=init_response,
        )

    def fetch_status(self, publish_id: str) -> dict[str, Any]:
        response = requests.post(
            f"{TIKTOK_BASE_URL}/v2/post/publish/status/fetch/",
            headers=self._json_headers(),
            json={"publish_id": publish_id},
            timeout=self.config.request_timeout_seconds,
        )
        return self._checked_json(response)

    def _initialize_upload(self, video_path: Path, caption: str) -> dict[str, Any]:
        if self.config.mode == "direct_post":
            endpoint = "/v2/post/publish/video/init/"
            body: dict[str, Any] = {
                "post_info": {
                    "title": caption,
                    "privacy_level": self.config.privacy_level,
                    "disable_duet": self.config.disable_duet,
                    "disable_comment": self.config.disable_comment,
                    "disable_stitch": self.config.disable_stitch,
                    "is_aigc": self.config.is_aigc,
                },
                "source_info": self._file_source_info(video_path),
            }
        elif self.config.mode == "upload":
            endpoint = "/v2/post/publish/inbox/video/init/"
            body = {"source_info": self._file_source_info(video_path)}
        else:
            raise TikTokConfigurationError("publishing.mode must be 'upload' or 'direct_post'")

        response = requests.post(
            f"{TIKTOK_BASE_URL}{endpoint}",
            headers=self._json_headers(),
            json=body,
            timeout=self.config.request_timeout_seconds,
        )
        return self._checked_json(response)

    def _upload_file(self, video_path: Path, upload_url: str) -> None:
        total_size = video_path.stat().st_size
        chunk_size = min(self.config.chunk_size_bytes, total_size)
        with video_path.open("rb") as file:
            start = 0
            while start < total_size:
                chunk = file.read(chunk_size)
                end = start + len(chunk) - 1
                response = requests.put(
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{total_size}",
                    },
                    data=chunk,
                    timeout=self.config.request_timeout_seconds,
                )
                if response.status_code >= 400:
                    raise TikTokPublishingError(f"TikTok upload failed: {response.status_code} {response.text[:1000]}")
                start = end + 1

    def _file_source_info(self, video_path: Path) -> dict[str, Any]:
        video_size = video_path.stat().st_size
        chunk_size = min(self.config.chunk_size_bytes, video_size)
        return {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": int(math.ceil(video_size / chunk_size)),
        }

    def _json_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {os.environ['TIKTOK_ACCESS_TOKEN']}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _checked_json(self, response: requests.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise TikTokPublishingError(f"TikTok API failed: {response.status_code} {response.text[:1000]}")
        data = response.json()
        error = data.get("error", {})
        if error.get("code") not in (None, "ok"):
            raise TikTokPublishingError(json.dumps(error, ensure_ascii=False))
        return data

    def _caption(self, title: str, description: str) -> str:
        caption = f"{title}\n\n{description}".strip()
        return caption[:2200]
