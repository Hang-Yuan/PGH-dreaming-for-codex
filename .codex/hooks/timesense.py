"""timesense.py — 每条消息注入当前真实时间。

不让模型自己猜时间。猜出来的时间会污染两件事：写进文件的日期字段，以及逻辑日期
换算（"昨天"是哪天）。这两个都不会报错，只会静默把工作归到错误的日子。
"""

import datetime as dt
import json
import sys


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


now = dt.datetime.now().astimezone()
stamp = f"{now:%Y-%m-%d %H:%M} {WEEKDAYS[now.weekday()]}"
text = (
    f"当前时间：{stamp}。任何时间认知与日期字段一律以此为准，禁止凭记忆估算。"
    f"逻辑日期换算见 AGENTS.md §时间感知（日界线由部署时的作息访谈决定，不是固定值）。"
)
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
