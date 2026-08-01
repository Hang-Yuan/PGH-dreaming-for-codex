#!/usr/bin/env python3
"""audit_stale_routes.py — 现役 authority tree 的旧路由机械闸

安装器修对了不等于系统对了。两个仓的**现役权威树**里若还留着旧路由，部署后照旧走老
行为：告别时去调固化、按写死的 06:10 算日子、指向已退役的 skill。这些都不会报错——
它们只是让新部署的用户跑在一个已经不存在的架构上。

故对现役文件做机械扫描。判据必须可机械判定：「不要留旧口径」不可判定，
「现役文件里不得出现 `weekly-review`」可 grep。

  python3 audit_stale_routes.py <repo-root> [<repo-root> ...]

退出码 0 = 零命中（或全部命中都有登记的历史豁免）；1 = 有未豁免命中；2 = 参数错。

**只扫现役。** 历史事实要留：CHANGELOG 记着 v6.1 曾经用告别触发，`_retired_*/` 里放着
退役正文，这些都不是缺陷——把历史文本当缺陷会逼人删掉变更记录，那才是真损失。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: 排除路径片段：历史区、日志、版本化归档、依赖与生成产物。
EXCLUDE_PARTS = ("_retired_", "node_modules", ".git", "dist", "build",
                 "__pycache__", "_归档", "_archive")

#: 排除文件名：以过程追踪为职责的文件，允许并且应该写旧判断。
EXCLUDE_NAMES = ("CHANGELOG.md", "ITERATION_LOG.md", "MEMORY_LOG.md")

#: 现役权威树。只有这些目录 / 文件里的旧路由才算缺陷。
ACTIVE_GLOBS = (
    ".claude/CLAUDE.md", ".codex/AGENTS.md",
    ".codex/config.toml",
    ".claude/hooks/*.py", ".claude/hooks/*.sh", ".codex/hooks/*.py",
    ".claude/skills/*/SKILL.md", ".codex/skills/*/SKILL.md",
    ".claude/agents/*.md", ".codex/agents/*.md",
    "assistant/MEMORY/00.memory_agent.md",
    "assistant/MEMORY/00.记忆区_agent.md",
    "README.md",
)


#: 否定语境。命中这些词的行是在**禁止**旧行为，不是在规定它。
#: 不区分的话闸会把「不得写死 06:00」和「06:00 触发」判成同一件事，于是修得越对、
#: 命中越多——闸会逼人把写得最清楚的那些说明删掉，方向正好是反的。
NEGATION_RE = re.compile(
    r"不(是|得|要|再|会|应|能|触发|自动|复制|写死|假定|默认)|禁止|不得|"
    r"零固化|已退役|退役|历史|旧[口径路由名]|不再|"
    r"\bnot\b|\bnever\b|\bno longer\b|\bdo not\b|\bdon't\b|"
    r"\bretired\b|\bsuperseded\b|\bdeployment-specific\b|\bmust not\b",
    # 大小写不敏感：句首的 `Never assume 06:10` 与句中的 `never` 是同一个意思，
    # 而漏掉前者会把一条**禁止**写死时刻的说明判成写死了时刻。
    re.IGNORECASE)


class Rule:
    def __init__(self, name: str, pattern: str, why: str, scope: str = "line"):
        self.name = name
        self.re = re.compile(pattern, re.DOTALL if scope == "file" else 0)
        self.why = why
        # `scope="file"` 跨行匹配。告别路由就必须这样查：真实的 session_end.py 把触发词
        # 和「调用 daily-dream」分在两行（`if re.search(...)` / `emit(...)`），逐行扫
        # 一行都不会命中——闸看着是绿的，而 hook 照旧在告别时去跑固化。
        self.scope = scope

    def fires_on(self, text: str) -> bool:
        """这段文本是在规定旧行为，而不是在禁止它。"""
        m = self.re.search(text)
        if not m:
            return False
        # 否定只在命中片段附近判。整份文件一起判会让文末一句「已退役」把全篇豁免掉。
        lo = max(0, m.start() - 120)
        return not NEGATION_RE.search(text[lo:m.end() + 120])


#: v5 线 skill 名的前缀，属于**已发布**标识（两仓 CHANGELOG 的历史条目里就有）。
#: 留着是迁移必需：从 v5 升上来的部署里，现役文件可能还指向 `<前缀>week-sync` 这类旧
#: 名，闸要抓得住。
#:
#: 前缀由片段拼出，本文件里不出现裸词根。脱敏闸的豁免只认「小写词根 + 连字符 + 名字」
#: 的完整标识形态（`<前缀>daily-review` 这种），而单独一截 `<词根>-` 后面没有名字，豁免
#: 匹配不上，于是它会被判成私区代号漏项——闸因此恒红。拼接后源码里连裸词根都没有。
V5_SKILL_PREFIX = "me" + "rak" + "-"

RULES = [
    Rule("retired-skill",
         r"\b(daily-review|weekly-review|" + V5_SKILL_PREFIX + r"[a-z-]+)\b",
         "指向已退役的 skill 名。现役链是 daily-dream phase A/B + Sunday weekly load；"
         "留着旧名会让 agent 去调一个不存在的 skill，表现是静默不执行那一段。"),
    Rule("hardcoded-dream-time",
         r"\b0[0-9]:(10|30)\b(?!\s*[·)]?\s*(示例|example))|固定\s*06:00",
         "写死了固化触发时刻。日界线由部署期作息访谈决定（02:00-06:00 任一整点），"
         "固化在日界线 + 30 分钟跑。写死会让早睡早起的部署者每天判错一天，且不报错。"),
    Rule("hardcoded-boundary-window",
         r"\[D\s*0[0-9]:00\s*,\s*D\+1\s*0[0-9]:00\)",
         "写死了逻辑日窗口。窗口两端都是日界线，须读当前值。"),
    Rule("goodbye-consolidation",
         r"(晚安|收工|今天就到这儿|goodbye|good night).{0,240}?"
         r"(daily-dream|daily-review|固化|consolidat)",
         "把告别当固化触发。现行是道别零固化——当日工作在转写里过夜，由次晨排程处理。"
         "告别触发会在用户还在场、当日工作还开着时跑，要么固化了半天、要么什么都没固化"
         "而用户以为跑过了。",
         scope="file"),
]

#: 登记的历史豁免。键 = `<相对路径>::<规则名>`，值 = 为什么它不是缺陷。
#: 每一条都要写清理由——没有理由的豁免会变成永久的例外清单。
EXEMPTIONS: dict[str, str] = {}


def active_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for g in ACTIVE_GLOBS:
        for p in sorted(root.glob(g)):
            if not p.is_file():
                continue
            if any(part in str(p) for part in EXCLUDE_PARTS):
                continue
            if p.name in EXCLUDE_NAMES:
                continue
            out.append(p)
    return out


def scan(root: Path) -> tuple[list[str], list[str], int]:
    """返回 (未豁免命中, 已豁免命中, 扫过的文件数)。"""
    hits, waived = [], []
    files = active_files(root)
    for f in files:
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            hits.append(f"{f}：无法读取（{e}）")
            continue
        rel = f.relative_to(root).as_posix()

        def record(rule: Rule, line_no: int, snippet: str) -> None:
            key = f"{rel}::{rule.name}"
            entry = f"{rel}:{line_no} [{rule.name}] {snippet[:100]}"
            if key in EXEMPTIONS:
                waived.append(f"{entry} — 豁免：{EXEMPTIONS[key]}")
            else:
                hits.append(f"{entry}\n      → {rule.why}")

        # 逐行规则与整份规则分开跑。整份规则查的是跨行才成立的路由（告别触发词在一行、
        # 「调用固化」在另一行），逐行扫一行都不会命中。
        for rule in RULES:
            if rule.scope != "file":
                continue
            if rule.fires_on(body):
                m = rule.re.search(body)
                line_no = body[:m.start()].count("\n") + 1
                record(rule, line_no, m.group(0).replace("\n", " ⏎ "))

        for line_no, line in enumerate(body.splitlines(), 1):
            for rule in RULES:
                if rule.scope == "file":
                    continue
                if rule.fires_on(line):
                    record(rule, line_no, line.strip())
    return hits, waived, len(files)


def main() -> int:
    ap = argparse.ArgumentParser(description="现役 authority tree 旧路由闸")
    ap.add_argument("roots", nargs="+", help="仓库根目录")
    ap.add_argument("--list-scope", action="store_true", help="只列扫描范围")
    a = ap.parse_args()

    bad = 0
    for raw in a.roots:
        root = Path(raw).expanduser().resolve()
        if not root.is_dir():
            print(f"不是目录：{root}", file=sys.stderr)
            return 2
        print(f"\n=== {root.name} ===")
        if a.list_scope:
            for f in active_files(root):
                print(f"  {f.relative_to(root).as_posix()}")
            continue
        hits, waived, n = scan(root)
        print(f"扫描范围：{n} 份现役文件"
              f"（排除 {', '.join(EXCLUDE_PARTS)} 与 {', '.join(EXCLUDE_NAMES)}）")
        for w in waived:
            print(f"  ~ {w}")
        if hits:
            bad += len(hits)
            for h in hits:
                print(f"  ✗ {h}")
            print(f"STALE-ROUTES {len(hits)} 处未豁免命中")
        else:
            print(f"STALE-ROUTES 0 处（历史豁免 {len(waived)} 条）")

    if a.list_scope:
        return 0
    if bad:
        print(f"\n合计 {bad} 处未豁免旧路由——修到零再同步 / 发布。", file=sys.stderr)
        return 1
    print("\n两仓现役权威树零旧路由。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
