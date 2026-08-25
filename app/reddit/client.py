from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import RedditConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedditPost:
    reddit_id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "reddit_id": self.reddit_id,
            "subreddit": self.subreddit,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "score": self.score,
            "created_at": self.created_at,
        }


class RedditCredentialsError(RuntimeError):
    """Raised when Reddit API credentials are not configured."""


class RedditClient:
    def __init__(self, config: RedditConfig) -> None:
        self.config = config
        self._reddit = None

    @staticmethod
    def credentials_available() -> bool:
        required = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
        return all(os.getenv(name) for name in required)

    def fetch_candidates(self, existing_reddit_ids: set[str]) -> list[dict[str, Any]]:
        reddit = self._get_reddit()
        candidates: list[dict[str, Any]] = []

        for subreddit_name in self.config.subreddits:
            logger.info("Fetching r/%s", subreddit_name)
            submissions = self._fetch_subreddit(reddit, subreddit_name)
            for submission in submissions:
                post = self._submission_to_post(submission)
                if post is None:
                    continue
                if post.reddit_id in existing_reddit_ids:
                    logger.debug("Skipping duplicate reddit_id=%s", post.reddit_id)
                    continue
                candidates.append(post.to_dict())
            time.sleep(max(self.config.request_delay_seconds, 0))

        return candidates

    def _get_reddit(self):
        if self._reddit is not None:
            return self._reddit

        if not self.credentials_available():
            raise RedditCredentialsError(
                "Missing REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET or REDDIT_USER_AGENT in .env"
            )

        try:
            import praw
        except ImportError as exc:
            raise RuntimeError("PRAW is not installed. Run: python -m pip install -r requirements.txt") from exc

        self._reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ["REDDIT_USER_AGENT"],
            check_for_async=False,
        )
        self._reddit.read_only = True
        return self._reddit

    def _fetch_subreddit(self, reddit, subreddit_name: str):
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                subreddit = reddit.subreddit(subreddit_name)
                sort = self.config.sort.lower()
                limit = self.config.limit_per_subreddit
                if sort == "new":
                    return list(subreddit.new(limit=limit))
                if sort == "top":
                    return list(subreddit.top(time_filter=self.config.time_filter, limit=limit))
                if sort == "rising":
                    return list(subreddit.rising(limit=limit))
                return list(subreddit.hot(limit=limit))
            except Exception as exc:  # PRAW wraps several HTTP/rate-limit failures.
                last_error = exc
                wait_seconds = min(2**attempt, 30)
                logger.warning(
                    "Reddit fetch failed for r/%s attempt %s/%s: %s",
                    subreddit_name,
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                time.sleep(wait_seconds)

        raise RuntimeError(f"Could not fetch r/{subreddit_name}") from last_error

    def _submission_to_post(self, submission) -> RedditPost | None:
        body = (getattr(submission, "selftext", "") or "").strip()
        title = (getattr(submission, "title", "") or "").strip()
        reddit_id = str(getattr(submission, "id", "") or "").strip()

        if not reddit_id or not title or not body:
            return None
        if body in {"[deleted]", "[removed]"}:
            return None
        if getattr(submission, "stickied", False):
            return None
        if getattr(submission, "removed_by_category", None):
            return None

        created_utc = float(getattr(submission, "created_utc", 0) or 0)
        created_at = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
        permalink = getattr(submission, "permalink", "")

        return RedditPost(
            reddit_id=reddit_id,
            subreddit=str(getattr(submission, "subreddit", "")),
            title=title,
            body=body,
            url=f"https://www.reddit.com{permalink}" if permalink else str(getattr(submission, "url", "")),
            score=int(getattr(submission, "score", 0) or 0),
            created_at=created_at,
        )
