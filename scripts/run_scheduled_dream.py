#!/usr/bin/env python3
"""run_scheduled_dream.py — 被 OS 排程直接调用的包装器

排程不直接调 CLI，而是调这一层。理由只有一个：**「排程自然触发过」这件事必须有
只有排程能写出来的证据。**

没有它的话，验收只能靠地面证据（探针 / MEMORY_LOG / 日志里出现某个日期），而这三
条手工补跑也都会写出来——于是「用户自己补跑了一次」与「排程夜里自然跑成功了」在
收据上完全同形，验收器会把前者当后者翻绿。而这两件事的失败后果不同：排程没装成时
用户每天都得记着手工补，一旦忘了就静默丢一天。

本包装器在 CLI 退出后追加一条结构化 sentinel（append-only JSONL），记下 label /
runtime / scheduled_at / fired_at / exit / status。

`scheduled_at` 与 `fired_at` 是两件事，不能互相代替：前者是 job 定义里那个**名义触发
时刻**（排程本该在几点跑），后者是包装器**实际开跑**的墙钟。唤醒补触发时两者能差几个
小时，而「排程是否按它自己声明的时刻在跑」只有前者答得上。`fired_at` 保留不动，旧收据
与旧验收路径继续读它。

**「本包装器跑过」本身不算自然触发的证据**——手工敲一条命令也能让它跑起来。故只有
环境里带着当次安装写进 job 定义的 proof（且与收据 hash 相符）时才写
`source=os-scheduler`；否则记 `manual-wrapper`：链照跑，但不冒充自然运行。

  python3 run_scheduled_dream.py --runtime claude --assistant-root <ASSISTANT_ROOT>

退出码原样透传 CLI 的退出码，好让 launchd / schtasks / systemd 的失败记录有意义。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 复用安装器里的命令构造、路径常量与 MAC 算法，避免两处各写一份而漂移。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_schedule as sched                                  # noqa: E402

PGH_DIR = Path.home() / ".pgh"

#: sentinel 里 `source` 字段的值。验收器只认 NATURAL_SOURCE。
NATURAL_SOURCE = "os-scheduler"
#: 没有匹配 proof 时降级到这个值——本脚本被手工直接运行时就是这种情况。
MANUAL_SOURCE = "manual-wrapper"

PROOF_ENV = "PGH_SCHED_PROOF"
GEN_ENV = "PGH_JOB_GENERATION"
#: 名义触发时刻（`HH:MM`），由安装器写进那一次的 job 定义。见 `scheduled_at_for()`。
SCHED_TIME_ENV = sched.SCHED_TIME_ENV

#: 允许「实际触发」早于「名义时刻」的余量。墙钟秒级抖动不该让名义日期回退一整天。
SKEW_GRACE = timedelta(minutes=5)


def scheduled_at_for(fired: datetime, source: str) -> str | None:
    """算这趟的 `scheduled_at`——即 job 定义声明的名义触发时刻，落在 `fired` 附近那天。

    **只在判定为自然触发时才产出。** 手工跑包装器时环境里没有 `PGH_SCHED_TIME`（它和
    proof 一样只写进 job 定义），故 `source != os-scheduler` 时一律返回 `None`：这个字段
    的全部含义就是「排程到点触发了」，让手工路径也能填上它等于把它降成又一个 `fired_at`。

    日期取法用一条不变量：**排程只会在名义时刻当刻或之后触发，不会提前。** 三个平台的
    补触发（launchd 唤醒、systemd `Persistent=true`、Windows `StartWhenAvailable`）都是
    「错过了，开机后补」，没有任何机制会提前跑。故名义时刻 = 不晚于 `fired` 的那个最近
    的 `HH:MM`：同日的点若晚于 `fired`，说明这趟补的是前一天那个点。

    留 `SKEW_GRACE` 的余量是因为墙钟可能有秒级抖动（06:29:59 触发、名义 06:30）。没有
    余量的话，一秒的偏差会让日期整整回退一天。
    """
    raw = (os.environ.get(SCHED_TIME_ENV) or "").strip()
    if source != NATURAL_SOURCE or not raw:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    nominal = fired.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if nominal - fired > SKEW_GRACE:
        nominal -= timedelta(days=1)
    return nominal.isoformat(timespec="seconds")


def proof_hash(proof: str, generation: str) -> str:
    """与 install_schedule.py 同一个算法。两处必须同数，否则每趟都判不匹配。"""
    return hashlib.sha256(f"{generation}\0{proof}".encode()).hexdigest()


def classify_source(runtime: str) -> tuple[str, dict, str, str | None]:
    """判定本次运行算不算 OS job 自然触发。

    返回 `(source, 待并入 sentinel 的字段, 说明, 可用于签名的 proof)`。proof 只在判定为
    自然触发时非 None——它不写进 sentinel，只用来算 MAC。

    **本脚本自己被运行这件事不构成证据。** 早先只要跑起来就写 `source=os-scheduler`，
    于是 sentinel 只能证明「包装器跑过」——而手工敲一条命令也能让它跑起来。首跑验收
    要回答的恰恰是「OS job 到点自己触发过吗」，两者必须能分开。

    故要求环境里带着**只存在于本次 job 定义中**的 proof，且它与收据里的 hash 相符。
    对不上就降级为 `manual-wrapper`：链照跑（补跑本身是有用的），但不冒充自然运行。

    这不防本机用户主动去 LaunchAgents 里抄 proof——同一个用户读得到自己的 job 定义，
    本地方案挡不住，声称能挡是自欺。它防的是普通手工补跑与陈旧状态误判。
    """
    proof = os.environ.get(PROOF_ENV, "").strip()
    gen = os.environ.get(GEN_ENV, "").strip()
    # generation 无论判成哪一档都写进 sentinel：验收器要拿它跟当前收据对，而
    # 「带着旧 generation 的运行」正是重装后最需要被认出来的那一类。
    fields = {"job_generation": gen or None, "proof_ok": False}
    if not proof or not gen:
        return MANUAL_SOURCE, fields, "环境里没有排程 proof（手工运行包装器）", None

    rp = PGH_DIR / f"schedule_receipt.{runtime}.json"
    if not rp.exists():
        return MANUAL_SOURCE, fields, f"找不到收据 {rp}，无法校验 proof", None
    try:
        receipt = json.loads(rp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return MANUAL_SOURCE, fields, f"收据无法解析（{e}）", None

    want_gen = receipt.get("job_generation")
    want_hash = receipt.get("scheduler_proof_sha256")
    if not want_gen or not want_hash:
        return (MANUAL_SOURCE, fields,
                "收据里没有 generation / proof hash（旧版安装器装的）", None)
    if gen != want_gen:
        # 重装换了 generation：这趟是旧 job 触发的，它证明不了新 job 的状态。
        return MANUAL_SOURCE, fields, f"generation 不符（job={gen} 收据={want_gen}）", None
    got = proof_hash(proof, gen)
    if not secrets.compare_digest(got, want_hash):
        return MANUAL_SOURCE, fields, "proof 与收据 hash 不符", None
    # 写 hash 而不是 proof 本身：sentinel 是留给人看的诊断文件，把 secret 抄进去
    # 等于每晚往一个谁都读得到的日志里复制一份，下一次重装前它一直在那儿。
    fields = {"job_generation": gen, "proof_ok": True, "proof_sha256": got}
    return NATURAL_SOURCE, fields, "proof 与当前收据相符", proof


def sentinel_path(runtime: str) -> Path:
    """自然运行 sentinel。按 runtime 分开——两端共用会互相覆盖验收状态。"""
    return PGH_DIR / f"natural_runs.{runtime}.jsonl"


def sign(record: dict, proof: str | None) -> dict:
    """给 sentinel 补上 MAC。没有 proof（手工运行）时不签——**不签也不伪造**。

    验收器要求 MAC 必须在场且可复算，故未签名的记录一律不翻绿。这正是要的效果：
    手工跑没有 job secret，签不出来，也就不能冒充自然运行。
    """
    if not proof:
        return record
    record = dict(record)
    record["mac"] = sched.sentinel_mac(proof, str(record.get("job_generation") or ""),
                                       record)
    return record


def append_sentinel(runtime: str, record: dict) -> None:
    """追加一条 sentinel。

    **append-only 且单次 write**：覆盖写会让上一趟的记录消失，于是「昨天跑成功过」
    这个事实会被今天的失败擦掉。单次 write 是为了原子性——排程跑到一半机器断电时，
    宁可整条记录没写上，也不要留半行坏 JSON 让验收器解析失败。
    """
    PGH_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with sentinel_path(runtime).open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def main() -> int:
    ap = argparse.ArgumentParser(description="排程包装器：跑 daily-dream 并留自然运行凭据")
    ap.add_argument("--runtime", choices=["claude", "codex"], required=True)
    ap.add_argument("--assistant-root", required=True)
    ap.add_argument("--label", default=None,
                    help="job label，写进 sentinel 供交叉核对。默认 pgh.daily-dream.<rt>")
    ap.add_argument("--shutdown-after", action="store_true")
    a = ap.parse_args()

    root = Path(a.assistant_root).expanduser().resolve()
    label = a.label or f"{sched.JOB_LABEL}.{a.runtime}"
    log = sched.log_path(a.runtime)
    log.parent.mkdir(parents=True, exist_ok=True)

    fired_at = datetime.now().astimezone()
    source, proof_fields, why, proof = classify_source(a.runtime)
    # 名义触发时刻只在自然触发那一档才有值——它的来源是 job 定义，手工跑拿不到。
    sched_at = scheduled_at_for(fired_at, source)
    if source == NATURAL_SOURCE and not sched_at:
        # 自然触发但读不到名义时刻 = 旧安装器装的 job（那一代不注入该变量）。如实留空，
        # 不用 fired_at 顶替：顶替会让「排程按时刻在跑」这件事变成自证。
        print("PGH: job 里没有名义触发时刻，scheduled_at 留空（重跑安装器可补上）",
              file=sys.stderr)
    if source != NATURAL_SOURCE:
        # 说明写到 stderr 而不是静默降级：手工跑的人需要知道这趟不算自然运行，
        # 否则他会以为验收该翻绿了，然后去查一个根本没坏的验收器。
        print(f"PGH: 本次记为 {source}（{why}）", file=sys.stderr)

    try:
        cmd = sched.runtime_cmd(a.runtime, root, a.shutdown_after)
    except SystemExit as e:
        # CLI 不在本机：这也是一次「排程真的触发了」的事实，必须留证据，
        # 否则表现为「排程从没跑过」，而成因完全不同（装好了但二进制没了）。
        append_sentinel(a.runtime, sign({
            "label": label, "runtime": a.runtime, "source": source,
            "scheduled_at": sched_at,
            "fired_at": fired_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "exit": None, "status": "blocked", "detail": str(e),
            **proof_fields,
        }, proof))
        print(f"PGH: 排程触发但无法构造命令：{e}", file=sys.stderr)
        return 127

    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== {fired_at:%Y-%m-%d %H:%M:%S%z} {label} 触发 =====\n")
    r = subprocess.run(cmd, shell=True)
    finished = datetime.now().astimezone()

    append_sentinel(a.runtime, sign({
        "label": label, "runtime": a.runtime, "source": source,
        # 名义触发时刻（job 定义声明的点）与实际开跑墙钟并列，两者都留。
        "scheduled_at": sched_at,
        "fired_at": fired_at.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "exit": r.returncode,
        # 失败也要留可诊断状态——但状态是 `failed`，验收器不得据此翻绿。
        # 只记成功会让「每夜都触发、每夜都失败」看起来和「从没触发」一样。
        "status": "ok" if r.returncode == 0 else "failed",
        "assistant_root": str(root),
        **proof_fields,
    }, proof))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
