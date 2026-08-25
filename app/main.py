from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.config import Settings, load_settings
from app.backgrounds.tests import run_test_background, run_test_story
from app.database import connect, initialize_database, table_counts
from app.dependencies import check_dependencies, has_missing_required_runtime, print_dependency_report
from app.logging_config import configure_logging
from app.pipeline.generate import run_pipeline
from app.publishing.tiktok_oauth import run_tiktok_login


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reddit Video Factory MVP local")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--test", action="store_true", help="Run a one-video local smoke flow")
    parser.add_argument("--count", type=int, help="Number of videos to generate")
    parser.add_argument("--dry-run", action="store_true", help="Show planned work without paid/API-heavy actions")
    parser.add_argument("--resume", action="store_true", help="Resume incomplete work")
    parser.add_argument("--retry-failed", action="store_true", help="Move failed jobs back into retryable states")
    parser.add_argument("--check-deps", action="store_true", help="Check local dependencies and configured credentials")
    parser.add_argument("--test-background", action="store_true", help="Test visual profile and local background selection")
    parser.add_argument("--test-story", action="store_true", help="Test visual consistency across story parts")
    parser.add_argument("--publish-ready", action="store_true", help="Publish/upload completed videos via the configured official API")
    parser.add_argument("--tiktok-login", action="store_true", help="Run local TikTok OAuth and print tokens for .env")
    parser.add_argument("--tiktok-redirect-uri", default="http://127.0.0.1:8765/callback/", help="TikTok OAuth redirect URI")
    parser.add_argument("--log-level", default="INFO", help="Logging level: DEBUG, INFO, WARNING, ERROR")
    return parser.parse_args()


def ensure_directories(settings: Settings) -> None:
    directories: list[Path] = [
        settings.app.output_dir,
        settings.backgrounds.directory,
        settings.cache_dir,
        settings.cache_dir / "audio",
        settings.cache_dir / "transcripts",
        settings.cache_dir / "llm",
        settings.subtitles.output_dir,
        settings.logs_dir,
        settings.database_path.parent,
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def main() -> int:
    args = parse_args()
    settings = load_settings(args.config)
    configure_logging(settings.logs_dir, args.log_level)
    ensure_directories(settings)

    logger.info("Starting Reddit Video Factory")
    logger.info("Config loaded")

    if args.check_deps:
        statuses = check_dependencies(settings)
        print_dependency_report(statuses)
        return 1 if has_missing_required_runtime(statuses) else 0

    if args.test_background:
        run_test_background(settings)
        return 0

    if args.test_story:
        run_test_story(settings)
        return 0

    if args.tiktok_login:
        run_tiktok_login(args.tiktok_redirect_uri, ["user.info.basic", "video.upload"])
        return 0

    with connect(settings.database_path) as connection:
        initialize_database(connection)
        counts = table_counts(connection)

    requested_count = 1 if args.test else args.count or settings.app.daily_videos
    run_pipeline(
        settings=settings,
        count=requested_count,
        dry_run=args.dry_run,
        resume=args.resume,
        retry_failed=args.retry_failed,
        publish_ready=args.publish_ready,
        test=args.test,
        database_counts=counts,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
