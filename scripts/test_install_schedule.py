#!/usr/bin/env python3
"""test_install_schedule.py — install_schedule.py 的回归套件

跑法：python3 test_install_schedule.py

每条测试对应一个实测过或推演出的失效形态。加测试的规矩：修了一个 bug 就补一条
针对该形态的测试，否则修完的东西下次会以同样的方式坏掉。
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "install_schedule", Path(__file__).with_name("install_schedule.py"))
sched = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sched)

#: 排程包装器。proof 判定在它那边，故与安装器一起测——两者必须同数。
_wspec = importlib.util.spec_from_file_location(
    "run_scheduled_dream", Path(__file__).with_name("run_scheduled_dream.py"))
wrapper = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(wrapper)


class BoundaryDerivationTest(unittest.TestCase):
    def d(self, sleep: str, wake: str) -> int:
        h, _ = sched.derive_boundary(
            sched.parse_hhmm(sleep, "s"), sched.parse_hhmm(wake, "w"))
        return h

    def test_normal_sleeper_gets_late_boundary(self):
        """23:00 睡 07:00 起 = 常见作息，日界线应贴上界 06:00。

        曾经的公式取「入睡 + 2h」，给这类人算出 01:00——那会把 01:00-06:00 的
        深夜工作切进次日，而这段恰恰是最常出现深夜工作的时段。
        """
        self.assertEqual(self.d("23:00", "07:00"), 6)

    def test_early_riser_gets_earlier_boundary(self):
        """早起的人日界线必须前移，否则他起床后干的活还算前一天。"""
        self.assertEqual(self.d("22:30", "05:00"), 4)
        self.assertEqual(self.d("21:00", "04:00"), 3)
        self.assertEqual(self.d("20:00", "03:00"), 2)

    def test_boundary_never_leaves_allowed_window(self):
        """凡是**接受**的作息，日界线必落在允许区间；不可行的作息应抛出而非夹取。"""
        accepted = 0
        for sleep in ("19:00", "21:00", "23:00", "01:00", "03:00", "05:00"):
            for wake in ("02:00", "05:00", "07:00", "09:00", "12:00", "14:00"):
                try:
                    h = self.d(sleep, wake)
                except SystemExit:
                    continue                      # 无可行窗口，拒绝是正确行为
                accepted += 1
                self.assertGreaterEqual(h, sched.BOUNDARY_MIN_H, (sleep, wake))
                self.assertLessEqual(h, sched.BOUNDARY_MAX_H, (sleep, wake))
                # 还要真落在「已睡下、还没起」之间，不只是落在区间里。
                self.assertLess(h, sched.parse_hhmm(wake, "w")[0], (sleep, wake))
        self.assertGreater(accepted, 20, "绝大多数常见作息应被接受，不是被一律拒绝")

    def test_boundary_after_sleep_when_sleeping_late(self):
        """凌晨 3 点睡的人，日界线不能落在他还在工作的 02:00。"""
        self.assertGreaterEqual(self.d("03:00", "11:00"), 4)

    def test_dream_time_is_boundary_plus_offset(self):
        self.assertEqual(sched.dream_time(6), (6, 30))
        self.assertEqual(sched.dream_time(2), (2, 30))

    def test_parse_hhmm_rejects_garbage(self):
        for bad in ("7", "25:00", "12:60", "abc", ""):
            with self.assertRaises(SystemExit):
                sched.parse_hhmm(bad, "--sleep")


    def test_rejects_pairs_with_no_feasible_boundary(self):
        """作息把窗口挤没了时必须拒绝，不能给一个夹出来的数字假装算好了。

        05:00 睡 07:00 起：日界线须晚于入睡 1h（≥06:00）、且早于起床（<07:00），
        同时受上界 06:00 约束——06:00 恰好满足，故这对是合法的。而 05:30 睡
        06:00 起则无解（需 ≥06:30 又需 <06:00）。夹取只保证落在 [MIN,MAX]，
        不保证落在「已睡下、还没起」之间。
        """
        with self.assertRaises(SystemExit):
            self.d("05:30", "06:00")
        with self.assertRaises(SystemExit):
            self.d("06:00", "06:30")

    def test_accepts_tight_but_feasible_pair(self):
        self.assertEqual(self.d("05:00", "07:00"), 6)


# 真实 pmset 输出的形状：Battery Power 在前，AC Power 在后，字段带前导空格。
PMSET_REAL = """Battery Power:
 sleep                1
 powernap             1
 disksleep            10
AC Power:
 sleep                0
 powernap             1
 disksleep            10
"""
PMSET_AC_SLEEPS = PMSET_REAL.replace("AC Power:\n sleep                0",
                                     "AC Power:\n sleep                1")


class PmsetParseTest(unittest.TestCase):
    def test_ac_block_is_found_despite_battery_first(self):
        """`AC Power:` 在 `Battery Power:` 之后。

        早先用 `split("Battery Power")[0]` 取 AC 段，实测（macOS 25.5）得到空串，
        `_pmset_field` 在空串上返回 None，于是「AC 段 sleep=1」被读成「不睡眠 ✓」
        报 READY。假绿方向恰是最坏的：真会漏跑时说没问题。
        """
        ac = sched._pmset_ac_block(PMSET_REAL)
        self.assertIsNotNone(ac)
        self.assertEqual(sched._pmset_field(ac, "sleep"), 0)
        self.assertNotIn("Battery", ac)

    def test_ac_sleep_nonzero_is_detected(self):
        ac = sched._pmset_ac_block(PMSET_AC_SLEEPS)
        self.assertEqual(sched._pmset_field(ac, "sleep"), 1)

    def test_missing_ac_block_returns_none_not_empty(self):
        """找不到 AC 段要返回 None（调用方据此报 NEEDS-ATTENTION），
        不能返回空串——空串会让字段查询静默返回 None 而被当成「没设睡眠」。"""
        self.assertIsNone(sched._pmset_ac_block("Battery Power:\n sleep 1\n"))


LINE = ("**逻辑日期口径**：物理 hour < 06:00 → 逻辑日期 = 物理日期 − 1；"
        "≥ 06:00 → 同物理日期。适用于流水归属。\n")


class BoundaryPatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "CLAUDE.md"
        self.addCleanup(self.tmp.cleanup)

    def test_patches_both_halves_of_the_line(self):
        """两个半句必须同时改。

        只替前半句会产出 `< 04:00 … ≥ 06:00` 这种自相矛盾的一行，而没有任何闸会
        报错——读到它的 agent 在 04:00-06:00 之间给出的答案是随机的。
        """
        self.f.write_text(LINE, encoding="utf-8")
        sched.patch_boundary([self.f], 4, dry=False)
        out = self.f.read_text(encoding="utf-8")
        self.assertIn("< 04:00", out)
        self.assertIn("≥ 04:00", out)
        self.assertNotIn("06:00", out)

    def test_idempotent(self):
        self.f.write_text(LINE, encoding="utf-8")
        sched.patch_boundary([self.f], 4, dry=False)
        first = self.f.read_text(encoding="utf-8")
        notes, fails = sched.patch_boundary([self.f], 4, dry=False)
        self.assertEqual(self.f.read_text(encoding="utf-8"), first)
        self.assertTrue(any("无需改" in n for n in notes))
        self.assertEqual(fails, [])

    def test_dry_run_does_not_write(self):
        self.f.write_text(LINE, encoding="utf-8")
        sched.patch_boundary([self.f], 4, dry=True)
        self.assertIn("< 06:00", self.f.read_text(encoding="utf-8"))

    def test_unrecognised_shape_fails_when_required(self):
        """形状不认识时不动，且**必须让安装失败**。

        只记一条 note 而放安装继续，会留下按新日界线跑、口径却是旧值的排程——
        两边各说一套，每天归错一段工作且无运行时报错。
        """
        self.f.write_text("物理 hour < 06:00 时算前一天\n", encoding="utf-8")
        notes, fails = sched.patch_boundary([self.f], 4, dry=False, required=True)
        self.assertIn("< 06:00", self.f.read_text(encoding="utf-8"))
        self.assertTrue(any("形状不认识" in n for n in notes))
        self.assertTrue(fails)

    def test_missing_required_target_is_a_failure(self):
        notes, fails = sched.patch_boundary(
            [Path(self.tmp.name) / "nope.md"], 4, dry=False, required=True)
        self.assertTrue(fails)
        self.assertTrue(any("落点不存在" in n for n in notes))

    def test_optional_target_does_not_fail(self):
        notes, fails = sched.patch_boundary(
            [Path(self.tmp.name) / "nope.md"], 4, dry=False, required=False)
        self.assertEqual(fails, [])
        self.assertTrue(notes)


class BoundaryTargetsTest(unittest.TestCase):
    """repo root 与 assistant root 是两个根，拼错会指向不存在的路径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / ".claude").mkdir(parents=True)
        (self.repo / ".claude" / "CLAUDE.md").write_text(LINE, encoding="utf-8")
        self.assistant = self.repo / "assistant"
        (self.assistant / "MEMORY").mkdir(parents=True)
        (self.assistant / "MEMORY" / "00.memory_agent.md").write_text(
            LINE, encoding="utf-8")

    def test_packaged_layout_resolves_both_roots(self):
        """发布包布局：assistant root = <repo>/assistant，宪法层在 <repo>/.claude/。"""
        req, _ = sched.boundary_targets(self.assistant, "claude")
        self.assertIn(self.assistant / "MEMORY" / "00.memory_agent.md", req)
        self.assertIn(self.repo / ".claude" / "CLAUDE.md", req)
        for p in req:
            self.assertTrue(p.exists(), p)

    def test_relocated_assistant_root_does_not_double_up_the_segment(self):
        """assistant root 被指到别处时不得拼出 `<root>/assistant/MEMORY/...`。"""
        moved = Path(self.tmp.name) / "elsewhere" / "myassistant"
        (moved / "MEMORY").mkdir(parents=True)
        (moved / "MEMORY" / "00.memory_agent.md").write_text(LINE, encoding="utf-8")
        req, _ = sched.boundary_targets(moved, "claude")
        self.assertIn(moved / "MEMORY" / "00.memory_agent.md", req)
        for p in req:
            self.assertNotIn("assistant/assistant", str(p))

    def test_exactly_one_config_target(self):
        """只取一份宪法层——两份都当必须落点会因无关的那份不匹配而误判失败。"""
        req, _ = sched.boundary_targets(self.assistant, "claude")
        cfgs = [p for p in req if p.name in ("CLAUDE.md", "AGENTS.md")]
        self.assertEqual(len(cfgs), 1)

    def test_legacy_chinese_canon_name_is_found(self):
        """旧仓与旧部署用中文 canon 名。取不到会以「必须落点缺失」中止安装，
        而那是纯命名差异、不是真缺口径行。"""
        moved = Path(self.tmp.name) / "legacy" / "assistant"
        (moved / "MEMORY").mkdir(parents=True)
        legacy = moved / "MEMORY" / "00.记忆区_agent.md"
        legacy.write_text(LINE, encoding="utf-8")
        req, _ = sched.boundary_targets(moved, "codex")
        self.assertIn(legacy, req)

    def test_standard_name_wins_when_both_exist(self):
        """两个名字并存时取现行规范名，不要两份都改。"""
        (self.assistant / "MEMORY" / "00.记忆区_agent.md").write_text(
            LINE, encoding="utf-8")
        req, _ = sched.boundary_targets(self.assistant, "claude")
        self.assertIn(self.assistant / "MEMORY" / "00.memory_agent.md", req)
        self.assertNotIn(self.assistant / "MEMORY" / "00.记忆区_agent.md", req)

    def test_missing_canon_reports_preferred_name(self):
        """都不存在时报错要指向应该建的那个（现行规范名），不是历史名。"""
        empty = Path(self.tmp.name) / "empty" / "assistant"
        (empty / "MEMORY").mkdir(parents=True)
        req, _ = sched.boundary_targets(empty, "claude")
        self.assertIn(empty / "MEMORY" / "00.memory_agent.md", req)

    def test_explicit_override_wins(self):
        other = Path(self.tmp.name) / "custom.md"
        other.write_text(LINE, encoding="utf-8")
        req, _ = sched.boundary_targets(self.assistant, "claude", config_file=other)
        # 比 resolve 后的值——macOS 的 /var 是 /private/var 的符号链接。
        self.assertIn(other.resolve(), req)

    def test_codex_runtime_targets_agents_md(self):
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex" / "AGENTS.md").write_text(LINE, encoding="utf-8")
        req, _ = sched.boundary_targets(self.assistant, "codex")
        self.assertIn(self.repo / ".codex" / "AGENTS.md", req)


class CommandBuildTest(unittest.TestCase):
    """命令拼装的测试**不得依赖本机装了哪个 CLI**。

    早先直接调 `runtime_cmd("claude", ...)`，于是在装了 claude 的机器上通过、在干净
    HOME / CI 上抛 SystemExit 报错。测试套件必须在两种环境下给同一个结论——否则「本机
    绿」只说明本机恰好装了那个二进制，说不出代码对不对。
    """

    def setUp(self):
        # 假可执行文件：拼命令只需要一个路径字符串，不需要真能跑。
        self.exe = mock.patch.object(sched, "_find_exe",
                                     lambda name, extra: f"/fake/bin/{name}")
        self.exe.start()
        self.addCleanup(self.exe.stop)

    def test_prompt_forbids_asking_questions(self):
        """排程跑的是无人值守链，prompt 必须明确禁止提问——否则它会停在问句上
        等一个不存在的人回答，整趟静默作废。"""
        self.assertIn("不要问我任何问题", sched.PROMPT)

    def test_shutdown_is_chained_on_success_only(self):
        """关机用 `&&` 串在成功之后。用 `;` 会在任务失败时也关机，把现场关掉。"""
        cmd = sched.runtime_cmd("claude", Path.home(), shutdown=True)
        self.assertIn("&&", cmd)
        idx_redirect = cmd.index(">>")
        self.assertGreater(cmd.rindex("&&"), idx_redirect)

    def test_no_shutdown_when_not_requested(self):
        cmd = sched.runtime_cmd("claude", Path.home(), shutdown=False)
        self.assertNotIn("shutdown", cmd)

    def test_unknown_runtime_rejected(self):
        with self.assertRaises(SystemExit):
            sched.runtime_cmd("gemini", Path.home(), shutdown=False)

    def test_missing_exe_aborts_real_install(self):
        """真安装时缺可执行文件必须中止——排程指向不存在的二进制不会报错，
        只是每天夜里静默失败一次。"""
        with mock.patch.object(sched, "_find_exe",
                               side_effect=SystemExit("找不到")):
            with self.assertRaises(SystemExit):
                sched.runtime_cmd("codex", Path.home(), shutdown=False)

    def test_missing_exe_allowed_in_dry_run_with_visible_placeholder(self):
        """`--dry-run` 不落地任何东西，故不该被另一端缺二进制挡掉预览；
        但占位符必须一眼假，否则预览会被误读成「这条命令能跑」。"""
        with mock.patch.object(sched, "_find_exe",
                               side_effect=SystemExit("找不到")):
            cmd = sched.runtime_cmd("codex", Path.home(), shutdown=False,
                                    allow_missing_exe=True)
        self.assertIn("未找到", cmd)
        self.assertIn("codex", cmd)


class ShutdownProbeTest(unittest.TestCase):
    def test_probe_is_read_only(self):
        """关机探测不得有副作用。

        早先用 `sudo -n /sbin/shutdown -h +2400` 探、靠随后 killall 撤销——那是在
        部署机上真排了一次关机；killall 若失败，机器会在 40 小时后自己关掉而部署者
        不知为何。故探测必须只查授权表（`sudo -n -l`），不执行。
        """
        import inspect
        # 只看可执行的部分——docstring 里提到 killall 是在解释它为何被删掉。
        src = inspect.getsource(sched.shutdown_ready)
        body = src.split('"""', 2)[-1]
        self.assertIn('"-l"', body)
        self.assertNotIn("killall", body)
        self.assertNotIn('"-h"', body)
        # 关机动作本身仍必须存在于被排的命令里（探测只读不代表不执行）。
        self.assertIn("shutdown", sched._shutdown_cmd())


class AcceptanceEvidenceTest(unittest.TestCase):
    def test_sentinel_carries_timezone_and_two_unverified_flags(self):
        """收据只能证明「装上了」。跑成功要留待验哨兵，周段另留一个。"""
        s = sched.first_run_sentinel("claude", 6, 30)
        self.assertTrue(s["timezone_iana"])
        self.assertRegex(s["utc_offset"], r"^[+-]\d{4}$")
        self.assertFalse(s["first_run_verified"])
        self.assertFalse(s["first_weekly_run_verified"])

    def test_expected_first_run_is_in_the_future(self):
        from datetime import datetime as _dt
        s = sched.first_run_sentinel("claude", 6, 30)
        self.assertGreater(_dt.fromisoformat(s["expected_first_run"]),
                           _dt.now().astimezone())

    def test_weekly_sentinel_targets_a_sunday_logical_day(self):
        """周段只在目标逻辑日为周日时跑；那趟的执行日是周一凌晨。"""
        from datetime import datetime as _dt
        s = sched.first_run_sentinel("claude", 6, 30)
        self.assertEqual(_dt.fromisoformat(s["expected_first_weekly_run"]).weekday(), 0)


class SmokeRunTest(unittest.TestCase):
    def test_missing_exe_reports_blocked_not_pass(self):
        """CLI 不在本机时必须报 BLOCKED，不能静默当通过。

        **必须 mock `_find_exe`**：早先这条直接调 `smoke_run`，于是结果取决于跑测试
        的机器上恰好装没装 CLI——装了就真起一次模型调用（慢，且成败与本条要验的
        性质无关），没装才走到 BLOCKED 分支。测试不该问部署机的环境。
        """
        with mock.patch.object(sched, "_find_exe",
                               side_effect=SystemExit("找不到 codex 可执行文件")):
            ok, msg = sched.smoke_run("codex", Path.cwd())
        self.assertFalse(ok)
        self.assertIn("BLOCKED", msg)

    def test_token_is_distinctive(self):
        """回显 token 要足够独特，避免撞上模型自述里的普通词。"""
        self.assertIn("PGH", sched.SMOKE_TOKEN)

    def test_codex_smoke_uses_current_flags(self):
        """实测 codex-cli 0.146.0-alpha.9.2 上 `--full-auto` 是**已弃用**（打
        `warning: --full-auto is deprecated; use --sandbox workspace-write instead`
        后仍会跑），不是已移除。仍然要换掉：无人值守的夜跑不该挂在一个弃用兼容层上，
        它哪天真被移除时的表现是每夜静默失败。
        探测还必须带 `--skip-git-repo-check`（知识库通常不是 git 仓库）与
        `--ephemeral`（不在用户会话历史里留痕）。"""
        seen: dict = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout=sched.SMOKE_TOKEN, stderr="")

        with mock.patch.object(sched, "_find_exe", return_value="/x/codex"), \
             mock.patch.object(sched.subprocess, "run", fake_run):
            ok, _ = sched.smoke_run("codex", Path.cwd())
        self.assertTrue(ok)
        self.assertNotIn("--full-auto", seen["cmd"])
        self.assertIn("--skip-git-repo-check", seen["cmd"])
        self.assertIn("--ephemeral", seen["cmd"])
        self.assertIn("workspace-write", seen["cmd"])


class SmokeResidueTest(unittest.TestCase):
    """探针不许在 L0 留下会话残留，且残留是 FAIL 条件而不是备注。

    残留只写进说明时，`state` 这个唯一结论字段照样是 READY，读收据的人和 week-sync
    都不会知道。而那份残留的转写会进次日回放候选，链读到一句
    「Reply with exactly: PGH_HEADLESS_OK」并当成一段真实对话代谢。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sess = Path(self.tmp.name) / "sessions"
        self.sess.mkdir()
        self.patch = mock.patch.object(sched, "_session_dirs",
                                       lambda rt: [self.sess])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_smoke(self, runtime="claude", *, writes=None, echo=True):
        """跑 smoke，`writes` 是 (文件名, 内容) 列表，模拟 CLI 落下的转写。"""
        def fake_run(cmd, **kw):
            for name, body in (writes or []):
                (self.sess / name).write_text(body, encoding="utf-8")
            return SimpleNamespace(
                returncode=0, stdout=sched.SMOKE_TOKEN if echo else "别的", stderr="")

        with mock.patch.object(sched, "_find_exe", return_value="/x/cli"), \
             mock.patch.object(sched.subprocess, "run", fake_run):
            return sched.smoke_run(runtime, Path(self.tmp.name))

    def test_claude_probe_carries_the_no_persistence_flag(self):
        """实测缺了它 `claude -p` 会在 `~/.claude/projects/` 落一份转写。"""
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout=sched.SMOKE_TOKEN, stderr="")

        with mock.patch.object(sched, "_find_exe", return_value="/x/claude"), \
             mock.patch.object(sched.subprocess, "run", fake_run):
            ok, _ = sched.smoke_run("claude", Path(self.tmp.name))
        self.assertTrue(ok)
        self.assertIn(sched.CLAUDE_NO_PERSIST, seen["cmd"])

    def test_clean_run_passes(self):
        ok, msg = self.run_smoke()
        self.assertTrue(ok, msg)
        self.assertIn("残留 0", msg)

    def test_probe_transcript_is_cleaned_and_then_passes(self):
        """确认属于本次探针的新增转写：删掉、复验归零，才算通过。"""
        body = f'{{"role":"user","content":"Reply with exactly: {sched.SMOKE_TOKEN}"}}\n'
        ok, msg = self.run_smoke(writes=[("probe.jsonl", body)])
        self.assertTrue(ok, msg)
        self.assertFalse((self.sess / "probe.jsonl").exists())
        self.assertIn("清理了 1 份", msg)

    def test_residue_that_cannot_be_attributed_fails_and_is_kept(self):
        """新增但不像探针产物的转写：判 FAIL 且**不删**。

        探针跑的那一分钟里用户可能正好在另一个窗口开了会话。那份也是新增，删掉就删了
        用户真实工作的 L0 唯一副本，不可恢复。故宁可报失败让人来看。
        """
        real = "\n".join(f'{{"turn":{i}}}' for i in range(200)) + "\n"
        ok, msg = self.run_smoke(writes=[("real-work.jsonl", real)])
        self.assertFalse(ok)
        self.assertIn("FAIL", msg)
        self.assertTrue((self.sess / "real-work.jsonl").exists())

    def test_token_echo_does_not_excuse_residue(self):
        """命中 token 也不能盖过残留——早先正是「回显对了就 return True」。"""
        big = f'{{"x":"{sched.SMOKE_TOKEN}"}}\n' + "\n".join(
            f'{{"turn":{i}}}' for i in range(100))
        ok, msg = self.run_smoke(echo=True, writes=[("mixed.jsonl", big)])
        self.assertFalse(ok, msg)

    def test_undeletable_residue_fails(self):
        body = f'{{"content":"{sched.SMOKE_TOKEN}"}}\n'
        with mock.patch.object(Path, "unlink",
                               side_effect=OSError("只读卷")):
            ok, msg = self.run_smoke(writes=[("stuck.jsonl", body)])
        self.assertFalse(ok)
        self.assertIn("删除失败", msg)

    def test_preexisting_transcripts_are_not_touched(self):
        """反向哨兵：探针之前就存在的转写不在差集里，一份都不许动。"""
        old = self.sess / "yesterday.jsonl"
        old.write_text(f'{{"mentions":"{sched.SMOKE_TOKEN}"}}\n', encoding="utf-8")
        ok, msg = self.run_smoke()
        self.assertTrue(ok, msg)
        self.assertTrue(old.exists(), "动了探针之前就存在的转写")


class RollbackTest(unittest.TestCase):
    """故障注入：正文改了、后面某一步失败时，正文必须回到安装前。

    这是唯一需要真跑 `main()` 的一组。前面各组都在单元层测函数，于是 `main()` 里的
    顺序与异常处理从来没被执行过——A6 那个 `run_h` 未定义的 NameError 就是这么活到
    安装现场的：所有测试都绿，真装时第一行就崩。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / ".claude").mkdir(parents=True)
        self.cfg = self.repo / ".claude" / "CLAUDE.md"
        self.cfg.write_text(LINE, encoding="utf-8")
        self.assistant = self.repo / "assistant"
        (self.assistant / "MEMORY").mkdir(parents=True)
        self.canon = self.assistant / "MEMORY" / "00.memory_agent.md"
        self.canon.write_text(LINE, encoding="utf-8")
        self.before = {self.cfg: self.cfg.read_text(encoding="utf-8"),
                       self.canon: self.canon.read_text(encoding="utf-8")}
        self.pgh = Path(self.tmp.name) / ".pgh"
        self.job_snap = None          # 首次安装：本机原先没有 job
        self.restores: list = []

    def run_main(self, argv: list[str], **patches):
        """跑 main()，把收据目录、供电探测与 CLI 查找全部换成本地假件。"""
        # job 快照 / 恢复默认换成记账桩：真跑 launchctl 会动本机排程。
        self.jobs: list[str] = []
        base = {
            "PGH_DIR": self.pgh,
            # `SCRIPTS_DIR` 是模块加载时从 `PGH_DIR` 算出来的常量，改 `PGH_DIR` 不会
            # 让它跟着变。不一起换掉的话 `install_runtime_scripts()` 会把脚本复制进
            # **真实** `~/.pgh/scripts/`——单测覆盖用户的现役排程脚本，而且是静默的。
            "SCRIPTS_DIR": self.pgh / "scripts",
            "check_power": lambda: (True, ["测试桩"]),
            "_find_exe": lambda *a, **k: "/fake/cli",
            "snapshot_job": lambda rt: self.job_snap,
            "restore_job": lambda rt, snap: self.record_restore(snap),
        }
        base.update(patches)
        stack = [mock.patch.object(sched, k, v) for k, v in base.items()]
        # receipt_path/log_path 闭在模块常量上，改 PGH_DIR 后要跟着重算。
        stack.append(mock.patch.object(
            sched, "receipt_path",
            lambda rt: self.pgh / f"schedule_receipt.{rt}.json"))
        with mock.patch("sys.argv", ["install_schedule.py", *argv]):
            for s in stack:
                s.start()
            try:
                return sched.main()
            finally:
                for s in reversed(stack):
                    s.stop()

    def record_restore(self, snap):
        self.restores.append(snap)
        return "假恢复"

    def assert_job_rolled_back(self):
        """恢复必须发生，且目标是**安装前那个状态**（`self.job_snap`）。

        按 fixture 判定而不是写死 None：首次安装的 fixture 是 None（该卸掉新装的），
        重装的 fixture 是旧 job 定义（该原样恢复）。同一组断言在两种场景下各自成立，
        故两组故障注入共用同一套测试，只换 setUp。
        """
        self.assertEqual(self.restores, [self.job_snap],
                         f"job 恢复目标不对：{self.restores!r}")

    def assert_no_job_restore(self):
        self.assertEqual(self.restores, [], "成功路径不该恢复 job")

    def assert_text_restored(self):
        for f, body in self.before.items():
            self.assertEqual(f.read_text(encoding="utf-8"), body,
                             f"{f.name} 没有回滚到安装前")

    def assert_no_receipt(self):
        self.assertFalse((self.pgh / "schedule_receipt.claude.json").exists(),
                         "失败路径不该留下收据——收据是「装好了」的凭据")

    def test_bad_timezone_changes_nothing_at_all(self):
        """非法时区必须在第一次 mutation 之前就被拒。

        早先 `--timezone` 是在 `verify()` / `first_run_sentinel()` 里才校验的，而那
        两步发生在正文已 patch、job 已装上之后：拼错一个时区名会抛 SystemExit，留下
        「按新日界线改过的正文 + 一个 ACTIVE job + 没有收据」。参数拼错本该零副作用。
        """
        never = mock.Mock(return_value=["不该被调到"])
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4",
             "--timezone", "Asia/Shangahi",          # 拼错
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): never},
        )
        self.assertEqual(rc, 2)
        never.assert_not_called()
        self.assert_text_restored()
        self.assert_no_receipt()
        self.assert_no_job_restore()     # 什么都没动，故也无须恢复

    def test_verify_failure_removes_the_new_job(self):
        """回查不过 = 这次安装没成立，不许留 ACTIVE job。

        早先是「写 INSTALL_UNVERIFIED + return 1」，job 与改过的正文都留在原地。
        回查不过的两种成因（时刻字段写坏 / job 没真正启用）都会让它在错误时刻跑或
        永不跑，而正文已经按新日界线改过——留下的是一个没人知道会不会跑的中间态。
        """
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4", "--smoke",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): lambda *a: ["假装装好了"]},
            smoke_run=lambda rt, wd: (True, "PASS：假注入"),
            verify=lambda *a, **k: (False, "假回查失败：抓不到 next fire", {}),
        )
        self.assertEqual(rc, 1)
        self.assert_text_restored()
        self.assert_no_receipt()
        self.assert_job_rolled_back()

    def test_installer_failure_rolls_back_boundary_text(self):
        """安装器抛 SystemExit（launchctl bootstrap / schtasks / systemctl 非 0）时，
        正文必须恢复。不恢复会留下「按新日界线写的口径 + 没有任何排程」——用户以为
        作息改好了，实际没有东西会在那个时刻跑，而且没有报错。"""
        boom = mock.Mock(side_effect=SystemExit("launchctl bootstrap 失败：假注入"))
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): boom},
        )
        self.assertEqual(rc, 1)
        boom.assert_called_once()
        self.assert_text_restored()
        self.assert_no_receipt()

    def test_smoke_failure_leaves_no_enabled_job(self):
        """smoke 跑不通时不许装 job。

        装了只会每夜失败一次，而失败发生在凌晨、没人看着——排程的失败是静默的。
        故顺序必须是「先证明能跑，再排上」。
        """
        never = mock.Mock(return_value=["不该被调到"])
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4", "--smoke",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): never},
            smoke_run=lambda rt, wd: (False, "FAIL：假注入的登录失败"),
        )
        self.assertEqual(rc, 1)
        never.assert_not_called()
        self.assert_text_restored()
        self.assert_no_receipt()

    def test_missing_required_target_rolls_back_the_other_file(self):
        """一处必须落点写不上时，另一处已经写好的也要退回去。

        否则两处口径不同数：一份说 04:00、一份说 06:00，读到哪份就按哪份算，
        而两份都不报错。这正是「每天有一段工作被归错日子」的成因。
        """
        self.canon.write_text("这一行没有口径句，替不上\n", encoding="utf-8")
        self.before[self.canon] = self.canon.read_text(encoding="utf-8")
        never = mock.Mock(return_value=["不该被调到"])
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): never},
        )
        self.assertEqual(rc, 1)
        never.assert_not_called()
        self.assert_text_restored()

    def test_success_path_keeps_new_boundary_and_writes_receipt(self):
        """反向哨兵：成功时不许回滚。

        只测失败路径的话，一个「无条件回滚」的实现也能全绿——那样正文永远改不动。
        """
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4", "--smoke",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): lambda *a: ["假装装好了"]},
            smoke_run=lambda rt, wd: (True, "PASS：假注入"),
            verify=lambda *a, **k: (True, "假回查通过", {"probe": "stub"}),
        )
        self.assertEqual(rc, 0)
        for f in self.before:
            body = f.read_text(encoding="utf-8")
            self.assertIn("< 04:00", body)
            self.assertNotIn("06:00", body)
        r = json.loads((self.pgh / "schedule_receipt.claude.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual(r["state"], "READY")
        self.assertEqual(r["boundary_hour"], 4)

    def test_smoke_not_run_is_not_ready(self):
        """不跑 smoke 就不是 READY——「CLI 真能被调起来」没有实证。"""
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): lambda *a: ["假装装好了"]},
            verify=lambda *a, **k: (True, "假回查通过", {}),
        )
        self.assertEqual(rc, 1)
        r = json.loads((self.pgh / "schedule_receipt.claude.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual(r["state"], "INSTALLED_SMOKE_NOT_RUN")


class ReinstallRollbackTest(RollbackTest):
    """重装场景：本机已有一个**健康的** job，改作息时失败。

    比首次安装更严重。`install_macos` 为了能重复 bootstrap 同一 label，必须先
    bootout 旧 job；此时 bootstrap 失败就把一个本来每夜正常跑的排程卸掉了，而正文
    回滚救不了它。表现是「改作息没成功」升级成「原来会跑的现在也不跑了」，且失败在
    夜里没人看着，要到 week-sync 查出连续断档才被发现。
    """

    def setUp(self):
        super().setUp()
        self.job_snap = {"kind": "launchd", "path": "/fake/old.plist",
                         "body": "<!-- 旧 job：每晚 06:30 -->"}

    def test_fixture_really_has_a_previous_job(self):
        """防退化哨兵。

        setUp 若哪天坏掉、`job_snap` 退回 None，继承来的那些断言会改成核「卸掉新装
        的」并全部通过——这个子类就静默变成基类的副本，重装路径再也没被测过。
        """
        self.assertIsNotNone(self.job_snap)
        self.assertEqual(self.job_snap["kind"], "launchd")

    def test_smoke_failure_never_touches_the_previous_job(self):
        """smoke 在装 job 之前跑，故失败时旧 job 根本没被动过——不该去「恢复」它。

        恢复动作本身要走 bootout + bootstrap，对一个完好的 job 做这套是无谓风险。
        """
        never = mock.Mock(return_value=["不该被调到"])
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4", "--smoke",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): never},
            smoke_run=lambda rt, wd: (False, "FAIL：假注入"),
        )
        self.assertEqual(rc, 1)
        never.assert_not_called()
        self.assert_text_restored()
        self.assert_no_job_restore()

    def test_bad_timezone_never_touches_the_previous_job(self):
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4",
             "--timezone", "Nowhere/Nothing",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): mock.Mock()},
        )
        self.assertEqual(rc, 2)
        self.assert_text_restored()
        self.assert_no_job_restore()

    def test_success_path_does_not_restore(self):
        rc = self.run_main(
            ["--runtime", "claude", "--boundary-hour", "4", "--smoke",
             "--assistant-root", str(self.assistant)],
            INSTALLERS={platform.system(): lambda *a: ["假装装好了"]},
            smoke_run=lambda rt, wd: (True, "PASS：假注入"),
            verify=lambda *a, **k: (True, "假回查通过", {}),
        )
        self.assertEqual(rc, 0)
        self.assert_no_job_restore()


class PersistentScriptsTest(unittest.TestCase):
    """临时 clone 被删掉之后，排程仍须能跑，且改作息 / 卸载 / 首跑验收都不断路。

    新用户的典型路径是 `git clone` 到临时目录 → 跑安装 → 删掉 clone。job 若指向仓库
    里的脚本，此后每夜固化都会静默失败（文件不存在），而失败发生在凌晨、没人看着。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clone = Path(self.tmp.name) / "tmp-clone" / "scripts"
        self.clone.mkdir(parents=True)
        for n in sched.RUNTIME_SCRIPTS:
            (self.clone / n).write_text(f"# 假 {n}\n", encoding="utf-8")
        self.persist = Path(self.tmp.name) / ".pgh" / "scripts"
        self.patch = mock.patch.object(sched, "SCRIPTS_DIR", self.persist)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_install_copies_every_runtime_script(self):
        with mock.patch.object(sched, "__file__", str(self.clone / "install_schedule.py")):
            target, notes = sched.install_runtime_scripts("claude")
        self.assertEqual(target, self.persist / "claude")
        for n in sched.RUNTIME_SCRIPTS:
            self.assertTrue((self.persist / "claude" / n).exists(), f"{n} 没落到持久根")

    def test_wrapper_path_prefers_the_persistent_copy(self):
        """顺序不能反：先解析到源目录的 job 在 clone 删除后就成了每夜静默失败的排程。"""
        with mock.patch.object(sched, "__file__", str(self.clone / "install_schedule.py")):
            sched.install_runtime_scripts("claude")
            self.assertEqual(sched.wrapper_path("claude"),
                             self.persist / "claude" / sched.WRAPPER_NAME)

    def test_scripts_survive_clone_deletion(self):
        import shutil as _sh
        with mock.patch.object(sched, "__file__", str(self.clone / "install_schedule.py")):
            sched.install_runtime_scripts("claude")
        _sh.rmtree(self.clone.parent)
        self.assertFalse(self.clone.exists())
        for n in sched.RUNTIME_SCRIPTS:
            self.assertTrue((self.persist / "claude" / n).exists(),
                            f"clone 删掉后 {n} 也没了——改作息 / 卸载 / 验收全断路")
        self.assertEqual(sched.wrapper_path("claude"), self.persist / "claude" / sched.WRAPPER_NAME)

    def test_dry_run_copies_nothing(self):
        with mock.patch.object(sched, "__file__", str(self.clone / "install_schedule.py")):
            sched.install_runtime_scripts("claude", dry=True)
        self.assertFalse(self.persist.exists())

    def test_scheduled_cmd_points_at_the_wrapper_not_the_cli(self):
        """装进排程的必须是包装器——它是自然运行凭据的唯一来源。"""
        with mock.patch.object(sched, "__file__", str(self.clone / "install_schedule.py")):
            sched.install_runtime_scripts("claude")
            with mock.patch.object(sched, "_find_exe", return_value="/x/claude"):
                cmd = sched.scheduled_cmd("claude", Path("/tmp/root"), False)
        self.assertIn(sched.WRAPPER_NAME, cmd)
        self.assertIn(str(self.persist), cmd)

    def test_falls_back_to_direct_cli_when_wrapper_absent(self):
        """包装器不在时降级直调 CLI：宁可少一层验收证据，也不要整个固化停摆。"""
        with mock.patch.object(sched, "wrapper_path",
                               return_value=self.persist / "nope.py"), \
             mock.patch.object(sched, "_find_exe", return_value="/x/claude"):
            cmd = sched.scheduled_cmd("claude", Path("/tmp/root"), False)
        self.assertNotIn(sched.WRAPPER_NAME, cmd)
        self.assertIn("/x/claude", cmd)


class PerRuntimeStateTest(unittest.TestCase):
    """两端同机并存：收据、日志、验收状态必须各自独立。

    共用一份的失败形态很安静：先装 Claude 再装 Codex，第二次安装把第一份收据连同
    `acceptance` 里已经验过的位一起覆盖掉，于是「Claude 那端首跑已验证」这条实证
    凭空消失，week-sync 会去重复核一件早就核过的事；卸载任一端又会把另一端的验收
    状态删掉。日志混在一个文件里则分不清哪趟是哪端跑的。
    """

    def test_receipt_paths_differ_by_runtime(self):
        self.assertNotEqual(sched.receipt_path("claude"),
                            sched.receipt_path("codex"))

    def test_log_paths_differ_by_runtime(self):
        self.assertNotEqual(sched.log_path("claude"), sched.log_path("codex"))

    def test_legacy_shared_paths_are_not_reused(self):
        """v6.2.0 之前两端共用的那两个路径不能再被写入。"""
        for rt in ("claude", "codex"):
            self.assertNotEqual(sched.receipt_path(rt), sched.LEGACY_RECEIPT)
            self.assertNotEqual(sched.log_path(rt), sched.LEGACY_LOG)

    def test_command_writes_to_per_runtime_log(self):
        with mock.patch.object(sched, "_find_exe", return_value="/x/cli"):
            claude = sched.runtime_cmd("claude", Path("/tmp/a"), False)
            codex = sched.runtime_cmd("codex", Path("/tmp/a"), False)
        self.assertIn("daily-dream.claude.log", claude)
        self.assertIn("daily-dream.codex.log", codex)


class DualInstallTest(unittest.TestCase):
    """装第二端不许动第一端的验收状态；卸载一端不许删另一端的。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pgh = Path(self.tmp.name) / ".pgh"
        self.pgh.mkdir(parents=True)
        self.patch = mock.patch.object(
            sched, "receipt_path",
            lambda rt: self.pgh / f"schedule_receipt.{rt}.json")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def seed(self, rt: str, verified: bool):
        sched.write_receipt(runtime=rt, payload={
            "state": "READY", "runtime": rt, "boundary_hour": 4,
            "acceptance": {"first_run_verified": verified,
                           "first_weekly_run_verified": verified},
        })

    def read(self, rt: str) -> dict:
        return json.loads(sched.receipt_path(rt).read_text(encoding="utf-8"))

    def test_second_install_does_not_clobber_first_acceptance(self):
        self.seed("claude", True)
        self.seed("codex", False)          # 模拟后装 Codex
        self.assertTrue(self.read("claude")["acceptance"]["first_run_verified"],
                        "装 Codex 把 Claude 已验过的首跑状态写没了")
        self.assertFalse(self.read("codex")["acceptance"]["first_run_verified"])

    def test_uninstalling_one_runtime_keeps_the_other_receipt(self):
        self.seed("claude", True)
        self.seed("codex", True)
        # 卸载路径只删本 runtime 的收据（对应 main() 里的 unlink）。
        sched.receipt_path("codex").unlink()
        self.assertTrue(sched.receipt_path("claude").exists(),
                        "卸载 Codex 把 Claude 的验收状态一起删了")
        self.assertTrue(self.read("claude")["acceptance"]["first_run_verified"])


class SchedulerProofTest(unittest.TestCase):
    """A11：只有当次安装写进 job 定义的 proof 才能让包装器声称自然触发。

    包装器早先只要跑起来就写 `source=os-scheduler`——于是 sentinel 只能证明「包装器跑
    过」，而手工敲一条命令也能让它跑起来。首跑验收要回答的恰恰是「OS job 到点自己触发
    过吗」，两者必须能分开。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pgh = Path(self.tmp.name) / ".pgh"
        self.pgh.mkdir()
        self.gen = sched.new_generation()
        self.proof = sched.new_proof()
        # 包装器与安装器各有一份 PGH_DIR，两处都要换掉，否则会读到真实收据。
        self.env = mock.patch.object(wrapper, "PGH_DIR", self.pgh)
        self.env.start()
        self.addCleanup(self.env.stop)
        # 安装器侧也换掉：不换的话 `scheduled_cmd` 会往真实 `~/.pgh/` 里找脚本与日志，
        # 测试就会读写用户的真实排程状态——单测污染真实状态是不可接受的，哪怕只是读。
        for name, val in (("PGH_DIR", self.pgh),
                          ("SCRIPTS_DIR", self.pgh / "scripts")):
            pt = mock.patch.object(sched, name, val)
            pt.start()
            self.addCleanup(pt.stop)
        # 假可执行文件：拼命令不需要本机真装了 CLI（见 CommandBuildTest 的理由）。
        pe = mock.patch.object(sched, "_find_exe", lambda n, extra: f"/fake/bin/{n}")
        pe.start()
        self.addCleanup(pe.stop)

    def write_receipt(self, runtime="claude", **kw):
        payload = {"job_generation": self.gen,
                   "scheduler_proof_sha256": sched.proof_hash(self.proof, self.gen)}
        payload.update(kw)
        (self.pgh / f"schedule_receipt.{runtime}.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def classify(self, runtime="claude", **env):
        with mock.patch.dict("os.environ", env, clear=False):
            return wrapper.classify_source(runtime)

    def test_generation_and_proof_are_fresh_each_call(self):
        """每次安装换一代。不换的话重装后旧 job 的 sentinel 仍然算数。"""
        self.assertNotEqual(sched.new_generation(), sched.new_generation())
        self.assertNotEqual(sched.new_proof(), sched.new_proof())
        self.assertGreater(len(sched.new_proof()), 30)

    def test_hash_binds_proof_to_its_generation(self):
        """hash 必须把两者绑一起。只摘要 proof 的话，把上一次的 proof 配上新
        generation 也能算出旧 hash，重装等于白做。"""
        self.assertNotEqual(sched.proof_hash("p", "g1"), sched.proof_hash("p", "g2"))

    def test_receipt_never_stores_the_proof_itself(self):
        """收据里只留 hash。收据是给人看的诊断文件，写进 secret 等于把它公开一份。"""
        self.write_receipt()
        body = (self.pgh / "schedule_receipt.claude.json").read_text()
        self.assertNotIn(self.proof, body)
        self.assertIn(sched.proof_hash(self.proof, self.gen), body)

    def test_matching_proof_yields_natural_source(self):
        self.write_receipt()
        src, fields, why, _pf = self.classify(
            **{sched.PROOF_ENV: self.proof, sched.GEN_ENV: self.gen})
        self.assertEqual(src, wrapper.NATURAL_SOURCE, why)
        self.assertTrue(fields["proof_ok"])
        self.assertEqual(fields["job_generation"], self.gen)

    def test_direct_run_without_env_is_manual(self):
        """手工直接跑包装器：环境里没有 proof，只能记 manual-wrapper。

        这条是 A11 的核心。放行它就等于把「测过包装器能跑」当成「排程夜里跑过」。
        """
        self.write_receipt()
        src, fields, why, _pf = self.classify()
        self.assertEqual(src, wrapper.MANUAL_SOURCE, why)
        self.assertFalse(fields["proof_ok"])
        self.assertNotIn("proof_sha256", fields)

    def test_wrong_proof_is_manual(self):
        self.write_receipt()
        src, _, why, _pf = self.classify(
            **{sched.PROOF_ENV: "not-the-proof", sched.GEN_ENV: self.gen})
        self.assertEqual(src, wrapper.MANUAL_SOURCE, why)
        self.assertIn("hash 不符", why)

    def test_stale_generation_is_manual(self):
        """重装后旧 job 又触发了一次：它证明不了新 job 的状态。"""
        self.write_receipt()
        src, fields, why, _pf = self.classify(
            **{sched.PROOF_ENV: self.proof, sched.GEN_ENV: "20260101T000000-dead"})
        self.assertEqual(src, wrapper.MANUAL_SOURCE, why)
        self.assertIn("generation 不符", why)
        # generation 仍要写进 sentinel，好让验收器说得出是哪一代。
        self.assertEqual(fields["job_generation"], "20260101T000000-dead")

    def test_proof_from_the_other_runtime_is_manual(self):
        """两端各有 generation 与收据。Codex 那条不能给 Claude 的验收充数。"""
        self.write_receipt("claude")
        other_gen, other_proof = sched.new_generation(), sched.new_proof()
        self.write_receipt("codex", job_generation=other_gen,
                           scheduler_proof_sha256=sched.proof_hash(other_proof,
                                                                   other_gen))
        src, _, why, _pf = self.classify(
            "claude", **{sched.PROOF_ENV: other_proof, sched.GEN_ENV: other_gen})
        self.assertEqual(src, wrapper.MANUAL_SOURCE, why)

    def test_missing_receipt_is_manual_not_natural(self):
        """收据没了就无法校验。无法判定不等于判定通过。"""
        src, _, why, _pf = self.classify(
            **{sched.PROOF_ENV: self.proof, sched.GEN_ENV: self.gen})
        self.assertEqual(src, wrapper.MANUAL_SOURCE, why)
        self.assertIn("找不到收据", why)

    def test_legacy_receipt_without_proof_fields_is_manual(self):
        self.write_receipt(job_generation=None, scheduler_proof_sha256=None)
        src, _, why, _pf = self.classify(
            **{sched.PROOF_ENV: self.proof, sched.GEN_ENV: self.gen})
        self.assertEqual(src, wrapper.MANUAL_SOURCE, why)
        self.assertIn("旧版安装器", why)

    def test_installed_command_carries_the_proof(self):
        """proof 必须真的进到 job 命令里，否则排程跑起来也拿不到它。"""
        cmd = sched.scheduled_cmd("claude", Path("/tmp/a"), False,
                                  allow_missing_exe=True,
                                  proof=self.proof, generation=self.gen)
        self.assertIn(f"{sched.PROOF_ENV}=", cmd)
        self.assertIn(self.gen, cmd)

    def test_command_without_proof_pair_stays_clean(self):
        """反向哨兵：不给 proof 时命令里不能凭空出现这两个环境变量。"""
        cmd = sched.scheduled_cmd("claude", Path("/tmp/a"), False,
                                  allow_missing_exe=True)
        self.assertNotIn(sched.PROOF_ENV, cmd)
        self.assertNotIn(sched.GEN_ENV, cmd)


class ScheduledAtFieldTest(unittest.TestCase):
    """`scheduled_at` = job 定义声明的**名义触发时刻**，只由排程触发那一档产出。

    与 `fired_at`（实际开跑墙钟）并列而非替代：唤醒补触发时两者能差几个小时，而
    「排程按它自己声明的时刻在跑吗」只有名义时刻答得上。

    关键约束是来源——**名义时刻只能来自 job 定义**。若让包装器自己去读收据里的
    `dream_time`，那么手工跑包装器的进程也读得到（收据是本机可读的普通 json），于是
    `scheduled_at` 会在手工路径上一样被填满，这个字段就退化成又一个 `fired_at`。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pgh = Path(self.tmp.name) / ".pgh"
        self.pgh.mkdir()
        self.gen = sched.new_generation()
        self.proof = sched.new_proof()
        for mod, name, val in ((wrapper, "PGH_DIR", self.pgh),
                               (sched, "PGH_DIR", self.pgh),
                               (sched, "SCRIPTS_DIR", self.pgh / "scripts")):
            pt = mock.patch.object(mod, name, val)
            pt.start()
            self.addCleanup(pt.stop)
        pe = mock.patch.object(sched, "_find_exe", lambda n, extra: f"/fake/bin/{n}")
        pe.start()
        self.addCleanup(pe.stop)
        (self.pgh / f"schedule_receipt.claude.json").write_text(json.dumps({
            "job_generation": self.gen,
            "scheduler_proof_sha256": sched.proof_hash(self.proof, self.gen),
            "dream_time": "06:30",
        }), encoding="utf-8")

    FIRED = datetime.datetime(2026, 8, 1, 6, 30, 12,
                              tzinfo=datetime.timezone.utc)

    def sched_at(self, source=wrapper.NATURAL_SOURCE, fired=None, **env):
        with mock.patch.dict("os.environ", env, clear=False):
            return wrapper.scheduled_at_for(fired or self.FIRED, source)

    def built_record(self) -> dict:
        """真跑一趟包装器 `main()`，回读它实际落盘的那条 sentinel。

        断言落在**产物**上而不是构造函数上：字段名拼错、或忘了把它并进 sentinel dict，
        都只在读产物时才现形。
        """
        env = {sched.PROOF_ENV: self.proof, sched.GEN_ENV: self.gen,
               sched.SCHED_TIME_ENV: "06:30"}
        argv = ["run_scheduled_dream.py", "--runtime", "claude",
                "--assistant-root", self.tmp.name]
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch("sys.argv", argv), \
             mock.patch.object(wrapper.sched, "runtime_cmd",
                               lambda *a, **k: "true"), \
             mock.patch.object(wrapper.sched, "log_path",
                               lambda rt: self.pgh / f"d.{rt}.log"), \
             mock.patch.object(wrapper.subprocess, "run",
                               lambda *a, **k: SimpleNamespace(returncode=0)):
            wrapper.main()
        lines = (self.pgh / "natural_runs.claude.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        self.assertTrue(lines, "包装器没写出 sentinel")
        return json.loads(lines[-1])

    # ── 正测 ────────────────────────────────────────────────────────────────
    def test_natural_run_records_a_non_null_scheduled_at(self):
        """正测：自然触发 + job 里带名义时刻 → 字段在场且非空。"""
        got = self.sched_at(**{sched.SCHED_TIME_ENV: "06:30"})
        self.assertIsNotNone(got)
        self.assertTrue(got)
        self.assertIn("06:30", got)

    def test_the_key_is_spelled_scheduled_underscore_at(self):
        """字面键名必须是 scheduled + 下划线 + at，且值非空。

        拼错不会报错——验收器读不到就当旧记录放行，于是整条链看起来正常。
        """
        rec = self.built_record()
        self.assertIn("scheduled_at", rec)
        self.assertIsNotNone(rec["scheduled_at"])

    def test_fired_at_is_kept_for_compatibility(self):
        """`fired_at` 必须原样保留：旧收据、旧验收路径、日志段头都在读它。"""
        rec = self.built_record()
        self.assertIn("fired_at", rec)
        self.assertIsNotNone(rec["fired_at"])

    def test_scheduled_at_differs_from_fired_at_on_catch_up(self):
        """唤醒补触发：名义 06:30、实际 09:14 → 两个字段必须记成不同的值。

        相等就说明实现拿 `fired_at` 顶替了名义时刻，那样这个字段什么也没多证明。
        """
        late = self.FIRED.replace(hour=9, minute=14)
        got = self.sched_at(fired=late, **{sched.SCHED_TIME_ENV: "06:30"})
        self.assertNotEqual(got, late.isoformat(timespec="seconds"))
        self.assertIn("06:30", got)

    def test_nominal_time_rolls_back_a_day_when_catch_up_crosses_midnight(self):
        """错过的 06:30 在次日 00:10 被补上：名义时刻属于**前一天**。

        不回退的话名义时刻会落在实际触发之后近 24 小时，比对当前 job 时刻虽仍相等，
        但写进收据的是一个未来时刻。
        """
        fired = datetime.datetime(2026, 8, 2, 0, 10, tzinfo=datetime.timezone.utc)
        got = self.sched_at(fired=fired, **{sched.SCHED_TIME_ENV: "06:30"})
        self.assertTrue(got.startswith("2026-08-01T06:30"), got)

    def test_a_few_seconds_of_clock_skew_does_not_roll_the_date_back(self):
        """06:29:59 触发、名义 06:30 → 仍算**当天**那个点。

        没有余量的话一秒的墙钟抖动会让名义日期整整回退一天，而回退后的时刻与 job 声明
        的时刻仍然相等，故交叉核对看不出来，只有收据里的日期会莫名早一天。
        """
        fired = datetime.datetime(2026, 8, 1, 6, 29, 59,
                                  tzinfo=datetime.timezone.utc)
        got = self.sched_at(fired=fired, **{sched.SCHED_TIME_ENV: "06:30"})
        self.assertTrue(got.startswith("2026-08-01T06:30"), got)

    def test_a_job_run_much_earlier_than_nominal_is_treated_as_yesterdays(self):
        """反向哨兵：余量不能宽到把「早了几小时」也算成当天。

        排程不会提前跑，故 02:00 触发 / 名义 06:30 只能是补前一天那趟；把它算成当天
        会写出一个晚于实际触发四小时的「名义时刻」。
        """
        fired = datetime.datetime(2026, 8, 1, 2, 0, tzinfo=datetime.timezone.utc)
        got = self.sched_at(fired=fired, **{sched.SCHED_TIME_ENV: "06:30"})
        self.assertTrue(got.startswith("2026-07-31T06:30"), got)

    # ── 负测 ────────────────────────────────────────────────────────────────
    def test_manual_wrapper_never_gets_a_scheduled_at(self):
        """**核心负测**：手工跑包装器不得产出名义时刻，即使环境里塞了值。

        放行等于让「排程到点触发过」这句话可以由手工路径自证。
        """
        self.assertIsNone(self.sched_at(source=wrapper.MANUAL_SOURCE,
                                        **{sched.SCHED_TIME_ENV: "06:30"}))

    def test_no_job_time_in_env_yields_none_not_a_guess(self):
        """自然触发但环境里没有名义时刻（旧安装器装的 job）→ 留空，不猜。

        用收据里的 `dream_time` 补一个值会让手工跑也能填满这个字段。
        """
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(wrapper.scheduled_at_for(
                self.FIRED, wrapper.NATURAL_SOURCE))

    def test_malformed_job_time_is_rejected_not_coerced(self):
        for bad in ("", "  ", "6h30", "25:00", "06:61", "abc"):
            self.assertIsNone(self.sched_at(**{sched.SCHED_TIME_ENV: bad}), bad)

    def test_the_wrapper_does_not_read_the_receipt_for_the_nominal_time(self):
        """机械判据：包装器源码里不得出现 `dream_time`。

        收据本机可读，任何手工进程都拿得到它；从那里取名义时刻等于把「只有排程知道」
        这条前提取消掉，而字段照样填满，谁也不会发现。
        """
        src = Path(wrapper.__file__).read_text(encoding="utf-8")
        self.assertNotIn("dream_time", src,
                         "包装器从收据取名义时刻了——手工跑也能填满 scheduled_at")

    # ── 命令注入 ────────────────────────────────────────────────────────────
    def test_installed_command_carries_the_nominal_time(self):
        cmd = sched.scheduled_cmd("claude", Path("/tmp/a"), False,
                                  allow_missing_exe=True, proof=self.proof,
                                  generation=self.gen, sched_time="04:30")
        self.assertIn(f"{sched.SCHED_TIME_ENV}=", cmd)
        self.assertIn("04:30", cmd)

    def test_command_without_the_pair_has_no_nominal_time(self):
        """反向哨兵：不给 proof 时不得凭空出现名义时刻变量。"""
        cmd = sched.scheduled_cmd("claude", Path("/tmp/a"), False,
                                  allow_missing_exe=True, sched_time="04:30")
        self.assertNotIn(sched.SCHED_TIME_ENV, cmd)

    def test_installed_sched_time_reads_it_back(self):
        cmd = sched.scheduled_cmd("claude", Path("/tmp/a"), False,
                                  allow_missing_exe=True, proof=self.proof,
                                  generation=self.gen, sched_time="04:30")
        with mock.patch.object(sched, "installed_command", lambda rt: cmd):
            self.assertEqual(sched.installed_sched_time("claude"), "04:30")

    def test_installed_sched_time_reads_the_cmd_exe_shape(self):
        """Windows 形状 `set "VAR=v"` 也要认——只认一种会让那个平台恒红。"""
        cmd = (f'set "{sched.PROOF_ENV}=p" && set "{sched.GEN_ENV}=g" && '
               f'set "{sched.SCHED_TIME_ENV}=02:30" && cd /d C:\\x && py w.py')
        with mock.patch.object(sched, "installed_command", lambda rt: cmd):
            self.assertEqual(sched.installed_sched_time("claude"), "02:30")

    def test_real_install_injects_the_derived_dream_time(self):
        """端到端：真装一趟，job 命令里的名义时刻必须等于推出来的固化时刻。

        写死一个常量、或忘了把推算结果传下去，都会在这里现形。
        """
        seen = {}
        real = sched.scheduled_cmd

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        root = Path(self.tmp.name) / "repo" / "assistant"
        (root / "MEMORY").mkdir(parents=True)
        (root / "MEMORY" / "00.memory_agent.md").write_text(LINE, encoding="utf-8")
        cfgdir = Path(self.tmp.name) / "repo" / ".claude"
        cfgdir.mkdir(parents=True)
        (cfgdir / "CLAUDE.md").write_text(LINE, encoding="utf-8")
        argv = ["install_schedule.py", "--runtime", "claude",
                "--boundary-hour", "3", "--dry-run",
                "--assistant-root", str(root)]
        with mock.patch.object(sched, "scheduled_cmd", spy), \
             mock.patch.object(sched, "check_power", lambda: (True, ["桩"])), \
             mock.patch("sys.argv", argv):
            rc = sched.main()
        self.assertIn(rc, (0, 1), "安装器没跑完")
        self.assertEqual(seen.get("sched_time"), "03:30")

    # ── MAC ────────────────────────────────────────────────────────────────
    def test_scheduled_at_is_covered_by_the_mac(self):
        """字段必须进签名集合：不签就等于允许在已签名的记录上贴任意名义时刻。"""
        self.assertIn("scheduled_at", sched.MAC_FIELDS)
        rec = {"runtime": "claude", "job_generation": self.gen,
               "scheduled_at": "2026-08-01T06:30:00+08:00",
               "fired_at": "2026-08-01T06:30:12+08:00", "exit": 0,
               "status": "ok", "label": "L", "finished_at": "x"}
        mac = sched.sentinel_mac(self.proof, self.gen, rec)
        tampered = dict(rec, scheduled_at="2026-08-01T02:30:00+08:00")
        self.assertFalse(sched.mac_matches(self.proof, self.gen, tampered, mac))

    def test_a_legacy_record_without_the_key_still_verifies(self):
        """向后兼容：旧 sentinel（没有该键）按旧集合复算，MAC 仍要认。

        判红等于让升级安装器把用户已经验过的首跑打回未验，那不是安全收益。
        """
        rec = {"runtime": "claude", "job_generation": self.gen,
               "fired_at": "2026-08-01T06:30:12+08:00", "finished_at": "x",
               "exit": 0, "status": "ok", "label": "L"}
        legacy_mac = sched.sentinel_mac(self.proof, self.gen, rec,
                                        sched.LEGACY_MAC_FIELDS)
        self.assertTrue(sched.mac_matches(self.proof, self.gen, rec, legacy_mac))

    def test_the_legacy_path_cannot_be_used_to_strip_a_signed_field(self):
        """反向哨兵：兼容回退只对「键不在场」开放。

        否则把签过名的 `scheduled_at` 删掉就能让记录按旧集合过签，等于该字段没签。
        """
        rec = {"runtime": "claude", "job_generation": self.gen,
               "scheduled_at": "2026-08-01T06:30:00+08:00",
               "fired_at": "2026-08-01T06:30:12+08:00", "finished_at": "x",
               "exit": 0, "status": "ok", "label": "L"}
        mac = sched.sentinel_mac(self.proof, self.gen, rec)
        stripped = {k: v for k, v in rec.items() if k != "scheduled_at"}
        self.assertFalse(sched.mac_matches(self.proof, self.gen, stripped, mac))

    def test_a_legacy_record_cannot_gain_a_forged_nominal_time(self):
        """往旧记录里贴一个名义时刻也过不了：有该键就一律按当前集合判。"""
        rec = {"runtime": "claude", "job_generation": self.gen,
               "fired_at": "2026-08-01T06:30:12+08:00", "finished_at": "x",
               "exit": 0, "status": "ok", "label": "L"}
        legacy_mac = sched.sentinel_mac(self.proof, self.gen, rec,
                                        sched.LEGACY_MAC_FIELDS)
        forged = dict(rec, scheduled_at="2026-08-01T06:30:00+08:00")
        self.assertFalse(sched.mac_matches(self.proof, self.gen, forged,
                                           legacy_mac))

    def test_legacy_field_set_is_the_current_one_minus_the_new_key(self):
        """反向哨兵：两个集合必须只差这一个键。

        漂开之后兼容回退会开始接受与当年签名无关的 payload。
        """
        self.assertEqual(tuple(f for f in sched.MAC_FIELDS
                               if f != "scheduled_at"),
                         sched.LEGACY_MAC_FIELDS)


class HermeticSuiteTest(unittest.TestCase):
    """本套件自身必须是 hermetic 的：不依赖本机装了什么，也不写用户的真实状态。

    这一组测的是**测试套件**，不是被测代码。理由是套件失去 hermetic 之后仍然报绿——
    「本机绿」会被当成「代码对」，而它实际只说明本机恰好装了那个 CLI；反过来它还会
    悄悄把脚本复制进用户真实的 `~/.pgh/scripts/`，覆盖现役排程脚本。两个后果都不报错。
    """

    def test_no_test_writes_into_the_real_pgh_dir(self):
        """凡是会落盘到 `~/.pgh` 的路径常量，测试里必须都换成临时目录。

        判据机械化：模块常量指向真实 HOME 时，`RollbackTest.run_main` 的 patch 表必须
        同时覆盖 `PGH_DIR` 与 `SCRIPTS_DIR`。少一个就会写穿。
        """
        src = Path(__file__).read_text(encoding="utf-8")
        harness = src[src.index("def run_main"):src.index("def record_restore")]
        for const in ("PGH_DIR", "SCRIPTS_DIR"):
            self.assertIn(f'"{const}"', harness,
                          f"run_main 没换掉 {const}，会写进真实 ~/.pgh")

    def test_command_tests_do_not_need_a_real_cli(self):
        """拼命令的测试必须假掉 `_find_exe`——干净 HOME / CI 上没有 claude 或 codex。"""
        src = Path(__file__).read_text(encoding="utf-8")
        body = src[src.index("class CommandBuildTest"):src.index("class ShutdownProbeTest")]
        self.assertIn("_find_exe", body, "CommandBuildTest 仍依赖本机真实 CLI")

    def test_scripts_dir_is_derived_from_pgh_dir(self):
        """反向哨兵：若哪天 SCRIPTS_DIR 改成独立配置，上面两条的假设就不成立了。"""
        self.assertTrue(str(sched.SCRIPTS_DIR).startswith(str(sched.PGH_DIR)),
                        "SCRIPTS_DIR 不再派生自 PGH_DIR，patch 策略需要同步更新")


class ExecutionShapeTest(unittest.TestCase):
    """**真跑一遍拼出来的命令**，看环境变量到不到被执行的那个进程里。

    A12#1 就是靠这一组才该被抓住的：早先拼成 `VAR=v cd <dir> && python wrapper`，字符串
    断言（「命令里含 PGH_SCHED_PROOF=」）全部通过——而 POSIX 前缀赋值只对紧随其后的那条
    命令（`cd`）生效，`&&` 之后的包装器环境里没有这两个变量。后果是每一趟自然触发都被
    判成 `manual-wrapper`，首跑验收永远翻不绿，而排程确实在跑、日志与探针都正常，故这个
    失败在任何地面证据上都看不出来。

    教训是通用的：命令是要被 shell **执行**的，故断言必须落在执行结果上，不是字符串形状上。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # 假包装器：把它看到的两个环境变量回显出来。
        self.fake = self.root / sched.WRAPPER_NAME
        self.fake.write_text(
            "import os\n"
            "print('PROOF=[%s] GEN=[%s]' % (os.environ.get('PGH_SCHED_PROOF',''),"
            " os.environ.get('PGH_JOB_GENERATION','')))\n", encoding="utf-8")
        self.log = self.root / "out.log"
        for name, val in (("wrapper_path", lambda rt: self.fake),
                          ("log_path", lambda rt: self.log),
                          ("_find_exe", lambda n, extra: f"/fake/bin/{n}")):
            pt = mock.patch.object(sched, name, val)
            pt.start()
            self.addCleanup(pt.stop)

    def build(self, proof="SEKRIT", generation="gen-1"):
        return sched.scheduled_cmd("claude", self.root, False,
                                   allow_missing_exe=True,
                                   proof=proof, generation=generation)

    def run_in(self, shell: str, cmd: str) -> str:
        if not Path(shell).exists():
            self.skipTest(f"本机没有 {shell}")
        self.log.write_text("", encoding="utf-8")
        subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        return self.log.read_text(encoding="utf-8").strip()

    def test_proof_reaches_the_wrapper_under_sh(self):
        out = self.run_in("/bin/sh", self.build())
        self.assertIn("PROOF=[SEKRIT]", out, f"sh 下 proof 没传到包装器：{out!r}")
        self.assertIn("GEN=[gen-1]", out)

    def test_proof_reaches_the_wrapper_under_zsh(self):
        out = self.run_in("/bin/zsh", self.build())
        self.assertIn("PROOF=[SEKRIT]", out, f"zsh 下 proof 没传到包装器：{out!r}")

    def test_proof_reaches_the_wrapper_under_bash(self):
        out = self.run_in("/bin/bash", self.build())
        self.assertIn("PROOF=[SEKRIT]", out, f"bash 下 proof 没传到包装器：{out!r}")

    def test_wrapper_actually_runs_in_the_assistant_root(self):
        """`cd` 必须真生效——包装器要在 assistant root 里跑。"""
        self.fake.write_text("import os\nprint('CWD=[%s]' % os.getcwd())\n",
                             encoding="utf-8")
        out = self.run_in("/bin/sh", self.build())
        self.assertIn(str(self.root.resolve()), out)

    def test_no_proof_means_empty_env_not_a_crash(self):
        """不给 proof 时命令仍要能跑——降级路径不能是崩溃。"""
        cmd = sched.scheduled_cmd("claude", self.root, False, allow_missing_exe=True)
        out = self.run_in("/bin/sh", cmd)
        self.assertIn("PROOF=[]", out)

    def test_values_with_shell_metacharacters_survive(self):
        """proof 是 `token_urlsafe`，可能含 `-` `_`；generation 含时间戳。加引号后
        必须原样到达——被 shell 拆开会让 hash 对不上，而表现同样是「判成手工补跑」。"""
        tricky = "a-b_c$notvar`echo x` d"
        out = self.run_in("/bin/sh", self.build(proof=tricky))
        self.assertIn(f"PROOF=[{tricky}]", out, f"引用被 shell 破坏：{out!r}")


class WindowsShapeTest(unittest.TestCase):
    """Windows 侧只能测形状与解析（本机跑不了 cmd.exe），但**必须**测到位。

    cmd.exe 不认 POSIX 前缀赋值：`VAR=v cmd` 在它眼里是要执行一个名叫 `VAR=v` 的程序。
    早先两端共用一套拼装，于是 Windows 上装出来的 job 从第一天起就跑不通。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # 包装器必须**真实存在**：`scheduled_cmd` 在它缺失时会降级成直调 CLI，于是
        # 整组 Windows 断言其实测的是降级路径——测试全绿而 Windows 形状根本没被覆盖。
        self.w = Path(self.tmp.name) / sched.WRAPPER_NAME
        self.w.write_text("# 假包装器\n", encoding="utf-8")

    def build(self, **kw):
        with mock.patch.object(sched.platform, "system", lambda: "Windows"), \
             mock.patch.object(sched, "wrapper_path", lambda rt: self.w), \
             mock.patch.object(sched, "log_path",
                               lambda rt: Path(self.tmp.name) / "log.txt"), \
             mock.patch.object(sched, "_find_exe", lambda n, extra: f"C:/bin/{n}.exe"):
            return sched.scheduled_cmd("claude", Path(self.tmp.name), False,
                                       allow_missing_exe=True,
                                       proof=kw.get("proof", "SEKRIT"),
                                       generation=kw.get("generation", "gen-1"))

    def test_uses_set_not_posix_prefix(self):
        cmd = self.build()
        self.assertIn(f'set "{sched.PROOF_ENV}=', cmd,
                      "Windows 命令没用 `set \"VAR=value\"`")
        self.assertNotRegex(cmd, rf"^{sched.PROOF_ENV}=",
                            "Windows 命令仍以 POSIX 前缀赋值开头")

    def test_assignments_are_chained_before_the_wrapper(self):
        cmd = self.build()
        self.assertLess(cmd.index("set "), cmd.index(sched.WRAPPER_NAME))

    def test_installed_proof_parses_the_windows_shape(self):
        """验收器必须能从这种形状里读回 proof 与 generation。

        只剥单引号的实现会让 `GEN="gen-1"` 与裸 `gen-1` 比不相等——Windows 上每次验收
        都判成「装的是别一代」，而 job 完全正常。
        """
        cmd = self.build()
        with mock.patch.object(sched, "installed_command", lambda rt: cmd):
            proof, gen = sched.installed_proof("claude")
        self.assertEqual(proof, "SEKRIT")
        self.assertEqual(gen, "gen-1")

    def test_task_xml_is_wellformed_and_carries_the_command(self):
        import xml.etree.ElementTree as ET
        xml = sched._task_xml(self.build(), 6, 30)
        root = ET.fromstring(xml)                 # 解析不了就是转义错了
        ns = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
        args = root.find(f".//{ns}Arguments").text
        self.assertIn(sched.WRAPPER_NAME, args)
        self.assertIn(sched.PROOF_ENV, args)

    def test_task_xml_time_round_trips_through_the_reader(self):
        """写进 XML 的时刻必须能被 `installed_hour_minute` 读回来——两边用同一个正则，
        故这条测的是「写的格式」与「读的格式」没有各写一套。"""
        xml = sched._task_xml("cmd", 3, 5)
        m = _re_search = __import__("re").search(
            r"<StartBoundary>\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", xml)
        self.assertEqual((int(m.group(1)), int(m.group(2))), (3, 5))

    def test_task_xml_sets_power_and_catchup_flags(self):
        """默认设置会让夜里静默漏跑，故三项必须写进 XML 本体，而不是靠事后改设置。"""
        xml = sched._task_xml("cmd", 6, 30)
        for flag in ("<DisallowStartIfOnBatteries>false",
                     "<WakeToRun>true", "<StartWhenAvailable>true"):
            self.assertIn(flag, xml, f"XML 缺 {flag}")

    def test_dry_run_output_redacts_the_proof(self):
        """打印的命令不得含 proof 明文——dry-run 输出会被贴进聊天、CI 日志与工单。"""
        cmd = self.build(proof="TOPSECRET")
        with mock.patch.object(sched.platform, "system", lambda: "Windows"):
            steps = sched.install_windows("claude", 6, 30, cmd, dry=True)
        joined = " ".join(steps)
        self.assertNotIn("TOPSECRET", joined, "dry-run 输出泄漏了 proof 明文")
        self.assertIn("<REDACTED>", joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
