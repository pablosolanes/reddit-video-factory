from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reddit_id TEXT NOT NULL UNIQUE,
    subreddit TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    internal_score REAL,
    visual_profile_json TEXT,
    created_at_local TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    hook TEXT NOT NULL,
    script TEXT NOT NULL,
    description TEXT,
    hashtags_json TEXT,
    estimated_duration_seconds INTEGER,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (story_id) REFERENCES stories(id)
);

CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL,
    part_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    audio_path TEXT,
    duration REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (script_id) REFERENCES scripts(id),
    UNIQUE (script_id, part_number)
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL,
    background_path TEXT,
    subtitle_path TEXT,
    video_path TEXT,
    metadata_path TEXT,
    style TEXT,
    duration REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (part_id) REFERENCES parts(id)
);

CREATE TABLE IF NOT EXISTS backgrounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    subcategory TEXT,
    source_url TEXT,
    source_platform TEXT,
    author TEXT,
    license TEXT,
    license_status TEXT NOT NULL DEFAULT 'manual',
    downloaded_at TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    file_hash TEXT,
    times_used INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    mode TEXT NOT NULL,
    publish_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (video_id) REFERENCES videos(id),
    UNIQUE (video_id, platform, mode)
);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    _ensure_column(connection, "stories", "visual_profile_json", "TEXT")
    _ensure_column(connection, "parts", "transcript_path", "TEXT")
    _ensure_column(connection, "parts", "subtitle_path", "TEXT")
    _ensure_column(connection, "backgrounds", "license_status", "TEXT NOT NULL DEFAULT 'manual'")
    connection.commit()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = ("stories", "scripts", "parts", "videos", "backgrounds", "publications")
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def reset_interrupted_jobs(connection: sqlite3.Connection) -> dict[str, int]:
    stories = connection.execute(
        "UPDATE stories SET status = 'pending', error = NULL WHERE status = 'processing'"
    ).rowcount
    parts = connection.execute(
        "UPDATE parts SET status = 'pending', error = NULL, updated_at = CURRENT_TIMESTAMP WHERE status = 'processing'"
    ).rowcount
    videos = connection.execute(
        """
        UPDATE videos
        SET status = 'failed', error = 'Interrupted before completion'
        WHERE status = 'processing'
        """
    ).rowcount
    connection.commit()
    return {"stories": stories, "parts": parts, "videos": videos}


def retry_failed_jobs(connection: sqlite3.Connection) -> dict[str, int]:
    stories = connection.execute(
        "UPDATE stories SET status = 'pending', error = NULL WHERE status = 'failed'"
    ).rowcount
    parts = connection.execute(
        """
        UPDATE parts
        SET status = CASE
                WHEN audio_path IS NULL OR audio_path = '' THEN 'pending'
                ELSE 'completed'
            END,
            error = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'failed'
        """
    ).rowcount
    videos = connection.execute(
        "UPDATE videos SET status = 'pending', error = NULL WHERE status = 'failed'"
    ).rowcount
    publications = connection.execute(
        "UPDATE publications SET status = 'pending', error = NULL, updated_at = CURRENT_TIMESTAMP WHERE status = 'failed'"
    ).rowcount
    connection.commit()
    return {"stories": stories, "parts": parts, "videos": videos, "publications": publications}


def get_existing_reddit_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT reddit_id FROM stories").fetchall()
    return {str(row["reddit_id"]) for row in rows}


def insert_story(connection: sqlite3.Connection, story: dict[str, Any]) -> bool:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO stories (
            reddit_id, subreddit, title, body, url, score, created_at, status, internal_score, visual_profile_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            story["reddit_id"],
            story["subreddit"],
            story["title"],
            story["body"],
            story["url"],
            int(story["score"]),
            story.get("created_at"),
            story.get("status", "pending"),
            story.get("internal_score"),
            json.dumps(story.get("visual_profile"), ensure_ascii=False) if story.get("visual_profile") else None,
        ),
    )
    connection.commit()
    return cursor.rowcount > 0


def update_story_score(connection: sqlite3.Connection, reddit_id: str, internal_score: float) -> None:
    connection.execute(
        "UPDATE stories SET internal_score = ? WHERE reddit_id = ?",
        (internal_score, reddit_id),
    )
    connection.commit()


def get_pending_stories(connection: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT *
        FROM stories
        WHERE status = 'pending'
        ORDER BY internal_score DESC, score DESC, created_at DESC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    return list(connection.execute(query, params).fetchall())


def mark_stories_processing(connection: sqlite3.Connection, story_ids: list[int]) -> None:
    if not story_ids:
        return
    placeholders = ",".join("?" for _ in story_ids)
    connection.execute(
        f"UPDATE stories SET status = 'processing' WHERE id IN ({placeholders})",
        tuple(story_ids),
    )
    connection.commit()


def get_story_by_id(connection: sqlite3.Connection, story_id: int) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()


def script_exists_for_story(connection: sqlite3.Connection, story_id: int) -> bool:
    row = connection.execute("SELECT 1 FROM scripts WHERE story_id = ? LIMIT 1", (story_id,)).fetchone()
    return row is not None


def insert_script_with_parts(
    connection: sqlite3.Connection,
    story_id: int,
    script_payload: dict[str, Any],
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO scripts (
            story_id, title, hook, script, description, hashtags_json,
            estimated_duration_seconds, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            story_id,
            script_payload["title"],
            script_payload["hook"],
            script_payload["script"],
            script_payload.get("description"),
            json.dumps(script_payload.get("hashtags", []), ensure_ascii=False),
            script_payload.get("estimated_duration_seconds"),
            json.dumps(script_payload, ensure_ascii=False),
        ),
    )
    script_id = int(cursor.lastrowid)

    for part in script_payload["parts"]:
        connection.execute(
            """
            INSERT INTO parts (
                script_id, part_number, text, duration, status
            )
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                script_id,
                int(part["part_number"]),
                part["text"],
                part.get("estimated_duration_seconds"),
            ),
        )

    connection.execute(
        """
        UPDATE stories
        SET status = 'completed',
            processed_at = CURRENT_TIMESTAMP,
            error = NULL,
            visual_profile_json = COALESCE(?, visual_profile_json)
        WHERE id = ?
        """,
        (
            json.dumps(script_payload.get("visual_profile"), ensure_ascii=False)
            if script_payload.get("visual_profile")
            else None,
            story_id,
        ),
    )
    connection.commit()
    return script_id


def mark_story_failed(connection: sqlite3.Connection, story_id: int, error: str) -> None:
    connection.execute(
        "UPDATE stories SET status = 'failed', processed_at = CURRENT_TIMESTAMP, error = ? WHERE id = ?",
        (error[:2000], story_id),
    )
    connection.commit()


def get_parts_needing_audio(connection: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT
            parts.*,
            scripts.story_id,
            scripts.title AS script_title,
            stories.subreddit,
            stories.url AS source_url
        FROM parts
        JOIN scripts ON scripts.id = parts.script_id
        JOIN stories ON stories.id = scripts.story_id
        WHERE parts.status = 'pending'
          AND (parts.audio_path IS NULL OR parts.audio_path = '')
        ORDER BY parts.created_at ASC, parts.id ASC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    return list(connection.execute(query, params).fetchall())


def get_parts_needing_subtitles(connection: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT
            parts.*,
            scripts.story_id,
            scripts.title AS script_title,
            stories.subreddit,
            stories.url AS source_url
        FROM parts
        JOIN scripts ON scripts.id = parts.script_id
        JOIN stories ON stories.id = scripts.story_id
        WHERE parts.audio_path IS NOT NULL
          AND parts.audio_path != ''
          AND parts.status = 'completed'
          AND (parts.subtitle_path IS NULL OR parts.subtitle_path = '')
        ORDER BY parts.updated_at ASC, parts.id ASC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    return list(connection.execute(query, params).fetchall())


def update_part_audio(
    connection: sqlite3.Connection,
    part_id: int,
    audio_path: str,
    duration: float,
) -> None:
    connection.execute(
        """
        UPDATE parts
        SET audio_path = ?, duration = ?, status = 'completed', error = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (audio_path, duration, part_id),
    )
    connection.commit()


def mark_part_failed(connection: sqlite3.Connection, part_id: int, error: str) -> None:
    connection.execute(
        """
        UPDATE parts
        SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (error[:2000], part_id),
    )
    connection.commit()


def update_part_subtitles(
    connection: sqlite3.Connection,
    part_id: int,
    transcript_path: str,
    subtitle_path: str,
) -> None:
    connection.execute(
        """
        UPDATE parts
        SET transcript_path = ?, subtitle_path = ?, status = 'completed', error = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (transcript_path, subtitle_path, part_id),
    )
    connection.commit()


def get_last_background_path(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        """
        SELECT background_path
        FROM videos
        WHERE background_path IS NOT NULL AND background_path != ''
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row["background_path"]) if row else None


def get_background_path_for_story(connection: sqlite3.Connection, story_id: int) -> str | None:
    row = connection.execute(
        """
        SELECT videos.background_path
        FROM videos
        JOIN parts ON parts.id = videos.part_id
        JOIN scripts ON scripts.id = parts.script_id
        WHERE scripts.story_id = ?
          AND videos.status = 'completed'
          AND videos.background_path IS NOT NULL
          AND videos.background_path != ''
        ORDER BY videos.created_at ASC, videos.id ASC
        LIMIT 1
        """,
        (story_id,),
    ).fetchone()
    return str(row["background_path"]) if row else None


def get_parts_ready_for_video(connection: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT
            parts.*,
            scripts.story_id,
            scripts.title AS script_title,
            scripts.description,
            scripts.hashtags_json,
            stories.visual_profile_json,
            (
                SELECT COUNT(*)
                FROM parts AS all_parts
                WHERE all_parts.script_id = parts.script_id
            ) AS total_parts,
            stories.subreddit,
            stories.url AS source_url
        FROM parts
        JOIN scripts ON scripts.id = parts.script_id
        JOIN stories ON stories.id = scripts.story_id
        WHERE parts.audio_path IS NOT NULL
          AND parts.audio_path != ''
          AND parts.subtitle_path IS NOT NULL
          AND parts.subtitle_path != ''
          AND parts.status = 'completed'
          AND NOT EXISTS (
              SELECT 1
              FROM videos
              WHERE videos.part_id = parts.id
                AND videos.status = 'completed'
          )
        ORDER BY parts.updated_at ASC, parts.id ASC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    return list(connection.execute(query, params).fetchall())


def insert_video_record(
    connection: sqlite3.Connection,
    part_id: int,
    background_path: str,
    subtitle_path: str,
    video_path: str,
    metadata_path: str,
    style: str,
    duration: float,
    status: str,
    error: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO videos (
            part_id, background_path, subtitle_path, video_path,
            metadata_path, style, duration, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            part_id,
            background_path,
            subtitle_path,
            video_path,
            metadata_path,
            style,
            duration,
            status,
            error[:2000] if error else None,
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def upsert_background(connection: sqlite3.Connection, background: dict[str, Any]) -> int:
    connection.execute(
        """
        INSERT INTO backgrounds (
            filename, filepath, category, subcategory, source_url, source_platform,
            author, license, license_status, downloaded_at, duration, width, height,
            file_hash, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(filepath) DO UPDATE SET
            filename = excluded.filename,
            category = excluded.category,
            subcategory = excluded.subcategory,
            duration = excluded.duration,
            width = excluded.width,
            height = excluded.height,
            file_hash = excluded.file_hash,
            status = excluded.status
        """,
        (
            background["filename"],
            background["filepath"],
            background["category"],
            background.get("subcategory"),
            background.get("source_url"),
            background.get("source_platform"),
            background.get("author"),
            background.get("license"),
            background.get("license_status", "manual"),
            background.get("downloaded_at"),
            background.get("duration"),
            background.get("width"),
            background.get("height"),
            background.get("file_hash"),
            background.get("status", "available"),
        ),
    )
    connection.commit()
    row = connection.execute("SELECT id FROM backgrounds WHERE filepath = ?", (background["filepath"],)).fetchone()
    return int(row["id"])


def find_backgrounds(
    connection: sqlite3.Connection,
    category: str,
    subcategory: str | None = None,
) -> list[sqlite3.Row]:
    params: list[Any] = [category]
    query = """
        SELECT *
        FROM backgrounds
        WHERE status = 'available'
          AND category = ?
    """
    if subcategory:
        query += " AND (subcategory = ? OR subcategory IS NULL OR subcategory = '')"
        params.append(subcategory)
    query += " ORDER BY times_used ASC, COALESCE(last_used_at, '') ASC, id ASC"
    return list(connection.execute(query, tuple(params)).fetchall())


def mark_background_used(connection: sqlite3.Connection, filepath: str) -> None:
    connection.execute(
        """
        UPDATE backgrounds
        SET times_used = times_used + 1,
            last_used_at = CURRENT_TIMESTAMP
        WHERE filepath = ?
        """,
        (filepath,),
    )
    connection.commit()


def get_publishable_videos(
    connection: sqlite3.Connection,
    platform: str,
    mode: str,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT videos.*
        FROM videos
        WHERE videos.status = 'completed'
          AND videos.video_path IS NOT NULL
          AND videos.video_path != ''
          AND NOT EXISTS (
              SELECT 1
              FROM publications
              WHERE publications.video_id = videos.id
                AND publications.platform = ?
                AND publications.mode = ?
                AND publications.status IN ('uploaded', 'published', 'processing')
          )
        ORDER BY videos.created_at ASC, videos.id ASC
    """
    params: list[Any] = [platform, mode]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return list(connection.execute(query, tuple(params)).fetchall())


def upsert_publication(
    connection: sqlite3.Connection,
    video_id: int,
    platform: str,
    mode: str,
    publish_id: str | None,
    status: str,
    error: str | None = None,
) -> int:
    connection.execute(
        """
        INSERT INTO publications (
            video_id, platform, mode, publish_id, status, error, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(video_id, platform, mode) DO UPDATE SET
            publish_id = excluded.publish_id,
            status = excluded.status,
            error = excluded.error,
            updated_at = CURRENT_TIMESTAMP
        """,
        (video_id, platform, mode, publish_id, status, error[:2000] if error else None),
    )
    connection.commit()
    row = connection.execute(
        "SELECT id FROM publications WHERE video_id = ? AND platform = ? AND mode = ?",
        (video_id, platform, mode),
    ).fetchone()
    return int(row["id"])
