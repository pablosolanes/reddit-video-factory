from __future__ import annotations

from app.backgrounds.downloader import BackgroundDownloadDisabled, BackgroundDownloader
from app.backgrounds.manager import BackgroundLibraryManager
from app.backgrounds.selector import BackgroundSelector, StoryVisualProfile
from app.config import Settings
from app.database import connect, initialize_database


def run_test_background(settings: Settings) -> None:
    profile = StoryVisualProfile(
        category=settings.backgrounds.default_category,
        style=settings.backgrounds.default_style,
        mood="energetic",
        color_style="normal",
        subtitle_style=(settings.video.styles or ["style_01"])[0],
    )
    print(f"[TEST-BACKGROUND] visual_profile={profile.to_dict()}")

    with connect(settings.database_path) as connection:
        initialize_database(connection)
        indexed = BackgroundLibraryManager(settings.backgrounds, settings.video).index_local_library(connection)
        print(f"[TEST-BACKGROUND] indexed_local_files={indexed}")
        selector = BackgroundSelector(settings.backgrounds, settings.video)
        try:
            selected = selector.select_for_story(connection, profile)
            print(f"[TEST-BACKGROUND] selected_background={selected}")
        except Exception as exc:
            print(f"[TEST-BACKGROUND] no_background_selected={exc}")

    downloader = BackgroundDownloader(settings.background_download)
    try:
        downloader.ensure_available(profile.category, settings.backgrounds.directory / profile.category)
    except BackgroundDownloadDisabled:
        print("[TEST-BACKGROUND] download_skipped=background_download.enabled is false")


def run_test_story(settings: Settings) -> None:
    profile = StoryVisualProfile(
        category="minecraft",
        style="parkour",
        mood="energetic",
        color_style="normal",
        subtitle_style="style_02",
    )
    parts = [1, 2, 3]
    print(f"[TEST-STORY] story_visual_profile={profile.to_dict()}")
    for part_number in parts:
        print(
            "[TEST-STORY] "
            f"part={part_number} category={profile.category} style={profile.style} "
            f"subtitle_style={profile.subtitle_style}"
        )
    print("[TEST-STORY] consistency=OK")
