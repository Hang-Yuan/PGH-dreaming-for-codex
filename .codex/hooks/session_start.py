import json
import sys
from pathlib import Path


FILES = [
    ("persona SOUL", Path("<ASSISTANT_ROOT>/SOUL/persona/persona_SOUL.md")),
    ("USER", Path("<ASSISTANT_ROOT>/USER/USER.md")),
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_context() -> str:
    sections = [
        "SessionStart(compact) 补注入：以下内容只来自本地身份层。"
        "episodic/semantic 池均不启动注入；完整启动流程以 <CODEX_HOME>/AGENTS.md §B 为准。"
    ]

    for label, path in FILES:
        try:
            text = read_text(path)
            sections.append(f"\n## {label}\n\n{text}")
        except Exception as exc:
            sections.append(f"\n## {label}\n\n读取失败：{path} ({exc})")

    return "\n".join(sections)


def emit(text: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": text,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


emit(build_context())
