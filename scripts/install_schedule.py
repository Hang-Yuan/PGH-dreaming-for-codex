#!/usr/bin/env python3
"""install_schedule.py — 部署期自动排程器（跨平台 / 双 runtime）

把每日固化任务（daily-dream）装进操作系统的调度器，并处理夜间供电。
部署时由 AI 按初始化访谈得到的作息调用一次，之后无需人工维护。

  # 1. 先探供电（只读，不改任何东西）
  python3 install_schedule.py --check-power

  # 2. 按作息算日界线并装排程
  python3 install_schedule.py --runtime claude --sleep 02:00 --wake 09:00

  # 3. 想让它跑完关机
  python3 install_schedule.py --runtime codex --sleep 22:30 --wake 05:00 --shutdown-after

  # 卸载
  python3 install_schedule.py --runtime claude --uninstall

`--dry-run` 打印将要执行的一切而不落地。退出码 0 = 成功，非 0 = 失败并已说明原因。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import re as _re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

JOB_LABEL = "pgh.daily-dream"
PGH_DIR = Path.home() / ".pgh"


def receipt_path(runtime: str) -> Path:
    """收据按 runtime 分开。

    两端共用一份收据会互相覆盖：同机先装 Claude 再装 Codex，第二次安装把第一份收据
    连同它的 `acceptance` 验收状态一起写没；卸载任一端又会把另一端的验收状态删掉。
    首跑日志同理——混在一个文件里分不清哪趟是哪个 runtime 跑的。
    """
    return PGH_DIR / f"schedule_receipt.{runtime}.json"


def log_path(runtime: str) -> Path:
    return PGH_DIR / f"daily-dream.{runtime}.log"


#: 兼容旧路径：v6.2.0 之前两端共用这两个文件。只用于迁移与报错提示，不再写入。
LEGACY_RECEIPT = PGH_DIR / "schedule_receipt.json"
LEGACY_LOG = PGH_DIR / "daily-dream.log"

# 日界线允许区间：不早于 02:00（再早会把深夜工作切进次日），
# 不晚于 06:00（再晚会把清晨工作切进前一日）。
BOUNDARY_MIN_H = 2
BOUNDARY_MAX_H = 6
# 日界线与起床之间留出的余量：起床即开工的人不能一起来就还算前一天。
HOURS_BEFORE_WAKE = 1
# 日界线须落在入睡后至少这么久，避免用户还在工作时就切日。
MIN_HOURS_AFTER_SLEEP = 1
# 固化在日界线之后多久跑：要等目标逻辑日彻底关闭。
DREAM_OFFSET_MIN = 30


# ── 时刻推算 ──────────────────────────────────────────────────────────────────
def parse_hhmm(raw: str, field: str) -> tuple[int, int]:
    try:
        h, m = raw.strip().split(":")
        hh, mm = int(h), int(m)
    except ValueError:
        raise SystemExit(f"{field} 需要 HH:MM 格式，收到 {raw!r}")
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise SystemExit(f"{field} 超出合法范围：{raw!r}")
    return hh, mm


def derive_boundary(sleep: tuple[int, int], wake: tuple[int, int]) -> tuple[int, str]:
    """由作息推日界线整点。

    日界线要落在「已睡下、还没起」的那段里，且**尽可能靠后**——因为切早了会把
    一段连续的深夜工作劈成两个逻辑日，而切晚（贴着起床）只是让固化早一点跑。
    故基准取「起床前 HOURS_BEFORE_WAKE 小时」，再夹进允许区间，最后确认它确实
    晚于入睡时刻。返回 (小时, 推算说明)——说明写进收据，供人回看当初为何是这个数。
    """
    sleep_h, sleep_m = sleep
    wake_h, wake_m = wake

    hour = wake_h - HOURS_BEFORE_WAKE
    reason = f"起床 {wake_h:02d}:{wake_m:02d} − {HOURS_BEFORE_WAKE}h"

    if hour > BOUNDARY_MAX_H:
        hour = BOUNDARY_MAX_H
        reason += f"，被上界 {BOUNDARY_MAX_H:02d}:00 压下"
    if hour < BOUNDARY_MIN_H:
        hour = BOUNDARY_MIN_H
        reason += f"，被下界 {BOUNDARY_MIN_H:02d}:00 抬起"

    # 入睡时刻映射到「凌晨坐标系」：22:30 → -1.5，01:00 → 1.0。这样熬夜到凌晨的人
    # 与晚上就睡的人能用同一条不等式比较。
    sleep_pos = sleep_h + sleep_m / 60
    if sleep_pos >= 12:
        sleep_pos -= 24

    # 日界线必须晚于入睡至少 MIN_HOURS_AFTER_SLEEP：否则人还在工作时就切了日。
    earliest = sleep_pos + MIN_HOURS_AFTER_SLEEP
    if hour < earliest:
        bumped = min(BOUNDARY_MAX_H, int(earliest) + (earliest > int(earliest)))
        if bumped != hour:
            reason += (f"，因入睡 {sleep_h:02d}:{sleep_m:02d} 太晚"
                       f"（须至少 +{MIN_HOURS_AFTER_SLEEP}h）后移到 {bumped:02d}:00")
            hour = bumped

    # 可行性闸——夹取只保证结果落在 [MIN, MAX]，不保证它真落在「已睡下、还没起」
    # 之间。作息本身把窗口挤没了时（睡 05:00 起 07:00：需 ≥06:00 又需 ≤06:00 之前
    # 且不晚于起床前 1h = 无解），必须拒绝并让人显式指定，不能给一个夹出来的数字
    # 假装算好了——那正是「每天都归错日子」的来源。
    latest_ok = wake_h + wake_m / 60
    if hour < earliest - 1e-9 or hour >= latest_ok:
        raise SystemExit(
            f"作息 {sleep_h:02d}:{sleep_m:02d} 睡 / {wake_h:02d}:{wake_m:02d} 起 "
            f"在 [{BOUNDARY_MIN_H:02d}:00, {BOUNDARY_MAX_H:02d}:00] 内没有可行的日界线"
            f"（须晚于入睡 {MIN_HOURS_AFTER_SLEEP}h、且早于起床）。"
            "请用 --boundary-hour 显式指定一个整点，并自行确认它落在你确实不工作的时段。"
        )

    return hour, reason


def dream_time(boundary_h: int) -> tuple[int, int]:
    """固化时刻 = 日界线 + DREAM_OFFSET_MIN。"""
    t = datetime(2000, 1, 1, boundary_h) + timedelta(minutes=DREAM_OFFSET_MIN)
    return t.hour, t.minute


# ── 供电探测 ──────────────────────────────────────────────────────────────────
def check_power() -> tuple[bool, list[str]]:
    """探本机能否在夜里无人时把任务跑完。返回 (是否就绪, 逐条说明)。

    排程装上了不等于会跑：机器睡了、盖子合了、任务计划器被设成「仅接通电源时
    运行」而机器在用电池——这些都让排程静默失效，且不报错。故装之前先探。
    """
    notes: list[str] = []
    system = platform.system()

    if system == "Darwin":
        ok = True
        out = _run_capture(["pmset", "-g", "custom"])
        if out is None:
            notes.append("无法读取 pmset 设置——请手动确认「系统设置 → 锁定屏幕 → 接通电源时…」")
            return False, notes
        ac = _pmset_ac_block(out)
        if ac is None:
            notes.append("pmset 输出里找不到 `AC Power:` 段——请手动确认接通电源时不睡眠")
            return False, notes
        sleep_val = _pmset_field(ac, "sleep")
        if sleep_val is not None and sleep_val != 0:
            ok = False
            notes.append(
                f"接通电源时系统 {sleep_val} 分钟后睡眠——睡眠中排程不会触发。"
                "请设为「永不」：系统设置 → 锁定屏幕 → 接通电源时…，或 "
                "`sudo pmset -c sleep 0`"
            )
        else:
            notes.append("接通电源时系统不睡眠 ✓")
        if _pmset_field(ac, "powernap") == 0:
            notes.append("Power Nap 关闭——建议开启以提高唤醒可靠性（`sudo pmset -c powernap 1`）")
        # 合盖行为要说准。早先写「合盖也行，接电源就好」是错的：macOS 笔记本合盖
        # 默认进睡眠，接电本身不阻止它。可跑的是「锁屏 / 关显示器、机器不睡」。
        notes.append("锁屏或关掉显示器都能跑——排程不需要有人登录在前台。")
        notes.append("**合盖不行**：macOS 笔记本合盖默认睡眠，接电源也不解除；"
                     "要合盖运行须外接显示器或用第三方工具阻止睡眠。夜里留机就别合盖。")
        notes.append("睡眠 / 关机 / 断网导致这趟没跑或跑失败时，排程不会自己补——"
                     "由次日第一个真人会话的 week-sync 查出断档并后台补跑（最多三天）。")
        return ok, notes

    if system == "Windows":
        notes.append("任务计划程序默认「仅在计算机使用交流电源时运行」——用电池会跳过本次触发。")
        notes.append("安装器会同时关掉「电池供电时停止」并允许唤醒计算机运行任务。")
        notes.append("请确认电源计划里「睡眠」设为「从不」（接通电源时）。")
        notes.append("锁屏可跑；合盖按「合上盖子时」的电源设置，设成「不采取任何操作」才跑。")
        notes.append("已设 StartWhenAvailable：错过的触发在机器可用后会补一次。"
                     "仍漏掉的由次日第一个真人会话 week-sync 后台补跑（最多三天）。")
        return True, notes

    if system == "Linux":
        ok = True
        if shutil.which("systemctl") is None:
            ok = False
            notes.append("未找到 systemctl——本脚本在 Linux 上依赖 systemd timer")
        else:
            notes.append("将装 systemd user timer（含 Persistent=true，错过的触发开机后补跑）")
            notes.append("如需关机后仍生效请启用 lingering：`loginctl enable-linger $USER`")
            notes.append("三平台里只有这条不需要人记着补：Persistent=true 会在开机后"
                         "自动补跑错过的那趟。仍失败的（如断网）由次日第一个真人会话"
                         "week-sync 后台补跑（最多三天）。")
        return ok, notes

    notes.append(f"未识别的平台 {system}——请手动排程")
    return False, notes


def _run_capture(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _pmset_ac_block(text: str) -> str | None:
    """切出 `AC Power:` 段。

    实测（2026-08-01，macOS 25.5）`pmset -g custom` 把 `Battery Power:` 排在
    **前面**，`AC Power:` 在后。故不能用 `split("Battery Power")[0]` 取 AC 段——
    那会得到空串，`_pmset_field` 在空串上返回 None，于是「AC 段 sleep=1」被当成
    「不睡眠 ✓」报 READY。假绿的方向恰好是最坏的：真会漏跑时说没问题。
    改为显式找 `AC Power:` 标题，读到下一个 `XXX Power:` 标题或文末为止。
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().rstrip(":").strip() == "AC Power":
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        s = lines[j].strip()
        # 段标题的形状：顶格、以 `Power:` 结尾。段内字段一律有前导空格。
        if s.endswith("Power:") and lines[j][:1] not in (" ", "\t"):
            end = j
            break
    return "\n".join(lines[start:end])


def _pmset_field(text: str, key: str) -> int | None:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == key:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


# ── 被排的命令 ────────────────────────────────────────────────────────────────
#: 两端共用的载荷正文——说清目标日与无人值守约束。
_PROMPT_BODY = (
    "目标逻辑日 = 昨天（按宪法层的逻辑日期口径自行推算，日界线不是固定 06:00，"
    "读当前值；不要用物理日期）。无人值守运行：不要问我任何问题，遇到需要 C 级"
    "确认的动作就写进提案等我醒来看。"
)

#: 各端调起 packaged skill 的原生语法。**不能只写「跑 daily-dream」**——那是自然语言
#: 请求，模型可能自己即兴做一遍相似的事而不加载 skill 文件，于是每天跑的是一条没有
#: 判据的即兴流程。精确 token 的 smoke 只证明 CLI 与鉴权通，不证明 skill 被路由到。
_SKILL_INVOCATION = {
    "claude": "/daily-dream",
    "codex": "$daily-dream",
}


def prompt_for(runtime: str) -> str:
    """按 runtime 拼出显式调起 skill 的 prompt。"""
    invoke = _SKILL_INVOCATION.get(runtime)
    if invoke is None:
        raise SystemExit(f"未知 runtime：{runtime}")
    return f"{invoke}\n\n{_PROMPT_BODY}"


#: 向后兼容：早前的调用点直接引用 PROMPT。保留为 Claude 形式。
PROMPT = prompt_for("claude")


#: `--dry-run` 里找不到可执行文件时用的占位符。必须是一眼假的字符串——若写成某个
#: 看似合理的路径，预览输出会被误读成「这条命令能跑」。
EXE_PLACEHOLDER = "<未找到-{}-可执行文件>"

#: Claude 的「不落会话」开关。**正式夜间命令必须带**：实测（2026-08-01）不带它时
#: `claude -p` 会在 `~/.claude/projects/<cwd>/` 落一份 jsonl 转写；而 daily-dream 的
#: 输入正是转写目录，于是排程每天生成的那份会进入次日的回放候选——链读到自己昨天
#: 的输出，形成自我回放，且 session 库被每日一份的机器会话长期污染。
#: 实测带上后 jsonl 计数不变（2548 → 2548）。
CLAUDE_NO_PERSIST = "--no-session-persistence"

#: Codex headless 的现行参数。实测（2026-08-01，codex-cli 0.146.0-alpha.9.2）：
#: `--full-auto` 的精确状态是 **deprecated**——仍能跑，但会打
#: `warning: --full-auto is deprecated; use --sandbox workspace-write instead`。
#: 不留它是因为不想让每夜无人值守的任务吊在一个弃用兼容层上：兼容层被摘掉的那天，
#: 失败发生在夜里没人看着，表现只是「今天没固化」。
#: `--skip-git-repo-check` 是必需的：assistant 知识库通常不是 git 仓库，缺它 codex
#: 拒绝启动。`--sandbox workspace-write` 给固化所需的写权限而不放开整机。
CODEX_EXEC_FLAGS = ("--sandbox", "workspace-write", "--skip-git-repo-check")


def runtime_cmd(runtime: str, workdir: Path, shutdown: bool,
                allow_missing_exe: bool = False) -> str:
    """构造被排的 shell 命令。两端 CLI 的 headless 入口不同。

    `allow_missing_exe` 只给 `--dry-run` 用：预览不落地任何东西，因为缺一个二进制
    就整个中止会把「另一端的排程长什么样」这个问题也一起挡掉。真安装仍必须中止
    ——排程指向不存在的可执行文件时不会有任何报错，只是每天夜里静默失败一次。
    """
    if runtime not in _EXE_FALLBACKS:
        raise SystemExit(f"未知 runtime：{runtime}")
    try:
        exe = _find_exe(runtime, _EXE_FALLBACKS[runtime])
    except SystemExit:
        if not allow_missing_exe:
            raise
        exe = EXE_PLACEHOLDER.format(runtime)
    if runtime == "claude":
        core = (f'{_q(exe)} -p {_q(prompt_for(runtime))} '
                f'--permission-mode acceptEdits --output-format text '
                f'{CLAUDE_NO_PERSIST}')
    else:
        core = (f'{_q(exe)} exec {_q(prompt_for(runtime))} '
                f'{" ".join(CODEX_EXEC_FLAGS)} --ephemeral '
                f'-C {_q(str(workdir))}')

    log = log_path(runtime)
    cmd = f'cd {_q(str(workdir))} && {core} >> {_q(str(log))} 2>&1'
    if shutdown:
        # 关机只在任务成功收尾后执行；失败时留机，好让人早上能看现场。
        cmd += " && " + _shutdown_cmd()
    return cmd


# ── job generation + scheduler proof ─────────────────────────────────────────
# A11 修的是这个断点：包装器只要被直接运行，就自行写 `source=os-scheduler`。于是
# sentinel 只能证明「包装器跑过」，证明不了「OS job 到点自然触发过」——而这两件事的
# 区别正是首跑验收要回答的问题。
#
# 做法：每次安装生成一对 (generation, proof)。**proof 只嵌进这一次的 OS job 命令**，
# 收据里只存它的 SHA-256 与 generation。包装器必须从环境里拿到 proof、算出的 hash 与
# 收据相符，才允许写 `source=os-scheduler` 的成功 sentinel；否则降级成
# `source=manual-wrapper`，验收器不认。
#
# 边界要说清楚：这不防「本机用户故意去 job 定义里抄 secret」——同一个用户能读自己的
# LaunchAgents，任何本地方案都挡不住，声称能挡是自欺。它防的是**普通手工补跑**与
# **陈旧状态误判**：直接跑 wrapper、重装后留下的旧 generation sentinel、从另一个
# runtime 复制过来的 sentinel、被替换或禁用的 job 靠旧 sentinel 蒙过当前验收。
PROOF_ENV = "PGH_SCHED_PROOF"
GEN_ENV = "PGH_JOB_GENERATION"
#: job 定义里带的**名义触发时刻**（`HH:MM`），包装器据此算 sentinel 的 `scheduled_at`。
#
# 为什么不让包装器自己去读收据里的 `dream_time`：收据是本机可读的普通 json，任何手工
# 跑包装器的进程都读得到它，于是算出来的 `scheduled_at` 无法区分「排程到点触发」与
# 「有人手工跑了一趟」。名义时刻走与 proof 同一条注入通道（只写进那一次的 job 定义），
# 故它在 sentinel 里出现这件事本身就带着「来自 job」的含义。
SCHED_TIME_ENV = "PGH_SCHED_TIME"


def new_generation() -> str:
    """本次安装的代号。人可读（带时间戳）+ 不重复（带随机尾）。"""
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"


def new_proof() -> str:
    """高熵 proof。只出现在 OS job 的命令 / 环境里，不写进收据。"""
    return secrets.token_urlsafe(32)


#: sentinel MAC 覆盖的字段，顺序固定。顺序进 MAC 是必须的——用 dict 序会让同一组值
#: 在不同 Python 版本下算出不同 MAC，于是验收在别人机器上恒红。
#
# `scheduled_at` **必须进签名集合**：它是「这趟由排程到点触发」的字面陈述，不签就等于
# 允许在一条已签名的记录上贴一个任意的名义时刻——而验收器读它。
MAC_FIELDS = ("runtime", "job_generation", "fired_at", "finished_at",
              "exit", "status", "label", "scheduled_at")

#: `scheduled_at` 之前的签名集合。**不能靠「缺字段写空串」自动兼容**——缺键算出的
#: payload 会多一段 `\x1fscheduled_at=`，与它当年被签名时的 payload 不同字节，旧
#: sentinel 的 MAC 因此复算不上。升级安装器不该让用户已经攒下的自然运行凭据集体失效
#: （那等于把已经验过的首跑重新打回未验），故旧集合显式留一份用于回退校验。
LEGACY_MAC_FIELDS = ("runtime", "job_generation", "fired_at", "finished_at",
                     "exit", "status", "label")


def canonical_mac_payload(rec: dict, fields: tuple[str, ...] | None = None) -> str:
    """把 sentinel 的关键字段拼成待签名串。缺字段写空，不跳过——跳过会让
    `{a:1,b:""}` 与 `{a:1}` 算出同一个 MAC，于是删掉一个字段就能改变语义而 MAC 不变。
    """
    return "\x1f".join(f"{k}={rec.get(k, '')!s}"
                       for k in (fields or MAC_FIELDS))


def sentinel_mac(proof: str, generation: str, rec: dict,
                 fields: tuple[str, ...] | None = None) -> str:
    """用 job secret 对 sentinel 关键字段做 HMAC。

    **只比 generation 与 proof hash 是不够的**：这两个值都写在收据里，而收据是本机可读
    的普通 json。于是手工往 JSONL 里贴一行、把收据里的 `job_generation` 与
    `scheduler_proof_sha256` 抄进去，就能造出一条验收器认可的「自然运行」——公开字段
    对得上，而它根本没被排程触发过。

    MAC 用的是 proof 本身（只存在于 job 定义里），故只有真的从 job 环境里拿到 proof 的
    那个进程能算出来。抄公开字段算不出。

    信任边界仍然是同一个用户：能读自己 LaunchAgents 的人能拿到 proof，也就能自己算
    MAC。这挡不住刻意伪造，挡的是普通手工补跑与陈旧状态误判。
    """
    return hmac.new(proof.encode(),
                    canonical_mac_payload(rec, fields).encode(),
                    hashlib.sha256).hexdigest()


def proof_matches(proof: str, generation: str, want_hash: str) -> bool:
    """常量时间比对 proof hash。"""
    return hmac.compare_digest(proof_hash(proof, generation), want_hash)


def mac_matches(proof: str, generation: str, rec: dict, mac: str) -> bool:
    """复算 sentinel MAC 并常量时间比对。

    带 `scheduled_at` 的记录按当前集合校验；**不带该键的旧记录**回退到
    `LEGACY_MAC_FIELDS` 再算一次。回退只对「键根本不在场」的记录开放——记录里有
    `scheduled_at` 时一律按当前集合判，故不能靠「把签过名的 scheduled_at 删掉」来绕过
    签名，也不能靠「往旧记录里贴一个 scheduled_at」蒙过去（前者会走当前集合算不上，
    后者同理）。
    """
    if hmac.compare_digest(sentinel_mac(proof, generation, rec), str(mac)):
        return True
    if "scheduled_at" in rec:
        return False
    return hmac.compare_digest(
        sentinel_mac(proof, generation, rec, LEGACY_MAC_FIELDS), str(mac))


def proof_hash(proof: str, generation: str) -> str:
    """收据里存的可校验值。

    带 generation 一起摘要：否则把上一次安装的 proof 配上新 generation 也能算出旧
    hash，重装就白做了。
    """
    return hashlib.sha256(f"{generation}\0{proof}".encode()).hexdigest()


#: 排程包装器。
WRAPPER_NAME = "run_scheduled_dream.py"

#: 排程要长期调用的脚本，安装时复制到持久根。
RUNTIME_SCRIPTS = (WRAPPER_NAME, "install_schedule.py", "verify_first_run.py")

#: 持久运行根。**排程不能指向仓库目录。**
#: 新用户的典型路径是 `git clone` 到临时目录 → 跑安装 → 删掉 clone。此时若 job 指向
#: 仓库里的脚本，每夜固化会静默失败（文件不存在），且改作息、卸载、首跑验收全部断路。
#: 故安装时把这几个脚本复制到 `~/.pgh/scripts/`，job 只引用这份副本。
SCRIPTS_DIR = PGH_DIR / "scripts"


def snapshot_scripts(runtime: str) -> dict[str, bytes] | None:
    """存下持久根里现有脚本的内容，够用来原样恢复。目录不存在则返回 None。

    **脚本在备份之前就被覆盖了**是事务的一个漏洞：`install_runtime_scripts()` 直接
    `copy2` 覆盖持久根，而回滚只还原正文与 job。于是「重装到一半失败」会留下一套新脚本
    配一个旧 job——两者的 generation 对不上，此后每夜的自然运行凭据都判不匹配，而排程
    看起来在跑、日志也正常，故这个不一致在地面证据上看不出来。
    """
    root = scripts_dir_for(runtime)
    if not root.exists():
        return None
    snap: dict[str, bytes] = {}
    for name in RUNTIME_SCRIPTS:
        f = root / name
        if f.exists():
            try:
                snap[name] = f.read_bytes()
            except OSError:
                pass
    return snap


def restore_scripts(runtime: str, snap: dict[str, bytes] | None) -> str:
    """把持久根恢复到 `snap`。`None` = 原先没有这个目录，故整个删掉。"""
    root = scripts_dir_for(runtime)
    if snap is None:
        try:
            if root.exists():
                shutil.rmtree(root)
            return "已删掉本次新建的持久脚本目录（原先没有）"
        except OSError as e:                                     # noqa: BLE001
            return f"删除持久脚本目录失败，请手工处理：{e}"
    done, failed = [], []
    for name in RUNTIME_SCRIPTS:
        f = root / name
        try:
            if name in snap:
                f.write_bytes(snap[name])
                done.append(name)
            elif f.exists():
                # 安装前不存在的脚本：本次新加的，回滚要拿掉。
                f.unlink()
                done.append(f"{name}（删除）")
        except OSError as e:                                     # noqa: BLE001
            failed.append(f"{name}（{e}）")
    msg = f"持久脚本已恢复 {len(done)} 项"
    return msg + (f"；失败：{', '.join(failed)}——请手工处理" if failed else "")


def scripts_dir_for(runtime: str) -> Path:
    """某一端的持久脚本根。

    **按 runtime 分开。** 两端共用一份的话，装 Codex 会覆盖 Claude 正在用的包装器：
    版本一致时看不出问题，而一旦两端的脚本版本不同步（一端先升级），后装的那一端会把
    另一端的 job 指向的文件换掉——被换掉的那端仍然每夜触发，跑的却是别一版的代码，
    且它的 job 命令、收据、日志全都不变，故这个错位在任何一处产物上都看不出来。
    """
    return SCRIPTS_DIR / runtime


def install_runtime_scripts(runtime: str, dry: bool = False) -> tuple[Path, list[str]]:
    """把排程要长期用的脚本复制到该端的持久根。返回 (目标目录, 逐条说明)。"""
    src_dir = Path(__file__).resolve().parent
    target = scripts_dir_for(runtime)
    notes: list[str] = []
    if src_dir == target:
        return target, ["已在持久根内运行，无需复制"]
    if not dry:
        target.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_SCRIPTS:
        src = src_dir / name
        if not src.exists():
            notes.append(f"缺 {name}（跳过）")
            continue
        dst = target / name
        if not dry:
            shutil.copy2(src, dst)
        notes.append(f"{name} → {dst}")
    return target, notes


def wrapper_path(runtime: str) -> Path:
    """job 里引用的包装器路径：优先该端的持久副本，其次源目录。

    顺序不能反。指向源目录的 job 在 clone 被删后就成了一个每夜静默失败的排程。
    """
    persistent = scripts_dir_for(runtime) / WRAPPER_NAME
    if persistent.exists():
        return persistent
    return Path(__file__).resolve().parent / WRAPPER_NAME


def scheduled_cmd(runtime: str, workdir: Path, shutdown: bool,
                  allow_missing_exe: bool = False,
                  proof: str | None = None, generation: str | None = None,
                  sched_time: str | None = None) -> str:
    """真正装进排程的命令：走包装器，而不是直接调 CLI。

    多这一层只为一件事——**留下只有排程能写出来的自然运行凭据**。地面证据（探针 /
    MEMORY_LOG / 日志里出现某个日期）手工补跑也会写出来，于是「用户自己补跑了一次」
    与「排程夜里自然跑成功了」在收据上同形，验收器会把前者当后者翻绿。而这两件事的
    失败后果不同：排程没装成时用户每天得记着手工补，忘一次就静默丢一天。

    包装器缺失时退回直调 CLI：宁可少一层验收证据，也不要因为脚本目录被挪走就让每夜
    固化整个停摆。这种降级会在收据的 `scheduled_via` 字段里显式记下来。
    """
    w = wrapper_path(runtime)
    if not w.exists():
        return runtime_cmd(runtime, workdir, shutdown, allow_missing_exe)
    # 先验证 CLI 存在（真安装时缺二进制必须中止），再拼包装器命令。
    runtime_cmd(runtime, workdir, shutdown, allow_missing_exe)
    core = (f'{_q(sys.executable)} {_q(str(w))} --runtime {runtime} '
            f'--assistant-root {_q(str(workdir))}')
    if shutdown:
        core += " --shutdown-after"
    log = log_path(runtime)

    # **赋值必须紧贴被执行的那条命令。** 早先拼成
    #   `VAR=v cd <dir> && python wrapper ...`
    # ——POSIX 里前缀赋值只对紧随其后的那一条命令（这里是 `cd`）生效，`&&` 之后的
    # 包装器进程环境里根本没有这两个变量。实测 zsh 与 sh 都取到空值，于是每一趟自然
    # 触发都会被判成 `manual-wrapper`，首跑验收永远翻不绿——而排程本身在跑，日志和
    # 探针都正常，故这个失败在地面证据上完全看不出来。
    if platform.system() == "Windows":
        # cmd.exe 不认 POSIX 前缀赋值，必须走 `set "VAR=value" && ...`。
        prefix = ""
        if proof and generation:
            prefix = (f'set "{PROOF_ENV}={proof}" && '
                      f'set "{GEN_ENV}={generation}" && ')
            if sched_time:
                prefix += f'set "{SCHED_TIME_ENV}={sched_time}" && '
        return (f'{prefix}cd /d {_q(str(workdir))} && '
                f'{core} >> {_q(str(log))} 2>&1')

    assign = ""
    if proof and generation:
        # proof 以环境变量传给包装器，**只存在于这一次的 job 定义里**。收据只留它的
        # hash，故看收据的人（和验收器）能校验，但拿不到 proof 本身去伪造 sentinel。
        assign = f'{PROOF_ENV}={_q(proof)} {GEN_ENV}={_q(generation)} '
        if sched_time:
            # 名义触发时刻与 proof 同批注入：它是 `scheduled_at` 的唯一来源，故必须
            # 和 proof 一样只存在于 job 定义里，手工跑包装器时环境里没有它。
            assign += f'{SCHED_TIME_ENV}={_q(sched_time)} '
    return f'cd {_q(str(workdir))} && {assign}{core} >> {_q(str(log))} 2>&1'


def redact(cmd: str) -> str:
    """把命令里的 proof 值替换掉，供打印 / 回报使用。

    安装过程会把将要装的命令打出来给用户看（dry-run 更是全靠这一份输出）。原样打印
    等于把 proof 抄进终端回滚缓冲、CI 日志、以及用户随手贴出来的报错里——而 proof
    的全部作用就是「只存在于 job 定义中」，泄漏一次这一代就不再能区分自然与手工。
    """
    out = _re.sub(rf'({PROOF_ENV}=)(")?[^\s"]+(")?', r'\1<REDACTED>', cmd)
    return _re.sub(rf'(set "{PROOF_ENV}=)[^"]*(")', r'\1<REDACTED>\2', out)


SMOKE_TOKEN = "PGH_HEADLESS_OK"


def _session_dirs(runtime: str) -> list[Path]:
    """各端落会话转写的目录。用于 smoke 前后计数。"""
    if runtime == "claude":
        return [Path.home() / ".claude" / "projects"]
    return [Path.home() / ".codex" / "sessions",
            Path.home() / ".codex" / "archived_sessions"]


def _snapshot_sessions(runtime: str) -> set[Path]:
    """会话转写文件的**路径集合**，不是计数。

    计数不足以清理：`after != before` 只说明多了几份，说不出是哪几份。而清理必须
    精确到文件——删错一份就删掉了用户的真实工作转写，那是 L0 唯一副本，不可恢复。
    故取前后路径差集，只动差集里的文件。
    """
    seen: set[Path] = set()
    for d in _session_dirs(runtime):
        if d.exists():
            seen.update(d.rglob("*.jsonl"))
    return seen


def _is_probe_transcript(path: Path) -> bool:
    """这份新增转写确实是本次探针写的吗？

    只按「新出现」就删是不够的：探针跑的那一分钟里用户可能正好在另一个窗口开了
    会话，那份也会是新增。故要求文件里出现探针 token 才算，且体量必须小——真实
    工作会话不会只有几行。两条都满足才动它。
    """
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if SMOKE_TOKEN not in body:
        return False
    return len(body.splitlines()) <= 40


def smoke_run(runtime: str, workdir: Path) -> tuple[bool, str]:
    """真调一次 headless CLI，证明被排的调用形式在本机能跑通。

    没有这一步，`--dry-run` 只证明命令字符串拼对了；而 headless 入口的真实失败
    形态（未登录 / 参数被上游改名 / 权限模式被拒 / 二进制在 PATH 外）全都只在真跑
    时才现形，且排程跑失败是在夜里、没人看着。故装完顺手跑一次最小 prompt。
    """
    try:
        exe = _find_exe(runtime, _EXE_FALLBACKS[runtime])
    except SystemExit as e:
        return False, f"BLOCKED：{e}"
    prompt = f"Reply with exactly: {SMOKE_TOKEN}"
    if runtime == "claude":
        # `--no-session-persistence` 与 Codex 的 `--ephemeral` 对位。实测缺了它
        # `claude -p` 会在 `~/.claude/projects/` 落一份转写（jsonl 数 2547→2548），
        # 那份会进次日回放候选，链读到一句「Reply with exactly: ...」当成真实对话。
        cmd = [exe, "-p", prompt, "--permission-mode", "acceptEdits",
               "--output-format", "text", CLAUDE_NO_PERSIST]
    else:
        cmd = [exe, "exec", prompt, *CODEX_EXEC_FLAGS, "--ephemeral",
               "-C", str(workdir)]
    before = _snapshot_sessions(runtime)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(workdir), timeout=300)
    except subprocess.TimeoutExpired:
        return False, "超时 300s——headless 调用没能在合理时间内返回"
    except OSError as e:
        return False, f"无法执行：{e}"

    # 残留是**失败条件**，不是备注。带着 L0 污染进 READY 等于把一段假对话留在次日
    # 回放的输入里；而 residue 只写进说明时，READY 这个唯一结论字段照样是绿的，
    # 读收据的人（和 week-sync）不会知道。故先清理、复验，仍有残留就判 FAIL。
    new_files = sorted(_snapshot_sessions(runtime) - before)
    cleaned, stubborn = [], []
    for f in new_files:
        if not _is_probe_transcript(f):
            stubborn.append(f"{f}（不像探针产物，未动）")
            continue
        try:
            f.unlink()
            cleaned.append(f.name)
        except OSError as e:
            stubborn.append(f"{f}（删除失败：{e}）")
    left = sorted(_snapshot_sessions(runtime) - before)
    if left and not stubborn:
        stubborn = [f"{f}（复验仍在）" for f in left]

    if stubborn:
        return False, ("FAIL：探针在 L0 留下会话残留，"
                       f"{CLAUDE_NO_PERSIST if runtime == 'claude' else '--ephemeral'} "
                       f"没有生效——{'; '.join(stubborn)}。"
                       "带残留的探针不能算通过：那段假对话会被次日回放读成真实工作。")
    residue = ("会话残留 0（隔离生效）" if not cleaned
               else f"会话残留 0（清理了 {len(cleaned)} 份探针转写：{', '.join(cleaned)}）")

    blob = (r.stdout or "") + (r.stderr or "")
    if SMOKE_TOKEN in blob:
        return True, (f"headless 实跑通过（exit={r.returncode}，回显命中 token）"
                      f"；{residue}")
    tail = blob.strip().splitlines()[-3:] if blob.strip() else ["（无输出）"]
    return False, (f"headless 实跑未见 token（exit={r.returncode}）："
                   f"{' | '.join(tail)}；{residue}")


#: PATH 之外的已知安装位置。桌面应用捆绑的 CLI 常不在 PATH 里——实测本机 codex 就
#: 只在 ChatGPT.app 内（`codex-cli 0.146.0-alpha.9.2`），`shutil.which` 找不到。漏掉
#: 这类位置的后果是把「装好的 CLI」误报成 BLOCKED。
_EXE_FALLBACKS: dict[str, list[Path]] = {
    "claude": [
        Path.home() / ".claude" / "local" / "claude",
        Path("/Applications/Claude.app/Contents/Resources/claude"),
    ],
    "codex": [
        Path.home() / ".codex" / "bin" / "codex",
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    ],
}


def _find_exe(name: str, extra: list[Path]) -> str:
    hit = shutil.which(name)
    if hit:
        return hit
    for p in extra:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    raise SystemExit(
        f"找不到 {name} 可执行文件。先装好 {name} CLI 并确认它在 PATH 里，再跑本脚本。"
    )


def _shutdown_cmd() -> str:
    system = platform.system()
    if system == "Darwin":
        return "sudo -n /sbin/shutdown -h now || echo 'PGH: 关机需要免密 sudo，已跳过'"
    if system == "Windows":
        # /t 60 留一分钟窗口，人在场时可 `shutdown /a` 中止。
        return "shutdown /s /t 60"
    return "systemctl poweroff || echo 'PGH: 关机失败，已跳过'"


def shutdown_ready() -> tuple[bool, str]:
    """探关机能不能真的执行。**只读探测，绝不排一次真关机。**

    早先的实现用 `sudo -n /sbin/shutdown -h +2400` 探，靠随后 `killall shutdown`
    撤销。那是在部署机上真排了一次关机：`killall` 若失败（权限 / 进程名不符 /
    脚本在这两行之间被中断），机器会在 40 小时后自己关掉，而部署者完全不知道
    为什么。探测不该有副作用，故改用 `sudo -n -l`——它只查授权表，不执行。
    """
    system = platform.system()
    if system == "Darwin":
        r = subprocess.run(["sudo", "-n", "-l", "/sbin/shutdown"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return True, "免密 sudo 已授权 /sbin/shutdown，关机会执行"
        return False, (
            "没有免密 sudo，任务跑完不会关机（只在日志里留一行提示）。"
            "要真关机，请在 `sudo visudo` 里加一行："
            f"`{os.environ.get('USER', 'youruser')} ALL=(root) NOPASSWD: /sbin/shutdown`"
        )
    if system == "Windows":
        return True, "shutdown /s 无需额外权限"
    if shutil.which("systemctl") is None:
        return False, "未找到 systemctl，关机不会执行"
    # polkit 授权只能在真调用时才知道，故这里只能报「命令在、结果待跑时看日志」。
    return True, "systemctl poweroff 可用（无 polkit 授权时会被拒，跑完看日志）"


def _q(s: str) -> str:
    """跨平台的最小引用。Windows 走 cmd 语义，其余走 POSIX 单引号。"""
    if platform.system() == "Windows":
        return '"' + s.replace('"', '""') + '"'
    return "'" + s.replace("'", "'\\''") + "'"


# ── 旧 job 快照 / 恢复 ────────────────────────────────────────────────────────
# 事务边界必须覆盖四样东西：正文 + 旧 job 定义与启用状态 + 新 job + 收据。
# 只回滚正文是不够的：`install_macos` 为了能重复 bootstrap 同一 label，会先 bootout
# 旧 job；此时 bootstrap 失败就把一个**本来健康的**排程卸掉了，而正文回滚帮不上——
# 结果是「改作息失败」变成「原来会跑的现在也不跑了」，且夜里没人发现。
def snapshot_job(runtime: str) -> dict | None:
    """存下当前 job 的定义，够用来原样恢复。没装过则返回 None。"""
    system = platform.system()
    if system == "Darwin":
        path = _plist_path(runtime)
        if not path.exists():
            return None
        try:
            # 记下**当时是否已加载**。回滚时必须照原样还原：原先被用户手工停掉的 job，
            # 回滚把它重新启用了，等于替用户改了一个他刻意做过的决定，而且不声不响。
            listed = _run_capture(["launchctl", "list"]) or ""
            return {"kind": "launchd", "path": str(path),
                    "body": path.read_text(encoding="utf-8"),
                    "was_enabled": f"{JOB_LABEL}.{runtime}" in listed}
        except OSError:
            return None
    if system == "Windows":
        # 任务名与 install_windows / uninstall_windows 完全一致——多一个反斜杠前缀
        # 就查不到已有任务，于是快照恒为 None，重装失败时按「本来没有 job」处理，
        # 把一个健康的旧任务卸掉且不再恢复。
        name = f"{JOB_LABEL}.{runtime}"
        xml = _run_capture(["schtasks", "/Query", "/TN", name, "/XML"])
        return {"kind": "schtasks", "name": name, "xml": xml} if xml else None
    if system == "Linux":
        # unit 名与 install_linux 一致：systemd 不接受名字里的点，故换成横线。
        base = f"{JOB_LABEL}.{runtime}".replace(".", "-")
        unit = _unit_dir() / f"{base}.timer"
        svc = _unit_dir() / f"{base}.service"
        if not unit.exists():
            return None
        try:
            en = _run_capture(["systemctl", "--user", "is-enabled",
                               f"{base}.timer"]) or ""
            return {"kind": "systemd", "timer": str(unit),
                    "timer_body": unit.read_text(encoding="utf-8"),
                    "service": str(svc),
                    "service_body": svc.read_text(encoding="utf-8")
                    if svc.exists() else None,
                    "was_enabled": "enabled" in en}
        except OSError:
            return None
    return None


def restore_job(runtime: str, snap: dict | None) -> str:
    """把 job 恢复到 `snap` 记录的状态。`snap is None` = 本来没装，故卸掉新装的。

    返回一句人读的结果说明。恢复本身失败不再抛——那会盖掉真正的失败原因，
    但必须在说明里明确写出来让人手工处理。
    """
    if snap is None:
        try:
            fn = UNINSTALLERS.get(platform.system())
            if fn:
                fn(runtime, False)
            return "已卸掉本次新装的 job（原先没有 job）"
        except Exception as e:                                   # noqa: BLE001
            return f"**卸载新 job 失败**，请手工处理：{e}"
    try:
        if snap["kind"] == "launchd":
            path = Path(snap["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(snap["body"], encoding="utf-8")
            domain = f"gui/{os.getuid()}"
            label = f"{JOB_LABEL}.{runtime}"
            subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                           capture_output=True, text=True)
            if not snap.get("was_enabled", True):
                # 原先没加载：只还原 plist 正文，不 bootstrap。
                return "已恢复旧 plist 正文，并保持原来的未加载状态"
            r = subprocess.run(["launchctl", "bootstrap", domain, str(path)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                return f"**旧 job 恢复失败**（bootstrap {r.returncode}），请手工重装"
            return "已恢复旧 job 定义并重新加载"
        if snap["kind"] == "schtasks":
            import tempfile as _tf
            with _tf.NamedTemporaryFile("w", suffix=".xml", delete=False,
                                        encoding="utf-16") as fh:
                fh.write(snap["xml"])
                tmp = fh.name
            r = subprocess.run(["schtasks", "/Create", "/TN", snap["name"],
                                "/XML", tmp, "/F"], capture_output=True, text=True)
            Path(tmp).unlink(missing_ok=True)
            if r.returncode != 0:
                return f"**旧任务恢复失败**（schtasks {r.returncode}），请手工重建"
            return "已从 XML 恢复旧计划任务"
        if snap["kind"] == "systemd":
            Path(snap["timer"]).write_text(snap["timer_body"], encoding="utf-8")
            if snap.get("service_body") is not None:
                Path(snap["service"]).write_text(snap["service_body"],
                                                 encoding="utf-8")
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            name = f"{JOB_LABEL}.{runtime}".replace(".", "-") + ".timer"
            if not snap.get("was_enabled", True):
                subprocess.run(["systemctl", "--user", "disable", "--now", name],
                               capture_output=True, text=True)
                return "已恢复旧 timer 正文，并保持原来的未启用状态"
            subprocess.run(["systemctl", "--user", "enable", "--now", name],
                           capture_output=True, text=True)
            return "已恢复并重新启用旧 timer"
    except Exception as e:                                       # noqa: BLE001
        return f"**旧 job 恢复失败**，请手工核对：{e}"
    return "旧 job 类型不认识，未恢复"


# ── macOS · launchd ───────────────────────────────────────────────────────────
def _plist_path(runtime: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{JOB_LABEL}.{runtime}.plist"


def install_macos(runtime: str, hh: int, mm: int, cmd: str, dry: bool) -> list[str]:
    label = f"{JOB_LABEL}.{runtime}"
    path = _plist_path(runtime)
    log = Path.home() / ".pgh"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string><string>-lc</string><string>{_xml(cmd)}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>{log / f"{label}.out.log"}</string>
  <key>StandardErrorPath</key><string>{log / f"{label}.err.log"}</string>
</dict>
</plist>
"""
    steps = [f"写 {path}", f"launchctl bootout/bootstrap gui/{os.getuid()} {path}"]
    if dry:
        return steps
    path.parent.mkdir(parents=True, exist_ok=True)
    log.mkdir(parents=True, exist_ok=True)
    path.write_text(plist, encoding="utf-8")
    domain = f"gui/{os.getuid()}"
    # bootout 先跑：重复 bootstrap 同一 label 会失败。旧 job 不存在时 bootout
    # 报错是正常的，故不检查它的退出码。
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                   capture_output=True, text=True)
    r = subprocess.run(["launchctl", "bootstrap", domain, str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"launchctl bootstrap 失败：{r.stderr.strip() or r.stdout.strip()}")
    return steps


def uninstall_macos(runtime: str, dry: bool) -> list[str]:
    label = f"{JOB_LABEL}.{runtime}"
    path = _plist_path(runtime)
    steps = [f"launchctl bootout gui/{os.getuid()}/{label}", f"删 {path}"]
    if dry:
        return steps
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"],
                   capture_output=True, text=True)
    path.unlink(missing_ok=True)
    return steps


def _task_xml(cmd: str, hh: int, mm: int) -> str:
    """Windows 计划任务定义。

    电源与补跑三项直接写在 XML 里，不再依赖建完之后那次 PowerShell 改设置：schtasks 建
    的任务默认「仅在交流电源时运行」且不唤醒机器，夜里必然静默漏跑；而如果改设置那一步
    失败，就留下一个看着装好了、实际每夜都不跑的任务。写进 XML 是一次成型。

    `StartBoundary` 的日期取今天——首次触发在今天或明天的该时刻，之后每日重复。
    """
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{today}T{hh:02d}:{mm:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <WakeToRun>true</WakeToRun>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c {_xml(cmd)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _xml(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


# ── Windows · 任务计划程序 ────────────────────────────────────────────────────
def install_windows(runtime: str, hh: int, mm: int, cmd: str, dry: bool) -> list[str]:
    name = f"{JOB_LABEL}.{runtime}"
    # schtasks 建的任务默认「仅在交流电源时运行」且不唤醒机器，夜里必然静默漏跑。
    # 故建完立刻用 PowerShell 改这三项设置——这是 Windows 端最常见的假装装好了。
    fix = (
        f"$s = New-ScheduledTaskSettingsSet "
        f"-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun "
        f"-StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3); "
        f"Set-ScheduledTask -TaskName '{name}' -Settings $s"
    )
    # **打印的命令必须脱敏。** dry-run 全靠这份输出给用户看，而 proof 的全部价值就是
    # 「只存在于 job 定义里」——原样打印等于把它抄进终端回滚缓冲、CI 日志、以及用户
    # 随手贴出来的报错里，泄漏一次这一代就不再能区分自然触发与手工补跑。
    steps = [
        f'schtasks /Create /TN {name} /XML <任务 XML> /F'
        f'（命令：cmd /c {redact(cmd)}，每日 {hh:02d}:{mm:02d}）',
        "PowerShell: 允许电池运行 + 唤醒计算机 + 错过则补跑",
    ]
    if dry:
        return steps
    (Path.home() / ".pgh").mkdir(parents=True, exist_ok=True)
    # 走 `/XML` 而不是 `/TR`：命令里含引号与 `&&`，塞进 `/TR "cmd /c ..."` 需要按
    # cmd.exe 与 schtasks 两层规则转义，任一层弄错都会得到一条**语法上合法但被截断**
    # 的命令——任务建得出来，夜里跑起来只执行前半截，且不报错。XML 有自己的转义规则，
    # 一次 `_xml()` 就够。
    task_xml = _task_xml(cmd, hh, mm)
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".xml", delete=False,
                                encoding="utf-16") as fh:
        fh.write(task_xml)
        xml_path = fh.name
    try:
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", name, "/XML", xml_path, "/F"],
            capture_output=True, text=True)
    finally:
        Path(xml_path).unlink(missing_ok=True)
    if r.returncode != 0:
        raise SystemExit(f"schtasks 建任务失败：{r.stderr.strip() or r.stdout.strip()}")
    r2 = subprocess.run(["powershell", "-NoProfile", "-Command", fix],
                        capture_output=True, text=True)
    if r2.returncode != 0:
        raise SystemExit(
            "任务已建但电源设置未改成功——夜里用电池或机器睡眠时会静默漏跑。"
            f"请手动在任务计划程序里勾选上述三项。原始错误：{r2.stderr.strip()}"
        )
    return steps


def uninstall_windows(runtime: str, dry: bool) -> list[str]:
    name = f"{JOB_LABEL}.{runtime}"
    steps = [f"schtasks /Delete /TN {name} /F"]
    if not dry:
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"],
                       capture_output=True, text=True)
    return steps


# ── Linux · systemd user timer ────────────────────────────────────────────────
def _unit_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def install_linux(runtime: str, hh: int, mm: int, cmd: str, dry: bool) -> list[str]:
    name = f"{JOB_LABEL}.{runtime}".replace(".", "-")
    d = _unit_dir()
    service = f"""[Unit]
Description=PGH daily-dream ({runtime})

[Service]
Type=oneshot
ExecStart=/bin/sh -lc {_q(cmd)}
"""
    # Persistent=true：机器在触发时刻关着，开机后补跑一次。没有它，关机一夜
    # 等于永久丢一天的固化。
    timer = f"""[Unit]
Description=PGH daily-dream timer ({runtime})

[Timer]
OnCalendar=*-*-* {hh:02d}:{mm:02d}:00
Persistent=true

[Install]
WantedBy=timers.target
"""
    steps = [f"写 {d}/{name}.service 与 {name}.timer",
             f"systemctl --user daemon-reload && enable --now {name}.timer"]
    if dry:
        return steps
    d.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".pgh").mkdir(parents=True, exist_ok=True)
    (d / f"{name}.service").write_text(service, encoding="utf-8")
    (d / f"{name}.timer").write_text(timer, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    r = subprocess.run(["systemctl", "--user", "enable", "--now", f"{name}.timer"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"systemctl enable 失败：{r.stderr.strip()}")
    return steps


def uninstall_linux(runtime: str, dry: bool) -> list[str]:
    name = f"{JOB_LABEL}.{runtime}".replace(".", "-")
    d = _unit_dir()
    steps = [f"systemctl --user disable --now {name}.timer", f"删 {d}/{name}.*"]
    if not dry:
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{name}.timer"],
                       capture_output=True, text=True)
        (d / f"{name}.service").unlink(missing_ok=True)
        (d / f"{name}.timer").unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return steps


# ── 派发 ──────────────────────────────────────────────────────────────────────
INSTALLERS = {"Darwin": install_macos, "Windows": install_windows, "Linux": install_linux}
UNINSTALLERS = {"Darwin": uninstall_macos, "Windows": uninstall_windows,
                "Linux": uninstall_linux}


def installed_hour_minute(runtime: str) -> tuple[int, int] | None:
    """读**已安装 job 自己**声明的触发时刻。取不到返回 None。

    computed fallback 不能拿调用参数自行算：若 job 的时间字段其实写错了（模板 bug /
    平台把 `05` 解析成八进制 / 手工改过），用「计划装的时间」算出来的下次触发只是
    把入参回显一遍，是一份自证。必须从落地产物里回读。
    """
    system = platform.system()
    try:
        if system == "Darwin":
            p = _plist_path(runtime)
            if not p.exists():
                return None
            import plistlib
            with p.open("rb") as f:
                data = plistlib.load(f)
            cal = data.get("StartCalendarInterval")
            if isinstance(cal, list):
                cal = cal[0] if cal else None
            if isinstance(cal, dict) and "Hour" in cal and "Minute" in cal:
                return int(cal["Hour"]), int(cal["Minute"])
            return None

        if system == "Windows":
            # 走 `/XML` 而不是 `/V /FO LIST`：后者的字段名是**本地化**的（中文系统上是
            # 「开始时间」，德语系统上又是别的），按英文标签匹配会在非英文机器上恒取不到，
            # 而取不到会被当成「读不到时刻」——一个真实的时间字段写错与语言不对，表现同形。
            xml = _run_capture(["schtasks", "/Query", "/TN",
                                f"{JOB_LABEL}.{runtime}", "/XML"])
            if not xml:
                return None
            m = _re.search(r"<StartBoundary>\s*\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})",
                           xml)
            return (int(m.group(1)), int(m.group(2))) if m else None

        if system == "Linux":
            name = f"{JOB_LABEL}.{runtime}".replace(".", "-")
            unit = Path.home() / ".config" / "systemd" / "user" / f"{name}.timer"
            if not unit.exists():
                return None
            m = _re.search(r"OnCalendar\s*=.*?(\d{1,2}):(\d{2})",
                           unit.read_text(encoding="utf-8"))
            if m:
                return int(m.group(1)), int(m.group(2))
            return None
    except (OSError, ValueError, KeyError, ImportError):
        return None
    return None


def installed_command(runtime: str) -> str | None:
    """读**已安装 job 里那条命令**的原文。取不到返回 None。

    首跑验收要拿它回答两个问题：这个 job 到底调的是不是持久根里的包装器，以及它带的
    generation 还是不是当前那一代。只看 sentinel 不够——sentinel 是过去某一刻写的，
    而 job 可能在那之后被改成指向临时 clone（clone 一删就静默不跑）或被换掉。

    注意 Windows 走 `/XML`、Linux 读 unit 正文，而不是 `/V /FO LIST`：后者会把长命令
    截断，截断后的文本里恰好可能看不到 generation，于是「命令漂移」和「读不全」同形。
    """
    system = platform.system()
    try:
        if system == "Darwin":
            p = _plist_path(runtime)
            if not p.exists():
                return None
            import plistlib
            with p.open("rb") as f:
                data = plistlib.load(f)
            args = data.get("ProgramArguments")
            if isinstance(args, list) and args:
                return str(args[-1])
            return None

        if system == "Windows":
            xml = _run_capture(["schtasks", "/Query", "/TN",
                                f"{JOB_LABEL}.{runtime}", "/XML"])
            if not xml:
                return None
            m = _re.search(r"<Arguments>(.*?)</Arguments>", xml, _re.DOTALL)
            if not m:
                m = _re.search(r"<Command>(.*?)</Command>", xml, _re.DOTALL)
            return m.group(1) if m else None

        if system == "Linux":
            name = f"{JOB_LABEL}.{runtime}".replace(".", "-")
            svc = _unit_dir() / f"{name}.service"
            if not svc.exists():
                return None
            m = _re.search(r"ExecStart\s*=\s*(.+)", svc.read_text(encoding="utf-8"))
            return m.group(1).strip() if m else None
    except (OSError, ValueError, KeyError, ImportError):
        return None
    return None


def installed_proof(runtime: str) -> tuple[str | None, str | None]:
    """从已安装 job 的命令里取出 proof 与 generation。取不到返回 `(None, None)`。

    验收器需要真的 proof 才能复算 sentinel 的 MAC。而 proof 只存在于 job 定义里——
    这正是它作为凭据的全部价值：收据里只有 hash，抄收据抄不出它。

    两种形状都要认：POSIX 的 `VAR='v'` 与 cmd.exe 的 `set "VAR=v"`。只认一种会让另一个
    平台上的验收恒红，而恒红与恒绿一样没有信息量。
    """
    cmd = installed_command(runtime)
    if not cmd:
        return None, None

    return _grab_env(cmd, PROOF_ENV), _grab_env(cmd, GEN_ENV)


def _grab_env(cmd: str, name: str) -> str | None:
    """从已安装的 job 命令原文里抠出某个环境变量的值。

    两种形状都要认：POSIX 的 `VAR='v'` 与 cmd.exe 的 `set "VAR=v"`。只认一种会让另一个
    平台上的验收恒红，而恒红与恒绿一样没有信息量。
    """
    for pat in (rf'set\s+"{name}=([^"]*)"',          # cmd.exe
                rf"{name}='([^']*)'",                 # POSIX 单引号
                rf'{name}="([^"]*)"',                 # POSIX 双引号
                rf'{name}=([^\s"\']+)'):              # 裸值
        m = _re.search(pat, cmd)
        if m:
            return m.group(1)
    return None


def installed_sched_time(runtime: str) -> str | None:
    """从已安装 job 的命令里取名义触发时刻（`HH:MM`）。取不到返回 `None`。

    验收器用它交叉核对 sentinel 里的 `scheduled_at`：那个字段声称「这趟是排程到点
    触发的」，而「到点」是哪个点只有 job 定义说得准。
    """
    cmd = installed_command(runtime)
    return _grab_env(cmd, SCHED_TIME_ENV) if cmd else None


def _seal_next_run(ev: dict, enabled: bool,
                   hh: int | None, mm: int | None) -> bool:
    """把「下次触发」这件证据补齐并给出最终通过判定。

    规格要求 enabled + next run **两件都有**。平台没自述下次触发时刻时，用已安装的
    Hour/Minute 加本机 IANA 时区机械算一个，并标 `computed` 以便与平台自述区分。
    时区取不到 IANA 名时不算：那时算出来的时刻可能差好几个小时（`CST` 既是 +08 也是
    −06），一个错的确定值比一个显式的「不知道」更坏。
    """
    ev["enabled"] = enabled
    if not enabled:
        return False

    # 先回读 job 自己声明的时刻，并与入参交叉核对。核不上就是 job 写错了——那时
    # 「装上了」不该算通过，因为它会在错误的时刻跑（或永不跑）。
    got = installed_hour_minute(ev.get("runtime", ""))
    if got is not None:
        ev["installed_hour_minute"] = f"{got[0]:02d}:{got[1]:02d}"
        if hh is not None and mm is not None and got != (hh, mm):
            ev["next_run_source"] = (
                f"job 回读时刻 {got[0]:02d}:{got[1]:02d} 与请求 "
                f"{hh:02d}:{mm:02d} 不符——job 时间字段写错了")
            return False

    if ev.get("next_run"):
        return True

    iana, tz_src = resolve_iana_tz(ev.get("timezone_iana_requested"))
    ev["timezone_iana"] = iana
    # 机械推算一律用**回读到的** job 时刻；回读不到才退回入参，并在来源里标明，
    # 因为那一份是自证强度更低的证据。
    src_h, src_m = (got if got is not None else (hh, mm))
    basis = "job 回读" if got is not None else "调用入参（未能回读 job，自证强度较低）"
    if src_h is None or src_m is None or iana == TZ_UNRESOLVED:
        ev["next_run_source"] = (
            f"取不到：平台未自述，且无法机械推算（时区={iana}，来源={tz_src}）。"
            "传 --timezone <IANA> 可补齐。")
        return False
    try:
        tz = ZoneInfo(iana)
    except Exception as e:                                  # noqa: BLE001
        ev["next_run_source"] = f"取不到：ZoneInfo({iana}) 失败 · {e}"
        return False
    now = datetime.now(tz)
    nxt = now.replace(hour=src_h, minute=src_m, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    ev["next_run"] = nxt.isoformat(timespec="seconds")
    ev["next_run_source"] = (
        f"computed（{basis} {src_h:02d}:{src_m:02d} + {iana}，时区来源={tz_src}）")
    return True


def verify(runtime: str, hh: int | None = None, mm: int | None = None,
           tz_name: str | None = None) -> tuple[bool, str, dict]:
    """装完回查。返回 (是否通过, 人读说明, 证据字典)。

    收据只能证明「装上了」。要证明「会按预期时刻跑」需**两件**证据：**enabled 状态**
    与 **下次触发时刻**，两件都得有。早先只要 `launchctl list` 命中就算过——而
    `launchctl print` 抓不到 `next fire` 时照样进 READY，于是「装上但永不触发」
    （时刻字段写坏 / job 被 disable）会被报成就绪。

    抓不到平台给的下次触发时刻时不直接判失败：用已安装的 Hour/Minute 加 IANA 时区
    机械算出下次触发，标为 `computed` 并记下算法来源。这条路径下证据仍算齐，但它是
    推算而非平台自述，故在收据里可区分。两条路都拿不到才判非 READY。

    真正跑成功的证据只能来自第一次自然运行——见 `first_run_sentinel()`。
    """
    system = platform.system()
    label = f"{JOB_LABEL}.{runtime}"
    ev: dict = {"probe_platform": system, "label": label, "runtime": runtime,
                "timezone_iana_requested": tz_name}

    if system == "Darwin":
        out = _run_capture(["launchctl", "list"])
        if out is None:
            return False, "launchctl list 读取失败", ev
        listed = label in out
        ev["listed"] = listed
        detail = _run_capture(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
        if detail:
            for line in detail.splitlines():
                s = line.strip()
                if s.startswith("next fire"):          # `next fire: ...`
                    ev["next_run"] = s
                    ev["next_run_source"] = "launchctl print"
                elif s.startswith("state ="):
                    ev["state"] = s
        ok = _seal_next_run(ev, listed, hh, mm)
        return ok, (f"launchctl list {'命中' if listed else '未命中'} {label}"
                    f"；下次触发={ev.get('next_run', '取不到')}"), ev

    if system == "Windows":
        # 启用态取自 Task XML 的 `<Enabled>`——与时刻同理，`/V /FO LIST` 的标签会随系统
        # 语言变，按英文标签判「是否 disabled」在中文系统上永远判成启用。
        xml = _run_capture(["schtasks", "/Query", "/TN", label, "/XML"])
        ev["listed"] = xml is not None
        if xml:
            m = _re.search(r"<Enabled>\s*(true|false)\s*</Enabled>", xml, _re.I)
            ev["state"] = (m.group(1).lower() if m else "unknown")
            ev["state_source"] = "schtasks /XML <Enabled>"
        # 下次触发时刻只有 `/V` 会给，故仍读它，但**不用它判启用态**。
        out = _run_capture(["schtasks", "/Query", "/TN", label, "/V", "/FO", "LIST"])
        if out:
            m = _re.search(r"^[^\n:]*:\s*(\d{1,2}/\d{1,2}/\d{2,4}[^\n]*)$",
                           out, _re.M)
            if m:
                ev["next_run"] = m.group(1).strip()
                ev["next_run_source"] = "schtasks /Query /V"
        enabled = bool(xml) and ev.get("state") != "false"
        ok = _seal_next_run(ev, enabled, hh, mm)
        return ok, (f"schtasks /Query {'命中' if out else '未命中'}"
                    f"；state={ev.get('state')}"
                    f"；下次触发={ev.get('next_run', '取不到')}"), ev

    if system == "Linux":
        name = label.replace(".", "-")
        en = _run_capture(["systemctl", "--user", "is-enabled", f"{name}.timer"])
        ev["state"] = (en or "").strip() or "failed"
        nxt = _run_capture(["systemctl", "--user", "list-timers", f"{name}.timer",
                            "--no-pager", "--no-legend"])
        if nxt and nxt.strip():
            ev["next_run"] = nxt.strip().splitlines()[0]
            ev["next_run_source"] = "systemctl list-timers"
        enabled = en is not None and "enabled" in en
        ok = _seal_next_run(ev, enabled, hh, mm)
        return ok, (f"systemctl is-enabled → {ev['state']}"
                    f"；下次触发={ev.get('next_run', '取不到')}"), ev

    return False, f"平台 {system} 无回查实现", ev


#: 时区取不到 IANA 名时写进收据的值。必须是显式标记而不是缩写——见 `resolve_iana_tz`。
TZ_UNRESOLVED = "UNRESOLVED"


def resolve_iana_tz(explicit: str | None = None) -> tuple[str, str]:
    """求本机 IANA 时区名。返回 `(名字或 UNRESOLVED, 证据来源)`。

    `explicit` 是部署访谈拿到的权威输入（`--timezone`），优先于一切自动探测。
    Windows 既没有 `/etc/localtime` 符号链接也没有 `timedatectl`，自动探测在那里
    **恒为 UNRESOLVED**——若只靠探测，Windows 部署者永远拿不到 READY。故把访谈
    输入设为权威通道，探测只作默认候选。

    **不能用 `datetime.now().astimezone().tzinfo`**：实测（2026-08-01，macOS 25.5）
    它只给 `CST`，而 `CST` 同时是 China Standard Time (+08) 和 US Central Standard
    Time (−06) 的缩写——把它当 IANA 名写进收据，等于把一个歧义字符串当成了精确证据。
    下次触发时刻的机械核算要靠时区，算错六个小时不会有任何报错。

    故按可信度依次取：`TZ` 环境变量 → `/etc/localtime` 符号链接指向的 zoneinfo 路径
    （macOS / 多数 Linux）→ `timedatectl`（systemd）。全都取不到就返回 `UNRESOLVED`，
    由调用方降级为非 READY；宁可显式说不知道，也不要拿缩写充数。
    """
    if explicit:
        name = explicit.strip()
        try:
            ZoneInfo(name)              # 校验：拼错的名字必须当场拒绝，不写进收据
        except Exception as e:          # noqa: BLE001
            raise SystemExit(
                f"--timezone {name!r} 不是有效的 IANA 时区名（{e}）。"
                "形如 Asia/Shanghai / Europe/London / America/New_York。")
        return name, "--timezone（部署访谈输入）"

    env = os.environ.get("TZ", "").strip()
    if "/" in env:                      # `Asia/Shanghai` 形状才算 IANA 名
        return env, "TZ 环境变量"

    lt = Path("/etc/localtime")
    if lt.is_symlink() or lt.exists():
        try:
            parts = lt.resolve().parts
            if "zoneinfo" in parts:
                idx = len(parts) - 1 - parts[::-1].index("zoneinfo")
                name = "/".join(parts[idx + 1:])
                if "/" in name:
                    return name, "/etc/localtime → zoneinfo"
        except OSError:
            pass

    out = _run_capture(["timedatectl", "show", "-p", "Timezone", "--value"])
    if out and "/" in out.strip():
        return out.strip(), "timedatectl"

    return TZ_UNRESOLVED, "取不到 IANA 名（不接受缩写代替）"


def first_run_sentinel(runtime: str, hh: int, mm: int,
                       tz_name: str | None = None) -> dict:
    """首次自然运行的验收哨兵——写进收据，等第一次真跑之后由人或 week-sync 核。

    装好 ≠ 跑过。周日的 weekly-dream 分支更是要等到第一个周日才有可执行证据。故
    收据里显式留两个待验字段，而不是让「INSTALL OK」被读成「已经在跑了」。
    """
    iana, tz_src = resolve_iana_tz(tz_name)
    # 跨 DST 推算必须用 ZoneInfo，不能用 `astimezone()` 拿到的固定 offset：那是一个
    # 死掉的偏移量，跨过夏令时切换后算出的时刻会差一小时，而排程本身是按本地墙钟
    # 触发的。拿不到 IANA 名时退回本机 offset，并在收据里已标 UNRESOLVED。
    now = datetime.now(ZoneInfo(iana)) if iana != TZ_UNRESOLVED \
        else datetime.now().astimezone()
    first = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if first <= now:
        first += timedelta(days=1)
    # 第一个周日：weekly-dream 周段只在目标逻辑日为周日时跑，故它的首次可执行
    # 证据最晚要等到下一个周一凌晨那趟（目标日 = 周日）。
    first_weekly = first
    while first_weekly.weekday() != 0:       # 0 = 周一，其目标日是周日
        first_weekly += timedelta(days=1)
    return {
        "timezone_iana": iana,
        "timezone_source": tz_src,
        # 缩写单独存字段并显式标注，不冒充 IANA 名。
        "timezone_abbrev": str(now.tzinfo),
        "utc_offset": now.strftime("%z"),
        "expected_first_run": first.isoformat(timespec="seconds"),
        "expected_first_weekly_run": first_weekly.isoformat(timespec="seconds"),
        "first_run_verified": False,
        "first_weekly_run_verified": False,
        "how_to_verify": (
            "首跑之后核三件：MEMORY_LOG 有目标日条目、last_dream.md 是目标日、"
            f"日志 {log_path(runtime)} 有该趟输出。"
            "周段另核当周归档与周录本周节。核过后把对应 *_verified 改 true。"
            "验收器同时回填 first_run_natural_scheduled_at（job 声明的名义触发时刻）"
            "与 first_run_natural_fired_at（实际开跑墙钟），周段同理；"
            "两者在唤醒补触发时会不同，都要留。"
        ),
    }


def write_receipt(payload: dict, runtime: str) -> None:
    path = receipt_path(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 把日界线写进正文 ──────────────────────────────────────────────────────────
# 日界线在两处被引用：宪法层的口径行、记忆区 canon 的 §逻辑日期。两处必须同数，
# 否则日期判断按读到哪份而变。交给 AI 手改必漏一处，故机械替换。

# 口径行的两个半句都带小时数：`物理 hour < 06:00 → … − 1；≥ 06:00 → 同物理日期`。
# 只替前半句会留下自相矛盾的一行（< 04:00 却 ≥ 06:00），且这种文本没有任何检查
# 会报错——读到它的 agent 只会在 04:00-06:00 之间给出随机答案。故整行一起替。
BOUNDARY_LINE_RE = _re.compile(
    r"(物理\s*hour\s*<\s*)(\d{2})(:00\s*→\s*逻辑日期\s*=\s*物理日期\s*[−\-]\s*1；"
    r"\s*≥\s*)(\d{2})(:00)"
)
BOUNDARY_ANY_RE = _re.compile(r"物理\s*hour\s*<\s*(\d{2}):00")


def patch_boundary(files: list[Path], boundary_h: int, dry: bool,
                   required: bool = True) -> tuple[list[str], list[str]]:
    """把日界线写进各引用点。返回 (notes, failures)。

    `failures` 非空 = 有**必须命中**的落点没能写上。调用方必须据此让安装失败并
    回滚——排程按新日界线跑，而正文里的口径还是旧值时，排程与逻辑日判定各说一套，
    每天都有一段工作被归错日子，且没有任何运行时报错。
    """
    notes: list[str] = []
    failures: list[str] = []
    b = f"{boundary_h:02d}"

    def bad(msg: str) -> None:
        notes.append(msg)
        if required:
            failures.append(msg)

    for f in files:
        if not f.exists():
            bad(f"落点不存在：{f}")
            continue
        text = f.read_text(encoding="utf-8")
        pairs = BOUNDARY_LINE_RE.findall(text)
        if not pairs:
            # 整行没匹配上但出现了 `物理 hour <` = 口径行被改写过，形状不认识。
            # 这时宁可不动并让安装失败，也不要只替半句造出矛盾行。
            loose = BOUNDARY_ANY_RE.findall(text)
            if loose:
                bad(f"口径行形状不认识（{len(loose)} 处 `物理 hour <` 但整行不匹配），"
                    f"未改动：{f}")
            else:
                bad(f"未找到日界线口径行：{f}")
            continue
        olds = sorted({h for pair in pairs for h in pair[1::2]})
        if olds == [b]:
            notes.append(f"已是 {b}:00，无需改：{f.name}")
            continue
        if not dry:
            f.write_text(BOUNDARY_LINE_RE.sub(rf"\g<1>{b}\g<3>{b}\g<5>", text),
                         encoding="utf-8")
        notes.append(f"{f.name}：{olds} → {b}:00（{len(pairs)} 行，各两处）")
    return notes, failures


#: 记忆区 canon 的候选文件名，**按优先级排列**。首位是现行规范名；其后是历史命名，
#: 保留只为让老部署仍能被正确改写，不作为新仓的推荐名。
MEMORY_CANON_NAMES = ("00.memory_agent.md", "00.记忆区_agent.md")


def boundary_targets(assistant_root: Path, runtime: str,
                     config_file: Path | None = None,
                     ) -> tuple[list[Path], list[Path]]:
    """日界线口径的两类落点：(必须命中, 可选命中)。

    两个根必须分清，否则路径会拼错：
      * **repo root** —— 仓库/ 部署包目录，装着 `.claude/` 或 `.codex/`。
      * **assistant root** —— 用户内容目录，装着 `MEMORY/` `USER/` `00 Focus Zone/`。

    发布包里 assistant root 是 repo root 下的 `assistant/`；部署到本机后用户可以
    把它放在任何地方（`<ASSISTANT_ROOT>` 占位符就是为此存在）。早先本函数拿一个
    `workdir` 同时当两个根用，于是在「assistant root 已被指到别处」的真实部署里
    拼出 `<ASSISTANT_ROOT>/assistant/MEMORY/...` 这种不存在的路径，而当时的实现
    只把它记成一条 note，安装照样报成功。

    故现在只收 assistant root，repo root 由它反推（`<repo>/assistant` 布局）或退回
    本机 `~`。必须命中的是记忆区 canon 与宪法层各一份；找不到即安装失败（见 #3）。

    记忆区 canon 的文件名按 `MEMORY_CANON_NAMES` 逐个探，取第一个存在的。旧仓与旧
    部署用过中文名，取不到就会以「必须落点缺失」中止安装——而那是个纯命名差异，
    不是真缺口径行。都不存在时回落到首选名，让报错指向应该建的那个。
    """
    cfg = ".claude/CLAUDE.md" if runtime == "claude" else ".codex/AGENTS.md"
    memory_dir = assistant_root / "MEMORY"
    memory_canon = next(
        (memory_dir / n for n in MEMORY_CANON_NAMES if (memory_dir / n).exists()),
        memory_dir / MEMORY_CANON_NAMES[0],
    )

    if config_file is not None:
        return [memory_canon, config_file.expanduser().resolve()], []

    # 发布包布局：assistant root 的父目录就是 repo root。
    packaged_cfg = assistant_root.parent / cfg
    # 已部署布局：宪法层在本机 home 下。
    installed_cfg = Path.home() / cfg

    # **只取一份宪法层。** 两份都存在时它们可能属于不同的安装（部署包 vs 本机已有
    # 的另一套），把两份都当必须落点会因为无关的那份不匹配而误判失败。故按「离
    # assistant root 更近的那份是本次操作对象」取包内那份优先，包内没有才用本机的。
    if packaged_cfg.exists():
        chosen = packaged_cfg
    elif installed_cfg.exists():
        chosen = installed_cfg
    else:
        chosen = packaged_cfg          # 都不在：报缺失时给出包内路径，指向更有用
    return [memory_canon, chosen], []


# ── 主入口 ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="PGH 部署期排程器")
    ap.add_argument("--runtime", choices=["claude", "codex"], help="被排的 CLI")
    ap.add_argument("--sleep", help="通常几点睡，HH:MM")
    ap.add_argument("--wake", help="通常几点起，HH:MM")
    ap.add_argument("--boundary-hour", type=int,
                    help="直接指定日界线整点，跳过由作息推算")
    ap.add_argument("--assistant-root", default=None,
                    help="用户内容目录（装着 MEMORY/ USER/ 00 Focus Zone/）。"
                         "任务的工作目录与日界线落点都由它定。默认 ./assistant，"
                         "不存在时退回当前目录。")
    ap.add_argument("--workdir", default=None,
                    help="已废弃：请用 --assistant-root。仍接受以兼容旧调用。")
    ap.add_argument("--config-file", default=None,
                    help="宪法层文件（Claude 的 CLAUDE.md / Codex 的 AGENTS.md）。"
                         "两套安装并存、自动推断会取错时用它显式指定。")
    ap.add_argument("--shutdown-after", action="store_true",
                    help="任务成功收尾后关机")
    ap.add_argument("--timezone", default=None,
                    help="本机 IANA 时区名（如 Asia/Shanghai）。部署访谈问到时区就"
                         "传进来——Windows 上自动探测拿不到 IANA 名，不传会一直非 READY。")
    ap.add_argument("--check-power", action="store_true", help="只探供电，不装")
    ap.add_argument("--smoke", action="store_true",
                    help="装完真调一次 headless CLI 验证调用形式可跑（约 1 分钟）。"
                         "推荐在部署时开——它是「排程会跑成功」的唯一实证。")
    ap.add_argument("--smoke-only", action="store_true",
                    help="只跑 headless 实跑验证，不装排程、不改正文")
    ap.add_argument("--uninstall", action="store_true", help="卸载排程")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做什么")
    a = ap.parse_args()

    system = platform.system()

    if a.check_power:
        ok, notes = check_power()
        print(f"POWER {'READY' if ok else 'NEEDS-ATTENTION'} · {system}")
        for n in notes:
            print(f"  - {n}")
        return 0 if ok else 1

    if not a.runtime:
        ap.error("--runtime 必填（除 --check-power 外）")

    # **纯输入校验全部前置到第一次 mutation 之前。**
    # `--timezone` 早先是在 `verify()` / `first_run_sentinel()` 里才校验的，而那两个
    # 调用发生在正文已 patch、job 已装上之后：拼错一个时区名会抛 SystemExit，留下
    # 「按新日界线改过的正文 + 一个 ACTIVE job + 没有收据」。参数拼错本该零副作用。
    if a.timezone:
        try:
            ZoneInfo(a.timezone.strip())
        except Exception as e:                                   # noqa: BLE001
            print(f"--timezone {a.timezone!r} 不是有效的 IANA 时区名（{e}）。"
                  "形如 Asia/Shanghai / Europe/London / America/New_York。",
                  file=sys.stderr)
            return 2

    if a.smoke_only:
        ok, msg = smoke_run(a.runtime, Path.cwd())
        print(f"SMOKE {'PASS' if ok else 'FAIL'} runtime={a.runtime} · {msg}")
        return 0 if ok else 1

    if a.uninstall:
        fn = UNINSTALLERS.get(system)
        if fn is None:
            print(f"平台 {system} 无卸载实现", file=sys.stderr)
            return 2
        for s in fn(a.runtime, a.dry_run):
            print(f"  {s}")
        if not a.dry_run:
            # 只删本 runtime 的收据——另一端的验收状态与它无关。
            receipt_path(a.runtime).unlink(missing_ok=True)
        print(f"UNINSTALL {'DRY-RUN' if a.dry_run else 'DONE'} runtime={a.runtime}")
        return 0

    # 日界线
    if a.boundary_hour is not None:
        if not (BOUNDARY_MIN_H <= a.boundary_hour <= BOUNDARY_MAX_H):
            print(f"--boundary-hour 需在 {BOUNDARY_MIN_H}..{BOUNDARY_MAX_H} 之间",
                  file=sys.stderr)
            return 2
        boundary_h, why = a.boundary_hour, "由 --boundary-hour 显式指定"
    else:
        if not (a.sleep and a.wake):
            ap.error("需要 --sleep 与 --wake（或用 --boundary-hour 直接指定）")
        boundary_h, why = derive_boundary(parse_hhmm(a.sleep, "--sleep"),
                                          parse_hhmm(a.wake, "--wake"))
    hh, mm = dream_time(boundary_h)

    raw_root = a.assistant_root or a.workdir
    if raw_root is None:
        guess = Path.cwd() / "assistant"
        raw_root = str(guess if guess.is_dir() else Path.cwd())
    assistant_root = Path(raw_root).expanduser().resolve()
    if not assistant_root.is_dir():
        print(f"assistant 根不存在：{assistant_root}", file=sys.stderr)
        return 2

    # **先取快照，再复制。** 顺序反了拿到的是新内容，回滚就成了把新脚本再写一遍。
    scripts_snap = None if a.dry_run else snapshot_scripts(a.runtime)
    scripts_touched = {"v": False}

    # 先把脚本落到持久根，再据此拼命令——顺序反了 wrapper_path() 会解析到源目录。
    scripts_dir, script_notes = install_runtime_scripts(a.runtime, a.dry_run)
    if not a.dry_run:
        scripts_touched["v"] = True
    print(f"排程脚本持久副本 {scripts_dir}：")
    for n in script_notes:
        print(f"  - {n}")

    # 每次安装 / 重装都换一对 (generation, proof)。换 generation 的作用是让**旧
    # sentinel 自动失效**：重装意味着 job 被重写过，之前那趟自然运行证明的是旧 job 的
    # 状态，不能拿来给新 job 的验收充数。
    generation = new_generation()
    proof = new_proof()
    cmd = scheduled_cmd(a.runtime, assistant_root, a.shutdown_after,
                        allow_missing_exe=a.dry_run,
                        proof=proof, generation=generation,
                        sched_time=f"{hh:02d}:{mm:02d}")

    print(f"日界线 {boundary_h:02d}:00（{why}）")
    print(f"固化时刻 {hh:02d}:{mm:02d}（日界线 + {DREAM_OFFSET_MIN} 分钟）")
    print(f"assistant 根 {assistant_root}")
    print(f"关机 {'开' if a.shutdown_after else '关'}")

    pok, pnotes = check_power()
    print(f"供电 {'READY' if pok else 'NEEDS-ATTENTION'}")
    for n in pnotes:
        print(f"  - {n}")

    sd_ok, sd_note = (True, "未启用")
    if a.shutdown_after:
        sd_ok, sd_note = shutdown_ready()
        print(f"关机 {'READY' if sd_ok else 'NOT-AVAILABLE'}")
        print(f"  - {sd_note}")

    fn = INSTALLERS.get(system)
    if fn is None:
        print(f"平台 {system} 无安装实现，请手动排程", file=sys.stderr)
        return 2

    # 顺序是刻意的：**先落正文，再装排程。** 反过来（先装后落）会在正文落盘失败时
    # 留下一个按新日界线跑、而口径还是旧值的排程——两边各说一套，每天归错日子且
    # 无运行时报错。先落正文则失败时什么都还没装，天然无残留。
    print("日界线口径落正文：")
    cfg_override = Path(a.config_file).expanduser() if a.config_file else None
    required, optional = boundary_targets(assistant_root, a.runtime, cfg_override)

    # 事务回滚的前提：先把要改的文件原文存下来。
    # 「先落正文再装 job」解决了「装了 job 但正文没落」，但反向仍是断的——正文落好、
    # installer/bootstrap 却失败时，会留下按新日界线写的正文而没有排程。那时用户以为
    # 日界线改了，实际没有任何东西会在那个时刻跑。故失败要把正文恢复原状。
    backups: dict[Path, str] = {}
    if not a.dry_run:
        for f in list(required) + list(optional):
            if f.exists():
                try:
                    backups[f] = f.read_text(encoding="utf-8")
                except OSError as e:
                    print(f"无法备份 {f}（{e}）——不做无法回滚的改动", file=sys.stderr)
                    return 1

    # 旧 job 快照。重装场景下 installer 会先 bootout 旧 job 才能重新 bootstrap，
    # 此时失败就把一个本来健康的排程卸掉了——正文回滚救不了它。
    job_snap = None if a.dry_run else snapshot_job(a.runtime)
    # 用可变容器而不是裸布尔：rollback 是闭包，裸布尔在函数体里赋值会被当成局部变量，
    # 闭包读到的永远是初始值 False，于是 job 永远不回滚。
    job_touched = {"v": False}

    def rollback(reason: str) -> None:
        """把正文、job 与持久脚本一起恢复到安装前，并说明为什么。"""
        if job_touched["v"]:
            print(f"job 回滚：{restore_job(a.runtime, job_snap)}", file=sys.stderr)
        if scripts_touched["v"]:
            print(f"脚本回滚：{restore_scripts(a.runtime, scripts_snap)}", file=sys.stderr)
        if not backups:
            return
        restored, failed = [], []
        for f, body in backups.items():
            try:
                f.write_text(body, encoding="utf-8")
                restored.append(f.name)
            except OSError as e:                             # noqa: PERF203
                failed.append(f"{f}（{e}）")
        print(f"已回滚日界线正文（{reason}）：{', '.join(restored)}", file=sys.stderr)
        if failed:
            print(f"**回滚失败**，请手工核对：{'; '.join(failed)}", file=sys.stderr)

    patch_notes, patch_fail = patch_boundary(required, boundary_h, a.dry_run,
                                            required=True)
    opt_notes, _ = patch_boundary(optional, boundary_h, a.dry_run, required=False)
    patch_notes += opt_notes
    for n in patch_notes:
        print(f"  - {n}")

    if patch_fail:
        print("INSTALL ABORTED — 日界线口径未能落到全部必须落点，排程未安装。",
              file=sys.stderr)
        print("排程与逻辑日口径不一致会让每天都有一段工作被归错日子，且不报错，"
              "故这里选择不装而不是装个半成品。", file=sys.stderr)
        for n in patch_fail:
            print(f"  ✗ {n}", file=sys.stderr)
        print("修法：确认 --assistant-root 指到装着 MEMORY/ 的那个目录；"
              "或手工把口径行改成标准形状后重跑。", file=sys.stderr)
        rollback("必须落点未全部写上")
        return 1

    # **smoke 在启用 job 之前跑。** 顺序理由：headless 跑不通时若 job 已启用，就留下
    # 一个每夜必失败的排程，而失败在夜里没人看着。先证明调用形状能跑，再把它排上。
    smoke_ok, smoke_msg = (None, "未跑（加 --smoke 开）")
    if a.smoke and not a.dry_run:
        smoke_ok, smoke_msg = smoke_run(a.runtime, assistant_root)
        print(f"headless 实跑 {'PASS' if smoke_ok else 'FAIL'}：{smoke_msg}")
        if not smoke_ok:
            print("INSTALL ABORTED — headless 调用跑不通，未启用排程。",
                  file=sys.stderr)
            print("启用了只会每夜失败一次，且没人在场看到。先修 CLI 登录 / 参数，"
                  "再重跑同一条命令（幂等）。", file=sys.stderr)
            rollback("headless 实跑失败")
            return 1

    # 安装器失败一律走 SystemExit（launchctl bootstrap / schtasks / systemctl 非 0）。
    # 不接住的话正文已经按新日界线改过、排程却没装上，而进程直接退出——留下的正是
    # 「以为改了作息、实际没有任何东西会跑」那个状态。接住 → 回滚 → 再报错。
    try:
        job_touched["v"] = True  # 从这里起 job 状态可能已被改动（bootout 先于 bootstrap）
        for s in fn(a.runtime, hh, mm, cmd, a.dry_run):
            print(f"  {s}")
    except SystemExit as e:
        rollback(f"排程安装失败：{e}")
        print(f"INSTALL ABORTED — {e}", file=sys.stderr)
        print("正文已恢复到安装前，可修好原因后重跑同一条命令（幂等）。",
              file=sys.stderr)
        return 1

    if a.dry_run:
        print("INSTALL DRY-RUN（未落地）")
        return 0

    # 回查传的是**请求装的**时刻，由 verify 内部回读 job 实际时刻并交叉核对；
    # 两者不符即判非通过（job 时间字段写错，会在错误时刻跑或永不跑）。
    vok, vmsg, vev = verify(a.runtime, hh, mm, a.timezone)

    # 回查不过 = 这次安装没成立，故走事务回滚，不留 ACTIVE job。
    # 早先是「写 INSTALL_UNVERIFIED 收据 + return 1」，但 job 和改过的正文都留在原地：
    # 回查不过的两种成因（时刻字段写坏 / job 没真正启用）都会让它在错误时刻跑或永不
    # 跑，而正文已经按新日界线改过。留着的是一个「没人知道它会不会跑」的中间态。
    if not vok:
        print(f"回查：{vmsg}", file=sys.stderr)
        print("INSTALL FAILED — 排程装上了但回查不通过，按事务回滚（不留 ACTIVE job）",
              file=sys.stderr)
        rollback(f"回查未通过：{vmsg}")
        print("修法：核对上面的证据，修好后重跑同一条命令（幂等）。", file=sys.stderr)
        return 1

    sentinel = first_run_sentinel(a.runtime, hh, mm, a.timezone)

    # state 是给人和给 week-sync 读的单一结论字段：READY 才等于「今晚会跑」。
    # 这里不再有 `smoke_ok is False` 与 `not vok` 两支：两者都在写收据之前就回滚并
    # return 1 了。留着等于留两条永远走不到的路，读代码的人会以为「失败也会装上、
    # 只是标个状态」，而实际行为是不装。
    if smoke_ok is None:
        # 没跑 smoke 就不能叫 READY。`--dry-run` 之外，「CLI 能被真调起来」是唯一
        # 无法从静态检查推出的性质：未登录 / 参数被上游改名 / 权限模式被拒，全都只
        # 在真跑时现形，而排程的真跑在夜里没人看着。
        state = "INSTALLED_SMOKE_NOT_RUN"
    elif not pok:
        state = "INSTALLED_POWER_NOT_READY"
    elif a.shutdown_after and not sd_ok:
        state = "INSTALLED_SHUTDOWN_UNAVAILABLE"
    else:
        state = "READY"

    write_receipt(runtime=a.runtime, payload={
        "state": state,
        "runtime": a.runtime, "platform": system,
        "boundary_hour": boundary_h, "boundary_reason": why,
        "dream_time": f"{hh:02d}:{mm:02d}",
        # **IANA 时区名的单一权威落点在顶层。** 早先它只存在 `acceptance` 嵌套里，而
        # 消费方（验收器、Codex 抽取器）读的都是顶层——于是取到 `None`，双双退回各自
        # 的默认值：验收器不传时区给回查，抽取器按 `Asia/Shanghai` 切抽取窗口。对不在
        # 那个时区的部署者，这会让每天的转写窗口整体偏移几个小时，而收据、日志、job
        # 定义全都正常，故偏移在任何一处产物上都看不出来。
        # `acceptance.timezone_iana` 同时保留：已装机器的收据是旧结构，消费方要能读。
        "timezone_iana": sentinel["timezone_iana"],
        "timezone_source": sentinel["timezone_source"],
        "assistant_root": str(assistant_root),
        "shutdown_after": a.shutdown_after,
        "shutdown_ready": sd_ok, "shutdown_note": sd_note,
        "power_ready": pok, "power_notes": pnotes,
        "boundary_patch": patch_notes,
        "boundary_targets_required": [str(p) for p in required],
        "verified": vok, "verify_detail": vmsg, "verify_evidence": vev,
        "headless_smoke": smoke_ok, "headless_smoke_detail": smoke_msg,
        # 走包装器 = 自然运行会留结构化 sentinel，首跑验收才有「排程真触发过」的
        # 证据。降级为直调 CLI 时这里显式记下来，验收器会据此说明它验不了自然触发。
        "scheduled_via": ("wrapper" if wrapper_path(a.runtime).exists() else "direct-cli"),
        "wrapper_path": str(wrapper_path(a.runtime)),
        "natural_run_sentinel": str(PGH_DIR / f"natural_runs.{a.runtime}.jsonl"),
        # 只存 generation 与 hash，**不存 proof 本身**。存了就等于把凭据副本放在
        # 一个手工补跑也能读到的文件里，proof 立刻失去区分能力。
        "job_generation": generation,
        "scheduler_proof_sha256": proof_hash(proof, generation),
        "acceptance": sentinel,
        "installed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    print(f"回查：{vmsg}")
    if vev.get("next_run"):
        print(f"下次触发：{vev['next_run']}")
    print(f"时区：{sentinel['timezone_iana']} ({sentinel['utc_offset']}"
          f"，缩写 {sentinel['timezone_abbrev']}，来源 {sentinel['timezone_source']})")
    print(f"首跑待验：{sentinel['expected_first_run']}"
          f"；周段首跑待验：{sentinel['expected_first_weekly_run']}")
    print(f"收据 {receipt_path(a.runtime)} · state={state}")

    if state != "READY":
        # 不说 OK。装上了但不会按预期跑，是一个需要人做一件具体事才能转 READY 的
        # 中间态，故显式命名它并给出复位动作。
        print(f"INSTALL INCOMPLETE state={state} runtime={a.runtime} "
              f"at {hh:02d}:{mm:02d} daily", file=sys.stderr)
        if not pok:
            print("  待办：按上面的电源提示把接通电源时的睡眠设为「永不」。",
                  file=sys.stderr)
        if a.shutdown_after and not sd_ok:
            print("  待办：配免密 sudo，或去掉 --shutdown-after 重跑（本脚本幂等）。",
                  file=sys.stderr)
        if smoke_ok is None:
            print("  待办：没做 headless 实跑验证。加 `--smoke` 重跑（或单独 "
                  "`--smoke-only`）——它是「排程会跑成功」的唯一实证。",
                  file=sys.stderr)
        print("  复位：处理完重跑同一条命令即可，state 会转 READY。", file=sys.stderr)
        return 1

    print(f"INSTALL OK state=READY runtime={a.runtime} at {hh:02d}:{mm:02d} daily")
    print("注意：这只证明排程装好且会按时触发。**跑成功要等首跑之后核收据里的 "
          "acceptance 两项**，周段最晚等到第一个周一凌晨那趟。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
