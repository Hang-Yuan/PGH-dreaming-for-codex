#!/usr/bin/env python3
"""verify_first_run.py — 首次自然运行的验收消费者

`install_schedule.py` 写的收据里留了两个待验位（`acceptance.first_run_verified` /
`first_weekly_run_verified`）。没有消费者的话它们永远是 `false`——那等于把「装好了」
和「已经在跑了」这两件事混在一起，而它们的失败形态完全不同：装好但不跑（时刻写坏 /
job 被 disable / 机器夜里睡了）在收据上看不出任何异常。

本脚本是那个消费者：核地面证据，只有真跑成功过才回写 `true`。

  # 核日跑（预期首跑时刻已过之后跑）
  python3 verify_first_run.py --assistant-root <ASSISTANT_ROOT>

  # 只看不写
  python3 verify_first_run.py --assistant-root <ASSISTANT_ROOT> --dry-run

由 week-sync 在每日首个真人会话调用，也可手动跑。退出码 0 = 该验的都验过了；
1 = 还有没验过的（含「预期时刻还没到」这种正常等待）；2 = 收据缺失或参数错。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 复用安装器的平台回查与路径常量，而不是在这里重写一份。两份实现会漂移，而漂移的方向
# 通常是验收器这份更宽松——它平时都是绿的，没人会注意到它已经不再检查同一件事。
import install_schedule as sched                                    # noqa: E402

PGH_DIR = Path.home() / ".pgh"

#: 收据与日志按 runtime 分开（与 install_schedule.py 一致）。共用一份会让同机装了
#: 两端时，后装的那端覆盖前一端的验收状态。
def receipt_path(runtime: str) -> Path:
    return PGH_DIR / f"schedule_receipt.{runtime}.json"


def log_path(runtime: str) -> Path:
    return PGH_DIR / f"daily-dream.{runtime}.log"


#: 模块级默认，测试里可替换。运行时按 runtime 覆盖成 `log_path(runtime)`。
DREAM_LOG = PGH_DIR / "daily-dream.log"

#: 与 install_schedule.py 保持一致：canon 文件名的历史与现行两种写法。
MEMORY_CANON_NAMES = ("00.memory_agent.md", "00.记忆区_agent.md")

#: 自然运行 sentinel（由 run_scheduled_dream.py 追加，手工跑写不出来）。
NATURAL_SOURCE = "os-scheduler"


def sentinel_path(runtime: str) -> Path:
    return PGH_DIR / f"natural_runs.{runtime}.jsonl"


def read_natural_runs(runtime: str) -> list[dict]:
    """读排程自然运行记录。坏行跳过，不让一条半截 JSON 废掉整份证据。"""
    p = sentinel_path(runtime)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def current_job_state(runtime: str, generation: str | None,
                      receipt: dict | None = None) -> tuple[bool, list[str]]:
    """现在这一刻，job 是否仍启用、且装的仍是本代包装器命令。

    sentinel 只能证明**过去某一刻**排程触发过。装完之后 job 被 disable、被别的工具覆
    盖、或被改成指向临时 clone 里的脚本，这些都不会让旧 sentinel 消失——于是拿旧
    sentinel 就能把一个当下已经不跑的系统判成验收通过，而它明天起就静默丢天。

    故验收当刻必须重新看一眼落地产物：enabled + 命令里确实是持久根包装器 + generation
    与当前收据同代。三条缺一不可。
    """
    notes: list[str] = []
    # 把收据里的固化时刻传进去：`verify()` 会回读 job 自己声明的 Hour/Minute 并与之
    # 交叉核对。不传的话它只能确认「有个时刻」，确认不了那个时刻**是不是收据说的那个**
    # ——于是 job 被改到别的钟点（或时区解释变了）照样算通过，而它每天在错的时刻跑。
    hh = mm = None
    if receipt is not None:
        try:
            hh, mm = dream_time_from_receipt(receipt)
        except SystemExit:
            notes.append("收据里的固化时刻不可用，无法核对 job 时刻")
    ok, msg, ev = sched.verify(runtime, hh, mm, iana_tz_from_receipt(receipt))
    notes.append(f"job 当前状态：{msg}")
    got = ev.get("installed_hour_minute")
    if hh is not None and got and got != f"{hh:02d}:{mm:02d}":
        notes.append(f"job 装的时刻 {got} 与收据 {hh:02d}:{mm:02d} 不符——"
                     "改过作息但没重装，或 job 被别的工具改了")
        return False, notes
    if hh is not None and not ok:
        notes.append("job 回查未通过（时刻 / 启用态 / 下次触发有一项不成立）")
        return False, notes
    if not ev.get("enabled", False):
        notes.append("job 当前**未启用**——旧 sentinel 不能证明它今晚还会跑")
        return False, notes

    cmd = sched.installed_command(runtime)
    if cmd is None:
        notes.append("读不到已安装 job 的命令原文，无法确认它调的是不是本代包装器")
        return False, notes
    if sched.WRAPPER_NAME not in cmd:
        notes.append(f"job 命令里没有 {sched.WRAPPER_NAME}——"
                     "它绕过了包装器，之后的运行写不出自然运行凭据")
        return False, notes
    persistent = str(sched.scripts_dir_for(runtime) / sched.WRAPPER_NAME)
    if persistent not in cmd:
        notes.append(f"job 命令没指向持久根 {persistent}——"
                     "指向临时 clone 的话，clone 一删就静默不跑")
        return False, notes
    # **不能只剥单引号。** cmd.exe 的形状是 `set "VAR=value"`，双引号；于是
    # `PGH_JOB_GENERATION="g1"` 在剥掉单引号后仍带着双引号，与裸 generation 比必然不等
    # ——Windows 上每次验收都判成「装的是别一代」，而 job 完全正常。改为按两种形状解析。
    _, live_gen = sched.installed_proof(runtime)
    if generation and live_gen != generation:
        notes.append(f"job 命令里的 generation={live_gen!r} 不是收据里的 {generation!r}"
                     "——装的是别一代的 job，本代收据证明不了它")
        return False, notes
    notes.append("job 仍启用、命令指向持久根包装器、generation 同代 ✓")
    return True, notes


def natural_run_for(runtime: str, target: date, boundary_h: int,
                    runs: list[dict] | None = None,
                    receipt: dict | None = None) -> tuple[dict | None, list[str]]:
    """找出「处理了 `target` 这个逻辑日」的那一趟**成功的自然运行**。

    这是把「排程真的自己跑成功过」与「用户手工补跑过」区分开的唯一依据。地面证据
    （探针 / MEMORY_LOG / 日志出现某日期）两者都会写出来，故单靠它们无法判别；而两
    者的后果不同——排程没装成时用户必须每天记着手工补，忘一次就静默丢一天。

    判据三条，缺一不可：
    - `source == os-scheduler`：手工调 daily-dream 不经过包装器，写不出这个字段
    - `status == ok` 且 `exit == 0`：失败的运行留可诊断记录，但不得据此翻绿
    - `fired_at` 换算出的处理目标 == `target`：日期用触发时刻机械推，不用验收时的钟

    再加 `scheduled_at`（名义触发时刻）与当前 job 的交叉核对：见
    `scheduled_at_ok()`。它与 `fired_at` 不可互换——后者是实际开跑的墙钟，唤醒补触发时
    能差几个小时，故「排程按它自己声明的时刻在跑」只有前者答得上。

    再加两条与当前收据的交叉核对（A11）：`job_generation` 必须是收据里那一代，
    `proof_sha256` 必须等于收据里的 hash。少了这两条，一条从别处抄来的、或者上一代
    job 留下的 sentinel 都能翻绿——而两者都不能说明**当前**这个 job 会跑。
    """
    notes: list[str] = []
    runs = read_natural_runs(runtime) if runs is None else runs
    if not runs:
        notes.append(f"没有自然运行记录（{sentinel_path(runtime)}）"
                     "——排程或从未触发，或装的是不经包装器的旧命令")
        return None, notes

    same_day = []
    for rec in runs:
        raw = rec.get("fired_at")
        if not isinstance(raw, str):
            continue
        try:
            fired = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if scheduled_target(fired, boundary_h) != target:
            continue
        same_day.append(rec)
        if rec.get("source") != NATURAL_SOURCE:
            notes.append(f"{raw} 那条 source={rec.get('source')!r}，不是排程自然触发")
            continue
        if rec.get("runtime") != runtime:
            notes.append(f"{raw} 那条 runtime={rec.get('runtime')!r}，不是本端")
            continue
        if rec.get("status") != "ok" or rec.get("exit") != 0:
            notes.append(f"{raw} 那趟自然触发了但失败："
                         f"status={rec.get('status')!r} exit={rec.get('exit')!r}")
            continue
        if receipt is not None:
            want_gen = receipt.get("job_generation")
            want_hash = receipt.get("scheduler_proof_sha256")
            if not want_gen or not want_hash:
                notes.append("收据里没有 generation / proof hash——"
                             "排程是旧版安装器装的，重装一次再验收")
                continue
            if rec.get("job_generation") != want_gen:
                notes.append(f"{raw} 那条 generation={rec.get('job_generation')!r}，"
                             f"收据是 {want_gen!r}——是上一代 job 留下的记录")
                continue
            if rec.get("proof_sha256") != want_hash:
                notes.append(f"{raw} 那条 proof 与当前收据不符——"
                             "可能是伪造的 source，或从另一端 / 另一代抄来的")
                continue
            # **公开字段对得上不够。** `job_generation` 与 `scheduler_proof_sha256` 都写在
            # 收据里，收据是本机可读的普通 json——把它们抄进一行 JSONL 就能造出一条
            # 「公开字段全对」的假自然运行。故要求 MAC：它用 job 定义里的 proof 签的，
            # 抄收据算不出来。
            live_proof, live_gen = sched.installed_proof(runtime)
            if not live_proof:
                notes.append("读不到当前 job 里的 proof，无法复算 sentinel MAC——"
                             "job 可能已被替换成不带 proof 的命令")
                continue
            if live_gen != want_gen:
                notes.append(f"当前 job 的 generation={live_gen!r} 与收据 {want_gen!r} 不符")
                continue
            if not sched.proof_matches(live_proof, want_gen, want_hash):
                notes.append("当前 job 里的 proof 与收据 hash 不符——收据与 job 不是一对")
                continue
            mac = rec.get("mac")
            if not mac:
                notes.append(f"{raw} 那条没有 MAC——手工写的 JSONL 签不出来，不予采信")
                continue
            if not sched.mac_matches(live_proof, want_gen, rec, mac):
                notes.append(f"{raw} 那条 MAC 复算不上——"
                             "字段被改过，或公开字段是从收据抄来的")
                continue
            sa_ok, sa_note = scheduled_at_ok(rec, runtime)
            if sa_note:
                notes.append(f"{raw} {sa_note}")
            if not sa_ok:
                continue
        notes.append(f"自然运行命中：{raw} 触发（名义时刻 "
                     f"{rec.get('scheduled_at') or '未记录'}），exit=0，"
                     "proof 与本代收据相符、MAC 复算通过 ✓")
        return rec, notes

    if not same_day:
        notes.append(f"有 {len(runs)} 条自然运行记录，但没有一趟处理 {target}")
    return None, notes


def scheduled_at_ok(rec: dict, runtime: str) -> tuple[bool, str | None]:
    """核 sentinel 里的 `scheduled_at`（名义触发时刻）。

    返回 `(是否放行, 说明或 None)`。四条：

    - **键根本不在场** —— 唯一的向后兼容形状：旧版包装器写的 sentinel 没有这个键。
      放行并在说明里点出来，因为把已经攒下的旧凭据判红等于让升级本身把验过的首跑打回
      未验，而那不是安全收益。
    - **键在场但值为 null / 空** —— **判红**，验收保持待验。这与上一条不是同一件事：
      本代包装器无条件写这个键，故「键在场而值空」意味着这趟自然触发时 job 定义里没有
      名义时刻（脚本升过级但 job 没重装）。放行它等于让一条不含名义时刻的新凭据把
      `first_run_verified` 翻成 true——而这个字段存在的全部理由就是证明「排程按它自己
      声明的时刻在跑」。复位动作是重跑安装器。
    - **可解析** —— 写了但不是 ISO 时刻 = 记录被改过，判红。
    - **与当前 job 声明的时刻同点** —— job 定义里的 `HH:MM` 是唯一权威。核不上说明
      sentinel 声称的「到点」与 job 现在的「点」不是一件事（改过作息没重装，或记录
      来自别处）。读不到 job 里的名义时刻时不据此判红——那与旧 job 同形；但它**不能**
      把上面「键在场而值空」那条救回来，两条各自独立成立。
    """
    if "scheduled_at" not in rec:
        return True, ("那条没有 scheduled_at 键（旧版包装器写的凭据）"
                      "——重跑安装器后新的运行会带上")
    raw = rec.get("scheduled_at")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return False, ("那条的 scheduled_at 是空值——这趟自然触发时 job 定义里没有名义"
                       "时刻（脚本升过级但 job 没重装）。重跑安装器后再验收")
    if not isinstance(raw, str):
        return False, f"scheduled_at 不是时刻字符串：{raw!r}"
    try:
        nominal = datetime.fromisoformat(raw)
    except ValueError:
        return False, f"scheduled_at 无法解析：{raw!r}——记录被改过"
    want = sched.installed_sched_time(runtime)
    if not want:
        return True, None
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", want)
    if not m:
        return True, None
    if (nominal.hour, nominal.minute) != (int(m.group(1)), int(m.group(2))):
        return False, (f"scheduled_at 的时刻 {nominal:%H:%M} 与当前 job 声明的 "
                       f"{want} 不符——改过作息但没重装，或记录来自别的 job")
    return True, None


def load_receipt(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"收据不存在：{path}。先跑 install_schedule.py 装排程。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"收据无法解析：{path} · {e}")


def dream_time_from_receipt(receipt: dict) -> tuple[int, int]:
    """取收据里记的固化触发时刻。缺失或不可解析时退回「日界线 + 30 分钟」。

    优先读收据而不是自己算：收据里的值来自实际安装那一趟，若日界线与固化时刻曾被
    单独改过，算出来的和装上去的会不一致。
    """
    raw = receipt.get("dream_time")
    if isinstance(raw, str):
        m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            if 0 <= h < 24 and 0 <= mi < 60:
                return h, mi
    bh = boundary_hour(receipt)
    total = bh * 60 + 30
    return (total // 60) % 24, total % 60


def iana_tz_from_receipt(receipt: dict | None) -> str | None:
    """取收据里的 IANA 时区名，顶层优先、嵌套兜底。

    顶层 `timezone_iana` 是单一权威落点。兜底读 `acceptance.timezone_iana` 是为已经装
    好的机器：那些收据是旧结构，只有嵌套那一份，不兜底就等于在升级瞬间把它们的时区
    信息全部作废——而作废的表现不是报错，是安静地退回默认时区。

    `UNRESOLVED` 与空串一律折成 `None`：它们是「没解析出来」的标记，不是时区名，往
    `ZoneInfo()` 里传会抛异常。
    """
    if not receipt:
        return None
    nested = receipt.get("acceptance")

    def usable(raw: object) -> str | None:
        if not isinstance(raw, str):
            return None
        raw = raw.strip()
        return raw if raw and raw != "UNRESOLVED" else None

    # **两个来源各自判可用，而不是「顶层缺了才看嵌套」。** 顶层写着 `UNRESOLVED` 也是
    # 不可用，此时必须继续退到嵌套；只按「键存不存在」分支的话，一个探测失败的顶层值
    # 会把一份其实有效的嵌套值挡住。
    return (usable(receipt.get("timezone_iana"))
            or usable(nested.get("timezone_iana") if isinstance(nested, dict) else None))


def boundary_hour(receipt: dict) -> int:
    h = receipt.get("boundary_hour")
    if not isinstance(h, int) or not (0 <= h < 24):
        raise SystemExit(f"收据里的 boundary_hour 不可用：{h!r}")
    return h


def logical_date(now: datetime, boundary_h: int) -> date:
    """按**收据里的动态日界线**换算逻辑日期，不用硬编码 06:00。

    日界线是部署者作息决定的（02:00-06:00 任一整点），写死 06:00 会让早睡早起的
    部署者每天被判错一天——而判错的方向是「核了昨天的证据去验前天的跑」，结论会
    是「没跑」，于是明明跑成功了也验不过。
    """
    d = now.date()
    return d - timedelta(days=1) if now.hour < boundary_h else d


def scheduled_target(run_at: datetime, boundary_h: int) -> date:
    """某趟排程在 `run_at` 触发时，它处理的是哪个逻辑日。

    这是排程自己的规则：它在**日界线 + 30 分钟**触发，处理刚闭窗的那个逻辑日 =
    「触发时刻的逻辑日 − 1 天」。

    **不能用验收当下的时钟代替。** 那是一日偏差的来源：首个真人会话通常在日界线之后
    打开（比如 09:00，日界线 06:00），此时 `logical_date(now)` = 今天，而凌晨 06:30
    那趟处理的是昨天。拿今天的日期去查 `last_dream` / MEMORY_LOG，永远查不到——
    于是明明跑成功了也稳定报红。
    """
    return logical_date(run_at, boundary_h) - timedelta(days=1)


def latest_scheduled_target(now: datetime, boundary_h: int, hh: int, mm: int) -> date:
    """算出「到 `now` 为止，最近一趟已经跑过的排程」处理的逻辑日。

    先找 `now` 之前最后一个 `hh:mm` 触发点，再套 `scheduled_target`。今天的触发点
    还没到就退回昨天那趟——否则会去核一趟还没发生的运行。
    """
    fire = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if fire > now:
        fire -= timedelta(days=1)
    return scheduled_target(fire, boundary_h)


def find_memory_canon(assistant_root: Path) -> Path | None:
    mem = assistant_root / "MEMORY"
    for n in MEMORY_CANON_NAMES:
        if (mem / n).exists():
            return mem / n
    return None


# ── 地面证据探测 ──────────────────────────────────────────────────────────────
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: 包装器写进日志的触发段头，形如 `===== 2026-08-01 06:30:00+0800 pgh.daily-dream.claude 触发 =====`
FIRE_MARKER_RE = re.compile(r"=====\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})")


def _log_has_fire_marker(text: str, target: date, boundary_h: int) -> bool:
    """日志里有没有一段「处理了 target 这个逻辑日」的触发段。

    段头带的是**触发时刻**（物理时钟）加时分，不是目标逻辑日。故不能拿日期直接比，
    要把段头的时刻套 `scheduled_target` 换算出它处理的逻辑日，再与 target 比——这与
    sentinel 判日期用的是同一条规则，两处口径因此不会分叉。

    早先按「触发日期 == target 或 target + 1 天」放行，那个窗口漏掉了**补触发**：
    错过的触发在开机后补跑（systemd `Persistent=true` / 休眠唤醒），补跑时刻可能落在
    日界线**之前**，此时它的逻辑日 = 物理日 − 1，处理的目标日 = 物理日 − 2 —— 于是
    段头日期是 target + 2，落在窗口外被判成「排程可能根本没触发」。而补触发恰恰是留
    机方案里最需要被认成成功的那一类。
    """
    for m in FIRE_MARKER_RE.finditer(text):
        try:
            fired = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}",
                                      "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if scheduled_target(fired, boundary_h) == target:
            return True
    return False


def check_daily_evidence(assistant_root: Path, target: date,
                         boundary_h: int = 6) -> tuple[bool, list[str]]:
    """核 daily 那趟真跑成功过。三条证据，全中才算过。

    只看日志会假绿——日志里有一行「启动了」不代表链跑完了。故必须核**链自己写的
    落点**：探针 + MEMORY_LOG 条目。探针是 daily-dream 第 9 步最后才覆盖的，中途
    失败就到不了那步，所以它同时也是「跑完了」的证据。
    """
    ds = target.isoformat()
    notes: list[str] = []
    hits = 0

    # 探针必须**精确等于**目标日，不是「文中出现过」。
    # 宽松包含会被两种东西假绿：探针文件里留着的历史行，以及任何顺手提到该日期的
    # 说明文字。而探针的语义恰恰是「已完成到哪一天」——它只能有一个当前值。
    probe = assistant_root / "MEMORY" / "last_dream.md"
    if probe.exists():
        body = probe.read_text(encoding="utf-8", errors="replace")
        found = DATE_RE.findall(body)
        if ds in found[-1:] or (found and max(found) == ds):
            hits += 1
            notes.append(f"last_dream.md 当前值 = {ds} ✓")
        elif found:
            notes.append(f"last_dream.md 当前值是 {max(found)}，不是 {ds}")
        else:
            notes.append(f"last_dream.md 里没有可解析的日期（{body.strip()[:40]!r}）")
    else:
        notes.append("last_dream.md 不存在——链没跑到第 9 步，或探针路径不对")

    # MEMORY_LOG 要求**标题行**命中，不是全文任意位置出现该日期。
    # 全文包含会把「某条旧条目在正文里引用了这一天」当成「这一天有代谢落账」。
    mlog = assistant_root / "MEMORY" / "MEMORY_LOG.md"
    if mlog.exists():
        heads = [l for l in mlog.read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.lstrip().startswith("#") and ds in l]
        if heads:
            hits += 1
            notes.append(f"MEMORY_LOG 有 {ds} 条目标题 ✓")
        else:
            notes.append(f"MEMORY_LOG 无 {ds} 的条目标题——phase B 未落账")
    else:
        notes.append("MEMORY_LOG.md 不存在")

    # 日志要求**本次触发的段落头**，不是「尾部出现过该日期」。
    # `MM/DD` 那条尤其松：普通输出里的任意日期、甚至版本号都可能撞上。
    if DREAM_LOG.exists():
        tail = DREAM_LOG.read_text(encoding="utf-8", errors="replace")[-200000:]
        if _log_has_fire_marker(tail, target, boundary_h):
            hits += 1
            notes.append("排程日志有该趟触发段 ✓")
        else:
            notes.append(f"排程日志无 {ds} 的触发段——排程可能根本没触发")
    else:
        notes.append(f"排程日志不存在（{DREAM_LOG}）——排程从未跑过")

    return hits == 3, notes


WEEK_FILE_RE = re.compile(r"^\d{4}-W\d{2}\.md$")


def check_weekly_evidence(assistant_root: Path, target: date) -> tuple[bool, list[str]]:
    """核周段真跑成功过。

    周段的可执行证据最早出现在第一个「目标逻辑日 = 周日」的那趟，即周一凌晨。它的
    产物与 daily 不同：周归档文件 + 周录本周节。故不能拿 daily 的证据代替——那会
    把「日跑通了、周段从没跑过」报成全绿，而周段恰恰是账实核对与衰减的唯一执行者。
    """
    notes: list[str] = []
    if target.weekday() != 6:                     # 6 = 周日
        notes.append(f"目标日 {target} 不是周日，周段本就不该跑（不构成失败）")
        return False, notes

    iso_y, iso_w, _ = target.isocalendar()
    want = f"{iso_y}-W{iso_w:02d}"
    hits = 0

    arch_dirs = [assistant_root / "00 Focus Zone" / "_归档",
                 assistant_root / "00 专注区" / "_归档"]
    arch = next((d for d in arch_dirs if d.exists()), None)
    if arch is None:
        notes.append("找不到周归档目录（`00 Focus Zone/_归档` 或 `00 专注区/_归档`）")
    else:
        names = [p.name for p in arch.iterdir() if WEEK_FILE_RE.match(p.name)]
        if f"{want}.md" in names:
            hits += 1
            notes.append(f"周归档 {want}.md 已在位 ✓")
        else:
            notes.append(f"周归档缺 {want}.md（现有：{sorted(names)[-3:] or '空'}）")

    ltm = next((p for p in (assistant_root / "长期记忆.md",
                            assistant_root / "Long_Term_Memory" / "weekly.md")
                if p.exists()), None)
    if ltm is None:
        notes.append("找不到周录文件（`长期记忆.md` 或 `Long_Term_Memory/weekly.md`）")
    else:
        if want in ltm.read_text(encoding="utf-8", errors="replace"):
            hits += 1
            notes.append(f"周录有 {want} 节 ✓")
        else:
            notes.append(f"周录缺 {want} 节")

    return hits == 2, notes


# ── 主入口 ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="首跑验收消费者")
    ap.add_argument("--assistant-root", required=True,
                    help="用户内容目录（装着 MEMORY/ USER/）")
    ap.add_argument("--runtime", choices=["claude", "codex"], default="claude",
                    help="要核哪一端的排程。收据与日志按 runtime 分开存。")
    ap.add_argument("--receipt", default=None,
                    help="收据路径。默认按 --runtime 取 ~/.pgh/schedule_receipt.<rt>.json")
    ap.add_argument("--dry-run", action="store_true", help="只核不回写")
    ap.add_argument("--target-date", default=None,
                    help="显式指定要核的逻辑日（YYYY-MM-DD），跳过由物理时钟换算。"
                         "补跑某日后复核、以及回归测试用——没有它则「绿」这条路径"
                         "永远走不到，等于这个脚本只被验过会报红。")
    a = ap.parse_args()

    root = Path(a.assistant_root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"--assistant-root 不存在：{root}")
    rpath = (Path(a.receipt).expanduser() if a.receipt
             else receipt_path(a.runtime))
    # 日志也按 runtime 取——混在一个文件里分不清哪趟是哪端跑的。
    global DREAM_LOG
    DREAM_LOG = log_path(a.runtime)
    receipt = load_receipt(rpath)
    acc = receipt.setdefault("acceptance", {})
    bh = boundary_hour(receipt)
    now = datetime.now().astimezone()
    if a.target_date:
        try:
            target = date.fromisoformat(a.target_date)
        except ValueError:
            raise SystemExit(f"--target-date 需要 YYYY-MM-DD，收到 {a.target_date!r}")
        basis = "--target-date 显式指定"
    else:
        rh, rm = dream_time_from_receipt(receipt)
        target = latest_scheduled_target(now, bh, rh, rm)
        basis = (f"最近一趟排程（{rh:02d}:{rm:02d} 触发）处理的逻辑日"
                 f" = 触发时逻辑日 − 1")

    print(f"日界线 {bh:02d}:00 · 现在 {now:%Y-%m-%d %H:%M} · 目标逻辑日 {target}")
    print(f"目标日依据：{basis}")
    print(f"收据 state={receipt.get('state')} runtime={receipt.get('runtime')}")

    changed = False
    pending: list[str] = []

    # ── daily ────────────────────────────────────────────────────────────────
    if acc.get("first_run_verified"):
        print("daily 首跑：早前已验过 ✓")
    else:
        exp = acc.get("expected_first_run")
        due = True
        if exp:
            try:
                due = datetime.fromisoformat(exp) <= now
            except ValueError:
                pass
        if not due:
            print(f"daily 首跑：预期时刻 {exp} 还没到，正常等待（不算失败）")
            pending.append("daily 首跑时刻未到")
        else:
            ok, notes = check_daily_evidence(root, target, bh)
            # 地面证据齐了还不够：必须同时有排程自然触发的结构化凭据。
            # 手工补跑会把三条地面证据全写出来，于是「用户自己补的」与「排程夜里自己
            # 跑成功的」同形。而首跑验收要回答的恰恰是后者。
            nat, nat_notes = natural_run_for(a.runtime, target, bh,
                                             receipt=receipt)
            notes.extend(nat_notes)
            # 还要看**当刻**的 job 状态：sentinel 是过去写的，job 之后可能已被停用或
            # 换掉，那时旧 sentinel 会把一个今晚不会跑的系统判成通过。
            job_ok, job_notes = current_job_state(
                a.runtime, receipt.get("job_generation"), receipt)
            notes.extend(job_notes)
            ok = ok and nat is not None and job_ok
            print(f"daily 首跑：{'PASS' if ok else '未通过'}")
            for n in notes:
                print(f"  - {n}")
            if ok:
                acc["first_run_natural_scheduled_at"] = nat.get("scheduled_at")
                acc["first_run_natural_fired_at"] = nat.get("fired_at")
                acc["first_run_verified"] = True
                acc["first_run_verified_at"] = now.isoformat(timespec="seconds")
                acc["first_run_verified_for"] = target.isoformat()
                changed = True
            else:
                pending.append("daily 首跑未通过——排程没跑成功，或当前 job 已不可信")

    # ── weekly ───────────────────────────────────────────────────────────────
    if acc.get("first_weekly_run_verified"):
        print("周段首跑：早前已验过 ✓")
    else:
        ok, notes = check_weekly_evidence(root, target)
        if target.weekday() != 6:
            print(f"周段首跑：{notes[0]}")
            pending.append("周段要等第一个目标日为周日的那趟（周一凌晨）")
        else:
            nat, nat_notes = natural_run_for(a.runtime, target, bh,
                                             receipt=receipt)
            notes.extend(nat_notes)
            job_ok, job_notes = current_job_state(
                a.runtime, receipt.get("job_generation"), receipt)
            notes.extend(job_notes)
            ok = ok and nat is not None and job_ok
            print(f"周段首跑：{'PASS' if ok else '未通过'}")
            for n in notes:
                print(f"  - {n}")
            if ok:
                acc["first_weekly_run_natural_scheduled_at"] = nat.get("scheduled_at")
                acc["first_weekly_run_natural_fired_at"] = nat.get("fired_at")
                acc["first_weekly_run_verified"] = True
                acc["first_weekly_run_verified_at"] = now.isoformat(timespec="seconds")
                acc["first_weekly_run_verified_for"] = target.isoformat()
                changed = True
            else:
                pending.append("周段首跑未通过——周日那趟没跑成功")

    if changed and not a.dry_run:
        rpath.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
        print(f"已回写收据 {rpath}")
    elif changed:
        print("DRY-RUN：核过了但未回写")

    if pending:
        print("待验：" + "；".join(pending))
        return 1
    print("ACCEPTANCE COMPLETE — 日跑与周段都已有实证")
    return 0


if __name__ == "__main__":
    sys.exit(main())
