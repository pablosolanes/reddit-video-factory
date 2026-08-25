from __future__ import annotations

import json
import logging
import random
from datetime import date
from pathlib import Path

from app.config import Settings
from app.backgrounds.manager import BackgroundLibraryManager
from app.backgrounds.selector import (
    BackgroundSelectionError,
    BackgroundSelector,
    StoryVisualProfile,
)
from app.database import (
    connect,
    get_existing_reddit_ids,
    get_background_path_for_story,
    get_parts_needing_audio,
    get_parts_needing_subtitles,
    get_parts_ready_for_video,
    get_pending_stories,
    get_publishable_videos,
    insert_video_record,
    insert_story,
    insert_script_with_parts,
    mark_part_failed,
    mark_story_failed,
    reset_interrupted_jobs,
    retry_failed_jobs,
    script_exists_for_story,
    table_counts,
    update_part_audio,
    update_part_subtitles,
    update_story_score,
    mark_background_used,
    upsert_publication,
)
from app.llm.deepseek import DeepSeekProvider, LLMConfigurationError
from app.reddit.client import RedditClient, RedditCredentialsError
from app.reddit.selector import StorySelector
from app.subtitles.ass import AssSubtitleWriter
from app.subtitles.whisper import WhisperConfigurationError, WhisperTranscriber
from app.tts.kokoro import KokoroTTSProvider, TTSConfigurationError
from app.video.renderer import VideoRenderError, VideoRenderer
from app.publishing.tiktok import TikTokConfigurationError, TikTokPublisher


logger = logging.getLogger(__name__)


def run_pipeline(
    settings: Settings,
    count: int,
    dry_run: bool,
    resume: bool,
    retry_failed: bool,
    publish_ready: bool,
    test: bool,
    database_counts: dict[str, int],
) -> None:
    mode = "test" if test else "normal"
    logger.info(
        "Pipeline mode=%s count=%s dry_run=%s resume=%s retry_failed=%s",
        mode,
        count,
        dry_run,
        resume,
        retry_failed,
    )

    print("[CONFIG] OK")
    print(f"[DATABASE] OK: {settings.database_path}")
    print(f"[DATABASE] Current rows: {database_counts}")
    print(f"[PIPELINE] Mode={mode} Count={count} Dry-run={dry_run} Resume={resume} Retry-failed={retry_failed}")

    selector = StorySelector(settings.reddit)
    with connect(settings.database_path) as connection:
        if dry_run:
            print("[RECOVERY] Dry-run: no job states will be changed.")
        else:
            recovered = reset_interrupted_jobs(connection)
            if any(recovered.values()):
                print(f"[RECOVERY] Reset interrupted jobs: {recovered}")
            if retry_failed:
                retried = retry_failed_jobs(connection)
                print(f"[RECOVERY] Retrying failed jobs: {retried}")

        existing_ids = get_existing_reddit_ids(connection)
        print("[REDDIT] Searching...")
        print(f"[REDDIT] Existing stories in SQLite: {len(existing_ids)}")

        fetched_candidates: list[dict] = []
        client = RedditClient(settings.reddit)
        if dry_run:
            print("[REDDIT] Skipped: dry-run never calls external APIs.")
            print("[DRY-RUN] With a real run, this would fetch, filter and rank Reddit stories.")
        elif resume:
            print("[REDDIT] Skipped: resume mode uses existing pending stories.")
        else:
            try:
                fetched_candidates = client.fetch_candidates(existing_ids)
            except RedditCredentialsError as exc:
                print(f"[REDDIT] ERROR: {exc}")
                print("[REDDIT] Add credentials to .env before running Phase 2 against Reddit.")
                raise

        selected = selector.select(fetched_candidates, count)
        print(f"[REDDIT] Found {len(fetched_candidates)} new candidates")
        print(f"[SELECTOR] Selected {len(selected)} stories")

        for index, story in enumerate(selected, start=1):
            print(
                f"[SELECTOR] {index}. r/{story['subreddit']} | "
                f"score={story['score']} | internal={story['internal_score']} | {story['title']}"
            )

        if dry_run:
            print("[DRY-RUN] No stories were written and no statuses were changed.")
            pending = get_pending_stories(connection, count)
            print(f"[LLM] Would generate scripts for up to {len(pending) or len(selected)} stories.")
            parts = get_parts_needing_audio(connection, count)
            print(f"[TTS] Would generate audio for up to {len(parts)} pending parts.")
            subtitle_parts = get_parts_needing_subtitles(connection, count)
            print(f"[WHISPER] Would transcribe up to {len(subtitle_parts)} audio parts.")
            print(f"[SUBTITLES] Would generate up to {len(subtitle_parts)} ASS files.")
            video_parts = get_parts_ready_for_video(connection, count)
            print(f"[VIDEO] Would render up to {len(video_parts)} videos.")
            publishable = get_publishable_videos(connection, settings.publishing.provider, settings.publishing.mode, count)
            print(f"[PUBLISH] Would process up to {len(publishable)} ready videos.")
            print("[BACKGROUNDS] Dry-run: no local library indexing or usage counters changed.")
            print("[PHASE 4] OK")
            print("[PHASE 5] OK")
            print("[PHASE 6] OK")
            print("[PHASE 7] OK")
            return

        inserted = 0
        for story in selected:
            story["status"] = "pending"
            if insert_story(connection, story):
                inserted += 1
            update_story_score(connection, story["reddit_id"], float(story["internal_score"]))

        pending = get_pending_stories(connection, count)
        if resume:
            print(f"[RESUME] Pending stories available: {len(pending)}")

        counts = table_counts(connection)

        print(f"[DATABASE] Inserted {inserted} selected stories")
        print(f"[DATABASE] Pending stories ready for Phase 3: {len(pending)}")
        print(f"[DATABASE] Updated rows: {counts}")

        if not pending:
            print("[LLM] No pending stories to script.")
        elif settings.llm.provider != "deepseek":
            raise ValueError(f"Unsupported LLM provider: {settings.llm.provider}")
        else:
            llm = DeepSeekProvider(settings.llm, settings.cache_dir / "llm")
            generated = 0
            skipped = 0
            failed = 0

            for index, row in enumerate(pending, start=1):
                story_id = int(row["id"])
                if script_exists_for_story(connection, story_id):
                    skipped += 1
                    print(f"[LLM] Skipping story {story_id}: script already exists")
                    continue

                story = dict(row)
                print(f"[LLM] Generating script {index}/{len(pending)} for story {story_id}")
                try:
                    script_payload = llm.generate_script(story)
                    insert_script_with_parts(connection, story_id, script_payload)
                    generated += 1
                    print("[LLM] OK")
                except LLMConfigurationError as exc:
                    print(f"[LLM] ERROR: {exc}")
                    print("[LLM] Add DEEPSEEK_API_KEY to .env before running Phase 3.")
                    raise
                except Exception as exc:
                    failed += 1
                    logger.exception("LLM script generation failed for story_id=%s", story_id)
                    mark_story_failed(connection, story_id, str(exc))
                    print(f"[LLM] FAILED story {story_id}: {exc}")

            counts = table_counts(connection)
            print(f"[LLM] Generated={generated} Skipped={skipped} Failed={failed}")
            print(f"[DATABASE] Updated rows: {counts}")

        parts = get_parts_needing_audio(connection, count)
        if not parts:
            print("[TTS] No pending parts need audio.")
        elif settings.tts.provider != "kokoro":
            raise ValueError(f"Unsupported TTS provider: {settings.tts.provider}")
        else:
            tts = KokoroTTSProvider(settings.tts, settings.cache_dir / "audio")
            generated_audio = 0
            failed_audio = 0
            print(f"[TTS] Pending parts: {len(parts)}")

            for index, part in enumerate(parts, start=1):
                part_id = int(part["id"])
                stem = f"story_{part['story_id']}_part_{part['part_number']}"
                audio_path = tts.cache_path_for_text(str(part["text"]), stem)
                print(f"[TTS] Generating audio {index}/{len(parts)} for part {part_id}")
                try:
                    duration = tts.synthesize(str(part["text"]), audio_path)
                    update_part_audio(connection, part_id, str(audio_path), duration)
                    generated_audio += 1
                    print(f"[TTS] OK duration={duration:.2f}s")
                except TTSConfigurationError as exc:
                    print(f"[TTS] ERROR: {exc}")
                    print("[TTS] Install/configure Kokoro and espeak-ng before running Phase 4.")
                    raise
                except Exception as exc:
                    failed_audio += 1
                    logger.exception("TTS generation failed for part_id=%s", part_id)
                    mark_part_failed(connection, part_id, str(exc))
                    print(f"[TTS] FAILED part {part_id}: {exc}")

            counts = table_counts(connection)
            print(f"[TTS] Generated={generated_audio} Failed={failed_audio}")
            print(f"[DATABASE] Updated rows: {counts}")

        subtitle_parts = get_parts_needing_subtitles(connection, count)
        if not subtitle_parts:
            print("[WHISPER] No audio parts need transcription/subtitles.")
        else:
            transcriber = WhisperTranscriber(settings.whisper, settings.cache_dir / "transcripts")
            subtitle_writer = AssSubtitleWriter(settings.subtitles, settings.video)
            transcribed = 0
            failed_subtitles = 0
            print(f"[WHISPER] Pending audio parts: {len(subtitle_parts)}")

            for index, part in enumerate(subtitle_parts, start=1):
                part_id = int(part["id"])
                audio_path = str(part["audio_path"])
                subtitle_path = subtitle_writer.cache_path_for_part(part_id)
                print(f"[WHISPER] Transcribing {index}/{len(subtitle_parts)} for part {part_id}")
                try:
                    transcript = transcriber.transcribe(audio_path)
                    transcript_path = transcriber.cache_path_for_audio(audio_path)
                    subtitle_writer.write(transcript, subtitle_path)
                    update_part_subtitles(connection, part_id, str(transcript_path), str(subtitle_path))
                    transcribed += 1
                    print("[SUBTITLES] OK")
                except WhisperConfigurationError as exc:
                    print(f"[WHISPER] ERROR: {exc}")
                    print("[WHISPER] Install faster-whisper before running Phase 5.")
                    raise
                except Exception as exc:
                    failed_subtitles += 1
                    logger.exception("Subtitle generation failed for part_id=%s", part_id)
                    mark_part_failed(connection, part_id, str(exc))
                    print(f"[SUBTITLES] FAILED part {part_id}: {exc}")

            counts = table_counts(connection)
            print(f"[WHISPER] Transcribed={transcribed} Failed={failed_subtitles}")
            print(f"[DATABASE] Updated rows: {counts}")

        background_manager = BackgroundLibraryManager(settings.backgrounds, settings.video)
        try:
            indexed_backgrounds = background_manager.index_local_library(connection)
            print(f"[BACKGROUNDS] Indexed local files: {indexed_backgrounds}")
        except Exception as exc:
            logger.warning("Background indexing failed: %s", exc)
            print(f"[BACKGROUNDS] WARNING: Could not index local library: {exc}")

        video_parts = get_parts_ready_for_video(connection, count)
        if not video_parts:
            print("[VIDEO] No subtitle-ready parts need rendering.")
            print("[PHASE 6] OK")
            _publish_ready_videos(connection, settings, count, publish_ready)
            print("[PHASE 7] OK")
            return

        background_selector = BackgroundSelector(settings.backgrounds, settings.video)
        renderer = VideoRenderer(settings.video)
        rendered = 0
        failed_videos = 0
        output_dir = _daily_output_dir(settings)
        print(f"[VIDEO] Pending renders: {len(video_parts)}")

        for index, part in enumerate(video_parts, start=1):
            part_id = int(part["id"])
            visual_profile = StoryVisualProfile.from_json(
                part["visual_profile_json"],
                settings.backgrounds,
                random.choice(settings.video.styles or ["style_01"]),
            )
            style = visual_profile.subtitle_style
            video_path = _next_output_path(output_dir, ".mp4")
            metadata_path = video_path.with_suffix(".json")
            part_label = f"Parte {int(part['part_number'])}/{int(part['total_parts'])}"
            print(f"[VIDEO] Rendering {index}/{len(video_parts)} for part {part_id}")

            try:
                existing_story_background = get_background_path_for_story(connection, int(part["story_id"]))
                background_path = (
                    Path(existing_story_background)
                    if existing_story_background
                    else background_selector.select_for_story(connection, visual_profile)
                )
                metadata = _metadata_for_part(part, float(part["duration"] or 0.0))
                metadata["visual_profile"] = visual_profile.to_dict()
                result = renderer.render(
                    background_path=background_path,
                    audio_path=part["audio_path"],
                    subtitle_path=part["subtitle_path"],
                    output_path=video_path,
                    metadata_path=metadata_path,
                    metadata=metadata,
                    style=style,
                    part_label=part_label,
                )
                insert_video_record(
                    connection=connection,
                    part_id=part_id,
                    background_path=str(background_path),
                    subtitle_path=str(part["subtitle_path"]),
                    video_path=str(result.video_path),
                    metadata_path=str(result.metadata_path),
                    style=style,
                    duration=result.duration,
                    status="completed",
                )
                mark_background_used(connection, str(background_path))
                rendered += 1
                print(f"[VIDEO] OK {result.video_path}")
            except (BackgroundSelectionError, FileNotFoundError, VideoRenderError) as exc:
                failed_videos += 1
                logger.exception("Video rendering failed for part_id=%s", part_id)
                insert_video_record(
                    connection=connection,
                    part_id=part_id,
                    background_path="",
                    subtitle_path=str(part["subtitle_path"]),
                    video_path=str(video_path),
                    metadata_path=str(metadata_path),
                    style=style,
                    duration=float(part["duration"] or 0.0),
                    status="failed",
                    error=str(exc),
                )
                print(f"[VIDEO] FAILED part {part_id}: {exc}")

        counts = table_counts(connection)
        print(f"[VIDEO] Rendered={rendered} Failed={failed_videos}")
        print(f"[DATABASE] Updated rows: {counts}")
        print("[PHASE 6] OK")
        _publish_ready_videos(connection, settings, count, publish_ready)
        print("[PHASE 7] OK")


def _publish_ready_videos(connection, settings: Settings, count: int, publish_ready: bool) -> None:
    if not publish_ready:
        print("[PUBLISH] Skipped: use --publish-ready to upload completed videos.")
        return
    if not settings.publishing.enabled:
        print("[PUBLISH] Skipped: publishing.enabled is false.")
        return
    if settings.publishing.provider != "tiktok":
        raise ValueError(f"Unsupported publishing provider: {settings.publishing.provider}")

    publisher = TikTokPublisher(settings.publishing)
    videos = get_publishable_videos(connection, settings.publishing.provider, settings.publishing.mode, count)
    if not videos:
        print("[PUBLISH] No completed videos ready for TikTok.")
        return

    uploaded = 0
    failed = 0
    print(f"[PUBLISH] Ready videos: {len(videos)}")
    for video in videos:
        video_id = int(video["id"])
        try:
            metadata = _load_video_metadata(video["metadata_path"])
            result = publisher.publish(
                Path(video["video_path"]),
                str(metadata.get("title") or "Reddit story"),
                _description_with_hashtags(metadata),
            )
            upsert_publication(
                connection,
                video_id,
                settings.publishing.provider,
                settings.publishing.mode,
                result.publish_id,
                result.status,
            )
            uploaded += 1
            print(f"[PUBLISH] OK video_id={video_id} publish_id={result.publish_id} status={result.status}")
        except TikTokConfigurationError as exc:
            print(f"[PUBLISH] ERROR: {exc}")
            raise
        except Exception as exc:
            failed += 1
            logger.exception("Publishing failed for video_id=%s", video_id)
            upsert_publication(
                connection,
                video_id,
                settings.publishing.provider,
                settings.publishing.mode,
                None,
                "failed",
                str(exc),
            )
            print(f"[PUBLISH] FAILED video_id={video_id}: {exc}")
    print(f"[PUBLISH] Uploaded={uploaded} Failed={failed}")


def _daily_output_dir(settings: Settings) -> Path:
    output_dir = settings.app.output_dir / date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _next_output_path(output_dir: Path, suffix: str) -> Path:
    index = 1
    while True:
        candidate = output_dir / f"video_{index:03d}{suffix}"
        if not candidate.exists() and not candidate.with_suffix(".json").exists():
            return candidate
        index += 1


def _metadata_for_part(part, duration: float) -> dict:
    try:
        hashtags = json.loads(part["hashtags_json"] or "[]")
    except json.JSONDecodeError:
        hashtags = []
    return {
        "title": part["script_title"],
        "description": part["description"] or "",
        "hashtags": hashtags,
        "source_subreddit": part["subreddit"],
        "source_url": part["source_url"],
        "duration": duration,
    }


def _load_video_metadata(metadata_path: str | Path) -> dict:
    path = Path(metadata_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _description_with_hashtags(metadata: dict) -> str:
    description = str(metadata.get("description") or "")
    hashtags = metadata.get("hashtags") or []
    hashtag_text = " ".join(str(item) for item in hashtags)
    return f"{description}\n\n{hashtag_text}".strip()
