from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import SubtitlesConfig, VideoConfig


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


class AssSubtitleWriter:
    def __init__(self, subtitles_config: SubtitlesConfig, video_config: VideoConfig) -> None:
        self.subtitles_config = subtitles_config
        self.video_config = video_config

    def cache_path_for_part(self, part_id: int) -> Path:
        self.subtitles_config.output_dir.mkdir(parents=True, exist_ok=True)
        return self.subtitles_config.output_dir / f"part_{part_id:06d}.ass"

    def write(self, transcript: dict, output_path: str | Path) -> None:
        cues = self.build_cues(transcript)
        if not cues:
            raise ValueError("Cannot write ASS subtitles without cues")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self._render_ass(cues), encoding="utf-8")

    def build_cues(self, transcript: dict) -> list[SubtitleCue]:
        words = transcript.get("words") or []
        if words:
            return self._build_word_cues(words)
        return self._build_segment_cues(transcript.get("segments") or [])

    def _build_word_cues(self, words: list[dict]) -> list[SubtitleCue]:
        cues: list[SubtitleCue] = []
        current: list[dict] = []
        max_chars = self.subtitles_config.max_chars_per_line * self.subtitles_config.max_lines

        for word in words:
            candidate = current + [word]
            candidate_text = self._join_words(candidate)
            should_flush = (
                len(candidate_text) > max_chars
                or len(current) >= 7
                or (current and self._ends_naturally(current[-1]["word"]))
            )
            if should_flush:
                cues.append(self._cue_from_words(current))
                current = [word]
            else:
                current = candidate

        if current:
            cues.append(self._cue_from_words(current))
        return [cue for cue in cues if cue.end > cue.start and cue.text]

    def _build_segment_cues(self, segments: list[dict]) -> list[SubtitleCue]:
        cues: list[SubtitleCue] = []
        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", start + 1.0))
            chunks = self._split_text_for_display(text)
            if not chunks:
                continue
            duration = max(end - start, 0.5)
            chunk_duration = duration / len(chunks)
            for index, chunk in enumerate(chunks):
                cue_start = start + (index * chunk_duration)
                cue_end = cue_start + chunk_duration
                cues.append(SubtitleCue(cue_start, cue_end, chunk))
        return cues

    def _cue_from_words(self, words: list[dict]) -> SubtitleCue:
        text = self._join_words(words)
        return SubtitleCue(
            start=float(words[0]["start"]),
            end=float(words[-1]["end"]),
            text=self._wrap_text(text),
        )

    def _join_words(self, words: list[dict]) -> str:
        text = " ".join(str(word["word"]).strip() for word in words if str(word.get("word", "")).strip())
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _split_text_for_display(self, text: str) -> list[str]:
        words = text.split()
        chunks: list[str] = []
        current: list[str] = []
        max_chars = self.subtitles_config.max_chars_per_line * self.subtitles_config.max_lines
        for word in words:
            candidate = " ".join(current + [word])
            if current and len(candidate) > max_chars:
                chunks.append(self._wrap_text(" ".join(current)))
                current = [word]
            else:
                current.append(word)
        if current:
            chunks.append(self._wrap_text(" ".join(current)))
        return chunks

    def _wrap_text(self, text: str) -> str:
        max_chars = self.subtitles_config.max_chars_per_line
        words = text.split()
        lines: list[str] = []
        current = ""

        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > max_chars and len(lines) + 1 < self.subtitles_config.max_lines:
                lines.append(current)
                current = word
            else:
                current = candidate

        if current:
            lines.append(current)
        return "\\N".join(lines[: self.subtitles_config.max_lines])

    def _ends_naturally(self, word: str) -> bool:
        return word.rstrip().endswith((".", ",", "?", "!", ";", ":"))

    def _render_ass(self, cues: list[SubtitleCue]) -> str:
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {self.video_config.width}
PlayResY: {self.video_config.height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Arial,{self.subtitles_config.font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,80,80,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events = [
            f"Dialogue: 0,{self._format_time(cue.start)},{self._format_time(cue.end)},TikTok,,0,0,0,,{self._escape_text(cue.text)}"
            for cue in cues
        ]
        return header + "\n".join(events) + "\n"

    def _format_time(self, seconds: float) -> str:
        seconds = max(seconds, 0.0)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        whole_seconds = int(seconds % 60)
        centiseconds = int(round((seconds - int(seconds)) * 100))
        if centiseconds == 100:
            whole_seconds += 1
            centiseconds = 0
        return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"

    def _escape_text(self, text: str) -> str:
        return text.replace("{", "\\{").replace("}", "\\}")
