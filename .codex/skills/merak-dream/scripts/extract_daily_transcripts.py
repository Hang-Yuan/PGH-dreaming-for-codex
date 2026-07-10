#!/usr/bin/env python3
"""Extract one logical day's user-facing Codex conversation into a dream bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


DEFAULT_SESSIONS = Path.home() / ".codex" / "sessions"
DEFAULT_ARCHIVED = Path.home() / ".codex" / "archived_sessions"
DEFAULT_TZ = "Asia/Shanghai"
SCAFFOLD_PREFIXES = (
    "<recommended_plugins>",
    "# AGENTS.md instructions",
    "<environment_context>",
    "<subagent_notification>",
    "<codex_internal_context",
    "<turn_aborted>",
)


@dataclass
class Message:
    timestamp: str
    local_time: str
    session_id: str
    turn_id: str
    role: str
    phase: str
    text: str
    source_file: str
    sequence: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Logical date in YYYY-MM-DD form")
    parser.add_argument("--timezone", default=DEFAULT_TZ)
    parser.add_argument("--sessions-root", type=Path, default=DEFAULT_SESSIONS)
    parser.add_argument("--archived-root", type=Path, default=DEFAULT_ARCHIVED)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def iter_jsonl_files(roots: Iterable[Path], lower_mtime: float) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                if path.stat().st_mtime >= lower_mtime:
                    files.append(path)
            except OSError:
                continue
    return sorted(set(files))


def parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_scaffold(text: str) -> bool:
    stripped = text.lstrip("\ufeff\n\r \t")
    return any(stripped.startswith(prefix) for prefix in SCAFFOLD_PREFIXES)


def message_text(payload: dict[str, Any]) -> tuple[str, int]:
    role = payload.get("role")
    wanted = "input_text" if role == "user" else "output_text"
    parts: list[str] = []
    filtered_scaffold_parts = 0
    for part in payload.get("content") or []:
        if not isinstance(part, dict) or part.get("type") != wanted:
            continue
        text = part.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if role == "user" and is_scaffold(text):
            filtered_scaffold_parts += 1
            continue
        parts.append(text.strip())
    return "\n\n".join(parts), filtered_scaffold_parts


def scan_file(
    path: Path,
    window_start: datetime,
    window_end: datetime,
    tz: ZoneInfo,
) -> tuple[dict[str, Any], list[Message]]:
    thread_sources: set[str] = set()
    session_ids: list[str] = []
    messages: list[Message] = []
    errors: list[str] = []
    filtered_scaffold_parts = 0
    user_turns_seen: set[str] = set()
    visible_user_turns: set[str] = set()

    try:
        handle = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        return {"path": str(path), "errors": [str(exc)]}, []

    with handle:
        for sequence, line in enumerate(handle, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {sequence}: {exc.msg}")
                continue

            payload = item.get("payload") or {}
            if item.get("type") == "session_meta":
                source = payload.get("thread_source")
                if isinstance(source, str):
                    thread_sources.add(source)
                sid = payload.get("id") or payload.get("session_id")
                if isinstance(sid, str):
                    session_ids.append(sid)
                continue

            if item.get("type") != "response_item" or payload.get("type") != "message":
                continue
            if payload.get("role") not in {"user", "assistant"}:
                continue

            stamp = parse_timestamp(item.get("timestamp"))
            if stamp is None:
                continue
            local = stamp.astimezone(tz)
            if not (window_start <= local < window_end):
                continue

            meta = payload.get("internal_chat_message_metadata_passthrough") or {}
            turn_id = str(meta.get("turn_id") or payload.get("id") or f"line-{sequence}")
            if payload.get("role") == "user":
                user_turns_seen.add(turn_id)

            text, filtered = message_text(payload)
            filtered_scaffold_parts += filtered
            if not text:
                continue
            if payload.get("role") == "user":
                visible_user_turns.add(turn_id)
            messages.append(
                Message(
                    timestamp=stamp.astimezone(timezone.utc).isoformat(),
                    local_time=local.isoformat(),
                    session_id="",
                    turn_id=turn_id,
                    role=str(payload.get("role")),
                    phase=str(payload.get("phase") or ""),
                    text=text,
                    source_file=str(path),
                    sequence=sequence,
                )
            )

    internal_only_turns = user_turns_seen - visible_user_turns
    messages = [msg for msg in messages if msg.turn_id not in internal_only_turns]

    effective_source = "subagent" if "subagent" in thread_sources else (
        "automation" if "automation" in thread_sources else (
            "user" if "user" in thread_sources else "unknown"
        )
    )
    included = effective_source == "user"
    session_id = next((sid for sid in session_ids if sid), path.stem)
    for msg in messages:
        msg.session_id = session_id

    info = {
        "path": str(path),
        "session_id": session_id,
        "thread_sources": sorted(thread_sources),
        "effective_thread_source": effective_source,
        "included": included,
        "message_count": len(messages) if included else 0,
        "target_window_message_count": len(messages),
        "filtered_scaffold_parts": filtered_scaffold_parts,
        "filtered_internal_only_turn_count": len(internal_only_turns),
        "errors": errors,
    }
    return info, messages if included else []


def dedupe(messages: list[Message]) -> list[Message]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[Message] = []
    for msg in sorted(messages, key=lambda m: (m.timestamp, m.source_file, m.sequence)):
        digest = hashlib.sha256(msg.text.encode("utf-8")).hexdigest()
        key = (msg.session_id, msg.turn_id, msg.role, msg.phase, digest)
        if key in seen:
            continue
        seen.add(key)
        result.append(msg)
    return result


def write_bundle(
    output_dir: Path,
    target: date,
    tz_name: str,
    window_start: datetime,
    window_end: datetime,
    files: list[dict[str, Any]],
    messages: list[Message],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    included_files = [f for f in files if f.get("included") and f.get("message_count", 0) > 0]
    excluded_files = [
        f for f in files
        if not f.get("included") and f.get("target_window_message_count", 0) > 0
    ]
    excluded_by_source: dict[str, int] = {}
    for info in excluded_files:
        source = str(info.get("effective_thread_source") or "unknown")
        excluded_by_source[source] = excluded_by_source.get(source, 0) + 1
    manifest = {
        "logical_date": target.isoformat(),
        "timezone": tz_name,
        "window_start": window_start.isoformat(),
        "window_end_exclusive": window_end.isoformat(),
        "candidate_file_count": len(files),
        "target_window_file_count": sum(f.get("target_window_message_count", 0) > 0 for f in files),
        "included_session_count": len({m.session_id for m in messages}),
        "included_turn_count": len({(m.session_id, m.turn_id) for m in messages}),
        "message_count": len(messages),
        "user_message_count": sum(m.role == "user" for m in messages),
        "assistant_message_count": sum(m.role == "assistant" for m in messages),
        "filtered_scaffold_parts": sum(
            int(f.get("filtered_scaffold_parts", 0)) for f in included_files
        ),
        "filtered_internal_only_turn_count": sum(
            int(f.get("filtered_internal_only_turn_count", 0)) for f in included_files
        ),
        "all_candidate_filtered_scaffold_parts": sum(
            int(f.get("filtered_scaffold_parts", 0)) for f in files
        ),
        "all_candidate_filtered_internal_only_turn_count": sum(
            int(f.get("filtered_internal_only_turn_count", 0)) for f in files
        ),
        "errors": [
            {"path": f["path"], "errors": f["errors"]}
            for f in files
            if f.get("errors")
        ],
        "included_files": included_files,
        "excluded_file_count": len(excluded_files),
        "excluded_by_source": excluded_by_source,
        "excluded_files": [
            {
                "path": f["path"],
                "session_id": f.get("session_id"),
                "effective_thread_source": f.get("effective_thread_source"),
                "target_window_message_count": f.get("target_window_message_count", 0),
            }
            for f in excluded_files
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Merak dream transcript bundle",
        "",
        f"- Logical date: {target.isoformat()}",
        f"- Timezone: {tz_name}",
        f"- Window: {window_start.isoformat()} to {window_end.isoformat()} (exclusive)",
        f"- Sessions: {manifest['included_session_count']}",
        f"- Turns: {manifest['included_turn_count']}",
        f"- Messages: {manifest['message_count']}",
        "",
    ]
    current_session = None
    for msg in messages:
        if msg.session_id != current_session:
            current_session = msg.session_id
            lines.extend([f"## Session {current_session}", ""])
        local = datetime.fromisoformat(msg.local_time)
        label = "User" if msg.role == "user" else "Assistant"
        phase = f" · {msg.phase}" if msg.phase else ""
        lines.extend(
            [
                f"### {local.strftime('%Y-%m-%d %H:%M:%S')} · {label}{phase} · turn {msg.turn_id}",
                "",
                msg.text,
                "",
            ]
        )
    (output_dir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        target = date.fromisoformat(args.date)
        tz = ZoneInfo(args.timezone)
    except (ValueError, KeyError) as exc:
        raise SystemExit(f"invalid date/timezone: {exc}")

    start_local = datetime.combine(target, time(hour=6), tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    candidates = iter_jsonl_files(
        (args.sessions_root, args.archived_root), start_local.astimezone(timezone.utc).timestamp()
    )
    file_infos: list[dict[str, Any]] = []
    all_messages: list[Message] = []
    for path in candidates:
        info, messages = scan_file(path, start_local, end_local, tz)
        file_infos.append(info)
        all_messages.extend(messages)

    messages = dedupe(all_messages)
    output_dir = args.output_dir or Path("/tmp") / "merak-dream" / target.isoformat()
    write_bundle(output_dir, target, args.timezone, start_local, end_local, file_infos, messages)
    summary = {
        "logical_date": target.isoformat(),
        "output_dir": str(output_dir),
        "sessions": len({m.session_id for m in messages}),
        "turns": len({(m.session_id, m.turn_id) for m in messages}),
        "messages": len(messages),
        "errors": sum(bool(f.get("errors")) for f in file_infos),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
