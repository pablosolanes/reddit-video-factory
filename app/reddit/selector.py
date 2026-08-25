from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.config import RedditConfig


CONFLICT_WORDS = {
    "aita",
    "angry",
    "argument",
    "betray",
    "boyfriend",
    "cheat",
    "conflict",
    "confronted",
    "dad",
    "divorce",
    "drama",
    "family",
    "fight",
    "fired",
    "friend",
    "girlfriend",
    "husband",
    "lied",
    "mom",
    "mother",
    "refused",
    "secret",
    "sister",
    "wife",
    "wrong",
}

RETENTION_WORDS = {
    "after",
    "because",
    "but",
    "finally",
    "found out",
    "however",
    "never",
    "realized",
    "then",
    "until",
    "update",
    "when",
}

SPAM_PATTERNS = (
    re.compile(r"\bsubscribe\b|\bfollow me\b|\bonlyfans\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class SelectionResult:
    story: dict[str, Any]
    score: float
    reasons: list[str]


class StorySelector:
    def __init__(self, config: RedditConfig) -> None:
        self.config = config

    def select(self, candidates: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        scored = [result for candidate in candidates if (result := self.evaluate(candidate))]
        scored.sort(key=lambda item: item.score, reverse=True)

        selected: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for result in scored:
            normalized_title = self._normalize(result.story["title"])
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            story = dict(result.story)
            story["internal_score"] = round(result.score, 3)
            story["selection_reasons"] = result.reasons
            selected.append(story)
            if len(selected) >= count:
                break
        return selected

    def evaluate(self, story: dict[str, Any]) -> SelectionResult | None:
        title = str(story.get("title", "")).strip()
        body = str(story.get("body", "")).strip()
        score = int(story.get("score", 0) or 0)
        combined = f"{title}\n{body}"
        text_length = len(body)

        if score < self.config.min_score:
            return None
        if text_length < self.config.min_length or text_length > self.config.max_length:
            return None
        if self._looks_like_spam(combined):
            return None
        if self._is_low_context(body):
            return None

        internal_score = 0.0
        reasons: list[str] = []

        score_component = min(math.log10(max(score, 1)) * 12, 40)
        internal_score += score_component
        reasons.append(f"reddit_score={score}")

        length_component = self._length_score(text_length)
        internal_score += length_component
        reasons.append(f"length={text_length}")

        conflict_hits = self._keyword_hits(combined, CONFLICT_WORDS)
        if conflict_hits:
            internal_score += min(conflict_hits * 6, 24)
            reasons.append(f"conflict_hits={conflict_hits}")

        retention_hits = self._keyword_hits(combined, RETENTION_WORDS)
        if retention_hits:
            internal_score += min(retention_hits * 3, 18)
            reasons.append(f"retention_hits={retention_hits}")

        if "?" in title:
            internal_score += 4
            reasons.append("curiosity_title")
        if body.lower().count("update") > 0:
            internal_score += 5
            reasons.append("has_update")
        if self._has_dialogue(body):
            internal_score += 5
            reasons.append("has_dialogue")

        return SelectionResult(story=story, score=internal_score, reasons=reasons)

    def _length_score(self, text_length: int) -> float:
        target = 3500
        distance = abs(text_length - target)
        return max(0.0, 25.0 - (distance / 180.0))

    def _keyword_hits(self, text: str, keywords: set[str]) -> int:
        lowered = text.lower()
        return sum(1 for keyword in keywords if keyword in lowered)

    def _looks_like_spam(self, text: str) -> bool:
        link_count = len(re.findall(r"https?://", text, flags=re.IGNORECASE))
        if link_count > 2:
            return True
        return any(pattern.search(text) for pattern in SPAM_PATTERNS)

    def _is_low_context(self, body: str) -> bool:
        sentences = re.split(r"[.!?]+", body)
        meaningful_sentences = [sentence.strip() for sentence in sentences if len(sentence.strip()) > 20]
        return len(meaningful_sentences) < 4

    def _has_dialogue(self, body: str) -> bool:
        return '"' in body or "'" in body or " said " in body.lower() or " told " in body.lower()

    def _normalize(self, value: str) -> str:
        return re.sub(r"\W+", " ", value.lower()).strip()
