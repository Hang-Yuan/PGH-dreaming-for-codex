import json
import sys


def emit(text: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": text,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


emit(
    "上下文路由提醒：若本轮出现项目阶段性收尾、子问题闭合、任务完成或用户说 close-node/闭合，调用 close-node。"
    " 若本轮进入项目工作且尚未加载项目链，按 <CODEX_HOME>/AGENTS.md §B 项目工作加载读取 _overview 与下沉链后再推进。"
)
