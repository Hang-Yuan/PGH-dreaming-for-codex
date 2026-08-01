import json
import re
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


def read_payload() -> str:
    raw = sys.stdin.buffer.read()
    text = ""
    for encoding in ("utf-8", "utf-8-sig", "gbk", "cp936"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode(errors="ignore")

    try:
        event = json.loads(text)
    except json.JSONDecodeError:
        return text

    strings = []

    def collect(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(event)
    return text + "\n" + "\n".join(strings)


payload = read_payload()
# 告别触发词默认给两句示例；新增触发词由用户按 config.toml 的 matcher 自定，
# 并同步本正则，确保二者一致。
if re.search(r"晚安|今天就到这儿|收工", payload):
    emit(
        "结束语触发：若本条消息确为道别 / 收尾，先调用 daily-dream 完整流程；若告别词只是行文中顺带提及，忽略本信号。"
    )
