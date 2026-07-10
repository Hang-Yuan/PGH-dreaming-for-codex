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
    "思考协议提醒：本轮回答前内化执行 <CODEX_HOME>/AGENTS.md §R 的四步流程："
    "①分析目标与边界；②判断是否需要检索，需要则发散检索；③先找反例/断点再收敛推导；④拍板后执行。"
    " 硬禁止第一句直接认可、未推导就执行、为既定立场补支撑。"
)
