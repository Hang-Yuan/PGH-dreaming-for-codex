#!/usr/bin/env python3
"""test_stale_routes.py — audit_stale_routes.py 的回归套件

跑法：python3 test_stale_routes.py

一个「永远报零命中」的闸和一个真闸在两个仓上的输出完全一样。故负测是这套的主体：
每条规则都要有一个「把旧路由塞回去必须被抓住」的用例。反向也要测——闸不能把禁止
旧行为的说明判成旧行为，否则修得越清楚命中越多，闸会逼人删掉写得最好的那些段落。
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "audit_stale_routes", Path(__file__).with_name("audit_stale_routes.py"))
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


class GateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, rel: str, body: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def hits(self) -> list[str]:
        h, _, _ = gate.scan(self.root)
        return h


class RetiredSkillTest(GateBase):
    def test_week_sync_pointing_at_retired_weekly_review_is_caught(self):
        """A8#3 的原始形态：现役 week-sync 还指向已退役的 weekly-review。"""
        self.write(".claude/skills/week-sync/SKILL.md",
                   "- 归 `weekly-review` 周日梦载荷处理。\n")
        h = self.hits()
        self.assertTrue(any("retired-skill" in x for x in h), h)

    def test_daily_review_in_memory_canon_is_caught(self):
        self.write("assistant/MEMORY/00.memory_agent.md",
                   "| 工作结论 | close-node / daily-review |\n")
        self.assertTrue(any("retired-skill" in x for x in self.hits()))

    def test_v5_prefixed_skill_name_is_caught(self):
        # 测例名不带那个词根：`test_<词根>_...` 里词根后面接的是下划线，不是连字符 +
        # 名字，故脱敏闸的豁免（只认完整 skill 标识形态）盖不住它，会把这一行判成
        # 私区代号漏项。样本字符串本身是完整合法形态，仍在豁免内。
        self.write(".codex/skills/close-node/SKILL.md",
                   "Invoke `merak-write-progress` for the reasoning chain.\n")
        self.assertTrue(any("retired-skill" in x for x in self.hits()))

    def test_current_chain_name_is_clean(self):
        self.write("assistant/MEMORY/00.memory_agent.md",
                   "| 工作结论 | close-node / daily-dream phase A |\n")
        self.assertEqual(self.hits(), [])


class HardcodedTimeTest(GateBase):
    def test_agents_md_with_a_fixed_0610_is_caught(self):
        """A8#2 的原始形态：AGENTS.md 里写死 06:10。"""
        self.write(".codex/AGENTS.md", "| 06:10 定时记忆回放 | 调用 daily-dream |\n")
        h = self.hits()
        self.assertTrue(any("hardcoded-dream-time" in x for x in h), h)

    def test_hardcoded_logical_day_window_is_caught(self):
        self.write(".codex/skills/daily-dream/SKILL.md",
                   "Logical date `D` covers `[D 06:00, D+1 06:00)`.\n")
        self.assertTrue(any("hardcoded-boundary-window" in x for x in self.hits()))

    def test_dynamic_description_is_clean(self):
        self.write(".codex/AGENTS.md",
                   "固化在日界线 + 30 分钟触发；日界线由部署期作息访谈决定。\n")
        self.assertEqual(self.hits(), [])

    def test_text_forbidding_hardcoding_is_not_a_hit(self):
        """反向哨兵。

        不区分否定语境的闸会把「不得写死 06:10」判成「写死了 06:10」，于是把说明写得
        越清楚、命中越多——闸会逼人删掉最该留的那几行，方向正好是反的。
        """
        self.write(".codex/skills/daily-dream/SKILL.md",
                   "Do not hardcode 06:00 or 06:10 anywhere in this chain.\n")
        self.assertEqual(self.hits(), [])


class GoodbyeRouteTest(GateBase):
    def test_goodbye_triggering_consolidation_is_caught(self):
        """A8#1 的原始形态：hook 在告别时注入「先调用 daily-dream」。"""
        self.write(".codex/hooks/session_end.py",
                   'if re.search(r"晚安|收工", payload):\n'
                   '    emit("先调用 daily-dream 完整流程")\n')
        h = self.hits()
        self.assertTrue(any("goodbye-consolidation" in x for x in h), h)

    def test_revived_hook_registration_is_caught(self):
        """hook 复活：脚本被重新注册回 config.toml。"""
        self.write(".codex/config.toml",
                   '[[hooks.UserPromptSubmit]]\n'
                   'matcher = "晚安|收工"\n'
                   'command = "python hooks/session_end.py"  # 触发 daily-review\n')
        self.assertTrue(any("retired-skill" in x or "goodbye" in x
                            for x in self.hits()))

    def test_stating_that_goodbye_does_not_consolidate_is_clean(self):
        self.write(".claude/CLAUDE.md",
                   "| 用户道别（「晚安」「收工」）| **不触发任何固化**，"
                   "当日工作由次晨排程处理 |\n")
        self.assertEqual(self.hits(), [])


class ScopeTest(GateBase):
    """只扫现役。历史事实必须留得住。"""

    def test_retired_directory_is_excluded(self):
        self.write(".codex/skills/_retired_20260801/weekly-review/SKILL.md",
                   "name: merak-weekly-review\n06:10 automation invokes merak-dream.\n")
        self.assertEqual(self.hits(), [])

    def test_changelog_is_excluded(self):
        """CHANGELOG 的职责就是记旧判断。把它当缺陷会逼人删掉变更记录。"""
        self.write("CHANGELOG.md",
                   "- v6.1.0：06:10 定时 automation 跑 daily-review → weekly-review。\n")
        self.assertEqual(self.hits(), [])

    def test_iteration_log_is_excluded(self):
        self.write("ITERATION_LOG.md", "旧路由：告别触发 daily-review。已退役。\n")
        self.assertEqual(self.hits(), [])

    def test_file_outside_the_active_tree_is_ignored(self):
        self.write("docs/some_old_note.md", "daily-review 06:10\n")
        self.assertEqual(self.hits(), [])

    def test_active_scope_actually_covers_the_authority_files(self):
        """反向哨兵：范围表若漏掉某类权威文件，闸会在那类文件上永远报零命中。"""
        for rel in (".claude/CLAUDE.md", ".codex/AGENTS.md", ".codex/config.toml",
                    ".claude/skills/x/SKILL.md", ".codex/skills/x/SKILL.md",
                    ".claude/agents/x.md", ".codex/hooks/x.py",
                    "assistant/MEMORY/00.memory_agent.md", "README.md"):
            self.write(rel, "占位\n")
        scanned = {p.relative_to(self.root).as_posix()
                   for p in gate.active_files(self.root)}
        self.assertEqual(len(scanned), 9, sorted(scanned))


class ExemptionTest(GateBase):
    def test_registered_exemption_waives_but_still_reports(self):
        """豁免不是消失：命中仍列出来，只是不再判失败。

        静默豁免会让例外清单越长越无人复核——豁免的价值全在于它是**可见的**。
        """
        self.write("assistant/MEMORY/00.memory_agent.md", "旧链：daily-review\n")
        key = "assistant/MEMORY/00.memory_agent.md::retired-skill"
        gate.EXEMPTIONS[key] = "测试用豁免"
        self.addCleanup(gate.EXEMPTIONS.pop, key, None)
        hits, waived, _ = gate.scan(self.root)
        self.assertEqual(hits, [])
        self.assertEqual(len(waived), 1)
        self.assertIn("测试用豁免", waived[0])

    def test_exemption_is_keyed_to_one_file_and_one_rule(self):
        """豁免不得跨文件生效——否则一条豁免会把整类命中一起放过。"""
        self.write("assistant/MEMORY/00.memory_agent.md", "旧链：daily-review\n")
        self.write(".codex/AGENTS.md", "旧链：weekly-review\n")
        key = "assistant/MEMORY/00.memory_agent.md::retired-skill"
        gate.EXEMPTIONS[key] = "只豁免 canon 那份"
        self.addCleanup(gate.EXEMPTIONS.pop, key, None)
        hits, waived, _ = gate.scan(self.root)
        self.assertEqual(len(waived), 1)
        self.assertEqual(len(hits), 1)
        self.assertIn("AGENTS.md", hits[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
