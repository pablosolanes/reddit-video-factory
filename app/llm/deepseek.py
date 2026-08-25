from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from app.config import LLMConfig
from app.llm.base import LLMProvider
from app.llm.prompts import (
    SCRIPT_GENERATION_SYSTEM_PROMPT,
    SCRIPT_PROMPT_VERSION,
    build_script_generation_user_prompt,
)


logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM provider cannot be configured."""


class LLMResponseError(RuntimeError):
    """Raised when the LLM response is missing or invalid."""


class DeepSeekProvider(LLMProvider):
    def __init__(self, config: LLMConfig, cache_dir: str | Path) -> None:
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def credentials_available() -> bool:
        return bool(os.getenv("DEEPSEEK_API_KEY"))

    def select_stories(self, candidates: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        # Phase 3 keeps selection local; this hook preserves the provider contract for later LLM ranking.
        return candidates[:count]

    def cache_path_for_story(self, story: dict[str, Any]) -> Path:
        source = {
            "prompt_version": SCRIPT_PROMPT_VERSION,
            "provider": "deepseek",
            "model": self.config.model,
            "reddit_id": story.get("reddit_id"),
            "title": story.get("title"),
            "body": story.get("body"),
        }
        digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        reddit_id = str(story.get("reddit_id") or "unknown")
        return self.cache_dir / f"{reddit_id}-{digest[:16]}.json"

    def generate_script(self, story: dict[str, Any]) -> dict[str, Any]:
        cache_path = self.cache_path_for_story(story)
        if cache_path.exists():
            logger.info("Using cached LLM script: %s", cache_path)
            with cache_path.open("r", encoding="utf-8") as file:
                cached = json.load(file)
            return self._validate_script_payload(cached)

        if not self.credentials_available():
            raise LLMConfigurationError("Missing DEEPSEEK_API_KEY in .env")

        payload = self._request_payload(story)
        response_json = self._post_with_retries(payload)
        content = self._extract_content(response_json)
        script_payload = self._validate_script_payload(json.loads(content))

        cache_document = {
            **script_payload,
            "_cache": {
                "provider": "deepseek",
                "model": self.config.model,
                "prompt_version": SCRIPT_PROMPT_VERSION,
                "reddit_id": story.get("reddit_id"),
            },
        }
        with cache_path.open("w", encoding="utf-8") as file:
            json.dump(cache_document, file, ensure_ascii=False, indent=2)
        return script_payload

    def _request_payload(self, story: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SCRIPT_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": build_script_generation_user_prompt(story)},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }

    def _post_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.request_timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                wait_seconds = min(2**attempt, 30)
                logger.warning(
                    "DeepSeek request failed attempt %s/%s: %s",
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                time.sleep(wait_seconds)

        raise RuntimeError("DeepSeek request failed after retries") from last_error

    def _extract_content(self, response_json: dict[str, Any]) -> str:
        try:
            content = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("DeepSeek response did not contain choices[0].message.content") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("DeepSeek returned empty content")
        return content

    def _validate_script_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        required_strings = ("title", "hook", "script", "description")
        for field in required_strings:
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise LLMResponseError(f"Script JSON missing non-empty field: {field}")

        hashtags = payload.get("hashtags")
        if not isinstance(hashtags, list) or not all(isinstance(item, str) for item in hashtags):
            raise LLMResponseError("Script JSON field 'hashtags' must be a list of strings")

        parts = payload.get("parts")
        if not isinstance(parts, list) or not parts:
            raise LLMResponseError("Script JSON field 'parts' must be a non-empty list")

        visual_profile = payload.get("visual_profile")
        if not isinstance(visual_profile, dict):
            payload["visual_profile"] = {
                "category": "minecraft",
                "style": "parkour",
                "mood": "energetic",
                "color_style": "normal",
                "subtitle_style": "style_01",
            }
        else:
            payload["visual_profile"] = {
                "category": str(visual_profile.get("category") or "minecraft"),
                "style": str(visual_profile.get("style") or "parkour"),
                "mood": str(visual_profile.get("mood") or "neutral"),
                "color_style": str(visual_profile.get("color_style") or "normal"),
                "subtitle_style": str(visual_profile.get("subtitle_style") or "style_01"),
            }

        for index, part in enumerate(parts, start=1):
            if not isinstance(part, dict):
                raise LLMResponseError("Each part must be an object")
            if int(part.get("part_number", index)) != index:
                part["part_number"] = index
            if not isinstance(part.get("text"), str) or not part["text"].strip():
                raise LLMResponseError("Each part must contain non-empty text")
            if "estimated_duration_seconds" in part:
                part["estimated_duration_seconds"] = int(part["estimated_duration_seconds"])

        payload["estimated_duration_seconds"] = int(payload.get("estimated_duration_seconds", 0) or 0)
        return payload
