#!/usr/bin/env python3
"""test_verify_first_run.py — verify_first_run.py 的回归套件

跑法：python3 test_verify_first_run.py

这个脚本的职责是「只在真跑成功过时才把待验位翻绿」。故两个方向都要测：
造齐证据必须能翻绿（否则它只是个永远报红的摆设），缺任一条必须报红。
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verify_first_run", Path(__file__).with_name("verify_first_run.py"))
vfr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vfr)

#: 包装器本体。取常量而不是在测里写字面量——两处各写一份的话，改了名字测还是绿的。
_wspec = importlib.util.spec_from_file_location(
    "run_scheduled_dream", Path(__file__).with_name("run_scheduled_dream.py"))
vfr_ws = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(vfr_ws)

SUNDAY = datetime.date(2026, 7, 26)          # 周日
WEEKDAY = datetime.date(2026, 7, 29)         # 周三


class LogicalDateTest(unittest.TestCase):
    def test_uses_dynamic_boundary_not_hardcoded_six(self):
        """日界线是部署者作息决定的，写死 06:00 会让早睡早起的人每天判错一天。

        02:00 睡 09:00 起的人日界线 06:00：他的 04:00 还算前一天。
        21:00 睡 04:00 起的人日界线 03:00：他的 04:00 已经是新的一天。
        同一个物理时刻，两人的逻辑日不同——这正是不能硬编码的原因。
        """
        t = datetime.datetime(2026, 7, 30, 4, 0)
        self.assertEqual(vfr.logical_date(t, 6), datetime.date(2026, 7, 29))
        self.assertEqual(vfr.logical_date(t, 3), datetime.date(2026, 7, 30))

    def test_boundary_hour_itself_belongs_to_the_new_day(self):
        t = datetime.datetime(2026, 7, 30, 3, 0)
        self.assertEqual(vfr.logical_date(t, 3), datetime.date(2026, 7, 30))

    def test_rejects_unusable_boundary_in_receipt(self):
        for bad in ({}, {"boundary_hour": "6"}, {"boundary_hour": 99}):
            with self.assertRaises(SystemExit):
                vfr.boundary_hour(bad)


class ScheduledTargetTest(unittest.TestCase):
    """验收器要核的是「排程那一趟处理的日子」，不是「验收此刻的逻辑日」。"""

    def test_first_human_session_after_boundary_targets_yesterday(self):
        """一日偏差的原始形态。

        日界线 06:00、固化 06:30。首个真人会话 09:00 打开时，`logical_date(now)`
        = 今天（08-01），而凌晨那趟处理的是 07-31。拿今天去查探针必然查不到，
        于是跑成功了也稳定报红。
        """
        now = datetime.datetime(2026, 8, 1, 9, 0)
        self.assertEqual(vfr.logical_date(now, 6), datetime.date(2026, 8, 1))
        self.assertEqual(vfr.latest_scheduled_target(now, 6, 6, 30),
                         datetime.date(2026, 7, 31))

    def test_session_before_todays_fire_falls_back_to_previous_run(self):
        """05:00 开会话时，今天 06:30 那趟还没跑——要核的是昨天 06:30 那趟，
        它处理的是前天。核一趟还没发生的运行只会报红。"""
        now = datetime.datetime(2026, 8, 1, 5, 0)
        self.assertEqual(vfr.latest_scheduled_target(now, 6, 6, 30),
                         datetime.date(2026, 7, 30))

    def test_right_after_fire_targets_the_just_closed_day(self):
        now = datetime.datetime(2026, 8, 1, 6, 35)
        self.assertEqual(vfr.latest_scheduled_target(now, 6, 6, 30),
                         datetime.date(2026, 7, 31))

    def test_early_riser_boundary_three(self):
        """日界线 03:00、固化 03:30。08:00 开会话 → 那趟处理 07-31。"""
        now = datetime.datetime(2026, 8, 1, 8, 0)
        self.assertEqual(vfr.latest_scheduled_target(now, 3, 3, 30),
                         datetime.date(2026, 7, 31))

    def test_month_boundary_crossing(self):
        """跨月：08-01 06:35 那趟处理 07-31，日期要真的回退一个月尾。"""
        now = datetime.datetime(2026, 8, 1, 6, 35)
        self.assertEqual(vfr.latest_scheduled_target(now, 6, 6, 30).month, 7)

    def test_year_boundary_crossing(self):
        now = datetime.datetime(2026, 1, 1, 6, 35)
        self.assertEqual(vfr.latest_scheduled_target(now, 6, 6, 30),
                         datetime.date(2025, 12, 31))

    def test_dream_time_read_from_receipt(self):
        self.assertEqual(vfr.dream_time_from_receipt(
            {"dream_time": "03:30", "boundary_hour": 3}), (3, 30))

    def test_dream_time_falls_back_to_boundary_plus_thirty(self):
        """收据缺 dream_time 时按「日界线 + 30 分钟」补，不能默认 06:30。"""
        self.assertEqual(vfr.dream_time_from_receipt({"boundary_hour": 2}), (2, 30))

    def test_dream_time_ignores_garbage(self):
        self.assertEqual(vfr.dream_time_from_receipt(
            {"dream_time": "半夜", "boundary_hour": 4}), (4, 30))


class EvidenceBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "assistant"
        (self.root / "MEMORY").mkdir(parents=True)
        (self.root / "00 Focus Zone" / "_归档").mkdir(parents=True)
        # 排程日志在 home 下，测试里换掉常量以免动到真实文件。
        self.log = Path(self.tmp.name) / "daily-dream.log"
        vfr.DREAM_LOG = self.log

    def seed_daily(self, d: datetime.date, *, probe=True, mlog=True, log=True):
        ds = d.isoformat()
        if probe:
            (self.root / "MEMORY" / "last_dream.md").write_text(ds, encoding="utf-8")
        if mlog:
            (self.root / "MEMORY" / "MEMORY_LOG.md").write_text(
                f"## {ds}\n代谢条目\n", encoding="utf-8")
        if log:
            # 用包装器真实写的段头格式。触发时刻在目标逻辑日的次日凌晨——
            # 排程在日界线 + 30 分钟跑，处理刚闭窗的那天。
            fire = d + datetime.timedelta(days=1)
            self.log.write_text(
                f"\n===== {fire.isoformat()} 06:30:00+0800 "
                f"pgh.daily-dream.claude 触发 =====\n[{ds}] daily-dream 跑完\n",
                encoding="utf-8")

    def seed_weekly(self, d: datetime.date, *, arch=True, wk=True):
        y, w, _ = d.isocalendar()
        want = f"{y}-W{w:02d}"
        if arch:
            (self.root / "00 Focus Zone" / "_归档" / f"{want}.md").write_text(
                "周归档\n", encoding="utf-8")
        if wk:
            (self.root / "长期记忆.md").write_text(f"### {want}\n周录\n",
                                                encoding="utf-8")


class DailyEvidenceTest(EvidenceBase):
    def test_full_evidence_passes(self):
        """造齐三条证据必须能翻绿——否则这个脚本只是个永远报红的摆设，
        待验位再也不会变成 true，等于没有消费者。"""
        self.seed_daily(WEEKDAY)
        ok, notes = vfr.check_daily_evidence(self.root, WEEKDAY)
        self.assertTrue(ok, notes)

    def test_probe_alone_is_not_enough(self):
        """只有探针不算跑成功：探针可能是补跑或手工写的。"""
        self.seed_daily(WEEKDAY, mlog=False, log=False)
        ok, _ = vfr.check_daily_evidence(self.root, WEEKDAY)
        self.assertFalse(ok)

    def test_log_alone_is_not_enough(self):
        """日志里有一行不代表链跑完了——中途失败也会留日志。"""
        self.seed_daily(WEEKDAY, probe=False, mlog=False)
        ok, _ = vfr.check_daily_evidence(self.root, WEEKDAY)
        self.assertFalse(ok)

    def test_wrong_date_does_not_pass(self):
        """证据是昨天的、要核的是今天 → 必须报红，不能拿旧证据充数。"""
        self.seed_daily(WEEKDAY)
        ok, _ = vfr.check_daily_evidence(self.root, WEEKDAY + datetime.timedelta(days=1))
        self.assertFalse(ok)

    def test_nothing_at_all_reports_never_ran(self):
        ok, notes = vfr.check_daily_evidence(self.root, WEEKDAY)
        self.assertFalse(ok)
        self.assertTrue(any("从未跑过" in n for n in notes))

    def _seed_log_fired_at(self, target: datetime.date, fire: datetime.datetime):
        """只铺日志，段头时刻由调用方指定；探针与 MEMORY_LOG 照常按 target 铺。"""
        self.seed_daily(target, log=False)
        self.log.write_text(
            f"\n===== {fire:%Y-%m-%d %H:%M:%S}+0800 "
            f"pgh.daily-dream.claude 触发 =====\n", encoding="utf-8")

    def test_catch_up_fire_before_boundary_still_counts(self):
        """**补触发必须算成功。**

        错过的触发在开机后补跑（systemd `Persistent=true` / 休眠唤醒），补跑时刻可能
        落在日界线之前：此时它的逻辑日 = 物理日 − 1，处理的目标日 = 物理日 − 2，段头
        日期因此是 target + 2。早先按「target 或 target + 1」的固定窗口放行，正好把这
        一类判成「排程可能根本没触发」——而留机方案里补触发恰恰最需要被认成成功。
        """
        fire = datetime.datetime.combine(WEEKDAY + datetime.timedelta(days=2),
                                         datetime.time(4, 5))
        self._seed_log_fired_at(WEEKDAY, fire)
        ok, notes = vfr.check_daily_evidence(self.root, WEEKDAY, 6)
        self.assertTrue(ok, notes)

    def test_fire_two_days_late_after_boundary_is_rejected(self):
        """同样是 target + 2 的段头，但落在日界线**之后** → 它处理的是 target + 1，
        不是 target。放行会让「隔天那趟」冒充「这一天跑过了」。"""
        fire = datetime.datetime.combine(WEEKDAY + datetime.timedelta(days=2),
                                         datetime.time(6, 30))
        self._seed_log_fired_at(WEEKDAY, fire)
        ok, _ = vfr.check_daily_evidence(self.root, WEEKDAY, 6)
        self.assertFalse(ok)

    def test_marker_matched_against_deployment_boundary(self):
        """段头换算用的是**部署者的日界线**，不是写死的 06。日界线 03 的部署者，
        03:30 那趟处理的是前一天；拿 06 去算会把它归到再往前一天。"""
        fire = datetime.datetime.combine(WEEKDAY + datetime.timedelta(days=1),
                                         datetime.time(3, 30))
        self._seed_log_fired_at(WEEKDAY, fire)
        self.assertTrue(vfr.check_daily_evidence(self.root, WEEKDAY, 3)[0])
        self.assertFalse(vfr.check_daily_evidence(self.root, WEEKDAY, 6)[0])


class WeeklyEvidenceTest(EvidenceBase):
    def test_sunday_with_full_evidence_passes(self):
        self.seed_weekly(SUNDAY)
        ok, notes = vfr.check_weekly_evidence(self.root, SUNDAY)
        self.assertTrue(ok, notes)

    def test_weekday_target_is_not_a_failure(self):
        """目标日不是周日时周段本就不该跑，不能报成失败。"""
        ok, notes = vfr.check_weekly_evidence(self.root, WEEKDAY)
        self.assertFalse(ok)
        self.assertTrue(any("不构成失败" in n for n in notes))

    def test_daily_evidence_does_not_satisfy_weekly(self):
        """周段有自己的产物（周归档 + 周录）。拿 daily 的证据顶替会把
        「日跑通了、周段从没跑过」报成全绿，而周段是账实核对与衰减的唯一执行者。"""
        self.seed_daily(SUNDAY)
        ok, _ = vfr.check_weekly_evidence(self.root, SUNDAY)
        self.assertFalse(ok)

    def test_archive_without_week_record_fails(self):
        self.seed_weekly(SUNDAY, wk=False)
        ok, _ = vfr.check_weekly_evidence(self.root, SUNDAY)
        self.assertFalse(ok)

    def test_iso_week_number_matches_archive_name(self):
        """归档名用 ISO 周号。用 `%W` 之类的其他周号会在跨年周对不上，
        表现是明明归档了却验不过。"""
        self.seed_weekly(SUNDAY)
        y, w, _ = SUNDAY.isocalendar()
        self.assertTrue(
            (self.root / "00 Focus Zone" / "_归档" / f"{y}-W{w:02d}.md").exists())


class NaturalRunSentinelTest(unittest.TestCase):
    """把「排程自己跑成功过」与「用户手工补跑过」区分开。

    地面证据（探针 / MEMORY_LOG / 日志）手工补跑也会全部写出来，故单靠它们两者同形。
    而后果不同：排程没装成时用户必须每天记着补，忘一次就静默丢一天——那正是首跑验收
    要拦住的失败。
    """

    BOUNDARY = 6
    TARGET = datetime.date(2026, 7, 31)
    FIRED = "2026-08-01T06:30:12+08:00"          # 目标日次日凌晨触发

    def rec(self, **kw):
        base = {"label": "pgh.daily-dream.claude", "runtime": "claude",
                "source": vfr.NATURAL_SOURCE, "fired_at": self.FIRED,
                "exit": 0, "status": "ok"}
        base.update(kw)
        return base

    def find(self, *records):
        return vfr.natural_run_for("claude", self.TARGET, self.BOUNDARY,
                                   runs=list(records))

    def test_clean_natural_run_is_accepted(self):
        hit, notes = self.find(self.rec())
        self.assertIsNotNone(hit, notes)

    def test_no_sentinel_at_all_is_not_green(self):
        hit, notes = self.find()
        self.assertIsNone(hit)
        self.assertTrue(any("没有自然运行记录" in n for n in notes))

    def test_manual_backfill_does_not_count(self):
        """手工补跑不经过包装器，写不出 `source=os-scheduler`。

        若放行，用户「每天开工手动补昨天」会把首跑验收翻绿，于是「排程根本没装成」
        这件事再也不会被发现。
        """
        hit, notes = self.find(self.rec(source="manual"))
        self.assertIsNone(hit)
        self.assertTrue(any("不是排程自然触发" in n for n in notes))

    def test_wrong_runtime_sentinel_does_not_count(self):
        """同机装了两端时，Codex 那趟不能给 Claude 的验收充数。"""
        hit, _ = self.find(self.rec(runtime="codex"))
        self.assertIsNone(hit)

    def test_nonzero_exit_is_diagnosable_but_not_green(self):
        """失败的运行要留可诊断记录——但不得翻绿。

        只记成功会让「每夜都触发、每夜都失败」看起来和「从没触发」一样。
        """
        hit, notes = self.find(self.rec(exit=1, status="failed"))
        self.assertIsNone(hit)
        self.assertTrue(any("自然触发了但失败" in n for n in notes))

    def test_status_ok_with_nonzero_exit_is_rejected(self):
        """两个字段都得对。只看一个的话，写坏 status 的实现能自证成功。"""
        hit, _ = self.find(self.rec(exit=2, status="ok"))
        self.assertIsNone(hit)

    def test_run_for_another_logical_day_does_not_count(self):
        """前天那趟跑成功了，不代表目标日这趟跑过。"""
        hit, notes = self.find(self.rec(fired_at="2026-07-30T06:30:00+08:00"))
        self.assertIsNone(hit)
        self.assertTrue(any("没有一趟处理" in n for n in notes))

    def test_corrupt_line_does_not_kill_the_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "natural_runs.claude.jsonl"
            path.write_text('{"broken\n' + json.dumps(self.rec()) + "\n",
                            encoding="utf-8")
            with unittest.mock.patch.object(vfr, "sentinel_path",
                                            lambda rt: path):
                runs = vfr.read_natural_runs("claude")
        self.assertEqual(len(runs), 1)


class SundayNaturalRunTest(EvidenceBase):
    """周段正测：第一个「目标逻辑日 = 周日」的自然运行（周一凌晨那趟）。"""

    def test_sunday_natural_run_with_full_evidence_passes(self):
        self.seed_weekly(SUNDAY)
        ok, notes = vfr.check_weekly_evidence(self.root, SUNDAY)
        self.assertTrue(ok, notes)
        hit, nat_notes = vfr.natural_run_for(
            "claude", SUNDAY, 6,
            runs=[{"label": "pgh.daily-dream.claude", "runtime": "claude",
                   "source": vfr.NATURAL_SOURCE, "exit": 0, "status": "ok",
                   "fired_at": "2026-07-27T06:30:00+08:00"}])   # 周一凌晨
        self.assertIsNotNone(hit, nat_notes)

    def test_preexisting_archive_without_natural_run_is_not_green(self):
        """周归档预先存在（上周手工归的），但周日那趟自然运行没发生 → 不许翻绿。"""
        self.seed_weekly(SUNDAY)
        hit, _ = vfr.natural_run_for("claude", SUNDAY, 6, runs=[])
        self.assertIsNone(hit)


class CanonNameTest(EvidenceBase):
    def test_finds_either_canon_name(self):
        for name in vfr.MEMORY_CANON_NAMES:
            p = self.root / "MEMORY" / name
            p.write_text("x", encoding="utf-8")
            self.assertEqual(vfr.find_memory_canon(self.root), p)
            p.unlink()

    def test_returns_none_when_absent(self):
        self.assertIsNone(vfr.find_memory_canon(self.root))


class ReceiptTest(unittest.TestCase):
    def test_missing_receipt_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                vfr.load_receipt(Path(d) / "nope.json")

    def test_corrupt_receipt_exits(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                vfr.load_receipt(p)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text(json.dumps({"boundary_hour": 4}), encoding="utf-8")
            self.assertEqual(vfr.boundary_hour(vfr.load_receipt(p)), 4)


class IanaHandoffTest(unittest.TestCase):
    """IANA 时区名从安装器交到验收器手里必须不掉。

    掉了不会报错：`verify()` 拿到 `None` 就退回本机 offset，跨 DST 的推算差一小时，而
    收据、job 定义、日志全都正常。故这一组测的是**交接**，不是格式。
    """

    def test_top_level_field_is_read(self):
        self.assertEqual(
            vfr.iana_tz_from_receipt({"timezone_iana": "America/New_York"}),
            "America/New_York")

    def test_nested_acceptance_is_read_for_already_installed_machines(self):
        """已装机器的收据只有 `acceptance.timezone_iana` 一份。不兜底读嵌套，等于在
        升级瞬间把它们的时区信息作废——而作废表现为安静退回默认时区。"""
        self.assertEqual(
            vfr.iana_tz_from_receipt(
                {"acceptance": {"timezone_iana": "America/New_York"}}),
            "America/New_York")

    def test_top_level_wins_over_nested(self):
        self.assertEqual(
            vfr.iana_tz_from_receipt({"timezone_iana": "Europe/Berlin",
                                      "acceptance": {"timezone_iana": "America/New_York"}}),
            "Europe/Berlin")

    def test_unresolved_is_not_a_zone_name(self):
        """Windows 上探测不到 IANA 名时收据里写的是 `UNRESOLVED`。把它当时区名传给
        `ZoneInfo()` 会抛异常，故必须折成 `None`。"""
        self.assertIsNone(vfr.iana_tz_from_receipt({"timezone_iana": "UNRESOLVED"}))
        self.assertEqual(
            vfr.iana_tz_from_receipt({"timezone_iana": "UNRESOLVED",
                                      "acceptance": {"timezone_iana": "America/New_York"}}),
            "America/New_York")

    def test_missing_and_blank_and_none_receipt(self):
        for bad in (None, {}, {"timezone_iana": ""}, {"timezone_iana": "   "},
                    {"timezone_iana": 42}, {"acceptance": "not-a-dict"}):
            self.assertIsNone(vfr.iana_tz_from_receipt(bad), bad)

    def test_installer_writes_the_zone_at_top_level(self):
        """安装器侧的对应半边：顶层必须有这个字段。

        只测验收器读得到是不够的——A13#2 的根因正是「读的一侧没问题、写的一侧根本没往
        顶层写」。两边各测一半才盖住整条交接。
        """
        import install_schedule as sched
        src = Path(sched.__file__).read_text(encoding="utf-8")
        head = src.split("write_receipt(runtime=a.runtime, payload={")[1]
        head = head.split("\n    })")[0]
        self.assertIn('"timezone_iana": sentinel["timezone_iana"]', head,
                      "收据顶层没写 timezone_iana——消费方会取到 None 并退回默认时区")

    def test_verifier_passes_the_zone_into_job_verification(self):
        """回查必须真的收到那个时区名。传 `None` 时 `verify()` 退回本机 offset，
        跨 DST 算出的下次触发差一小时，而它照样返回「已回查」。"""
        seen = {}

        def fake_verify(runtime, hh=None, mm=None, tz=None):
            seen.update(runtime=runtime, hh=hh, mm=mm, tz=tz)
            return True, "已回查", {"enabled": True, "installed_hour_minute": "04:30"}

        receipt = {"boundary_hour": 4, "dream_time": "04:30",
                   "timezone_iana": "America/New_York"}
        with unittest.mock.patch.object(vfr.sched, "verify", fake_verify), \
             unittest.mock.patch.object(vfr.sched, "installed_command", lambda rt: None):
            vfr.current_job_state("claude", None, receipt)
        self.assertEqual(seen["tz"], "America/New_York")
        self.assertEqual((seen["hh"], seen["mm"]), (4, 30))


class ProofBindingTest(unittest.TestCase):
    """A11：sentinel 必须绑定到**当前这一代 job**，否则它只证明「包装器跑过」。

    `run_scheduled_dream.py` 自己就能写 `source=os-scheduler`——手工敲一条命令也能让它
    跑起来。于是「排程到点自己触发了」和「有人手工跑了一趟包装器」在 sentinel 上同形。
    绑定 generation + proof hash 才能把两者分开。
    """

    BOUNDARY = 6
    TARGET = datetime.date(2026, 7, 31)
    FIRED = "2026-08-01T06:30:12+08:00"
    GEN = "20260801T063000-a1b2c3d4"
    PROOF = "test-proof-value-high-entropy"

    @property
    def HASH(self):
        return vfr.sched.proof_hash(self.PROOF, self.GEN)

    def receipt(self, **kw):
        base = {"job_generation": self.GEN, "scheduler_proof_sha256": self.HASH}
        base.update(kw)
        return base

    def rec(self, sign=True, **kw):
        base = {"label": "pgh.daily-dream.claude", "runtime": "claude",
                "source": vfr.NATURAL_SOURCE, "fired_at": self.FIRED,
                "finished_at": "2026-08-01T06:31:00+08:00",
                "exit": 0, "status": "ok",
                "job_generation": self.GEN, "proof_ok": True,
                "proof_sha256": self.HASH}
        base.update(kw)
        if sign:
            # 真排程会签名。负测里把 sign=False 传进来模拟手写的 JSONL。
            base["mac"] = vfr.sched.sentinel_mac(
                self.PROOF, str(base.get("job_generation") or ""), base)
        return base

    def live_cmd(self, gen=None, proof=None):
        return (f"cd '/tmp/a' && {vfr.sched.PROOF_ENV}='{proof or self.PROOF}' "
                f"{vfr.sched.GEN_ENV}='{gen or self.GEN}' python3 wrapper.py")

    def find(self, rec, receipt=None, cmd=None):
        with unittest.mock.patch.object(vfr.sched, "installed_command",
                                        lambda rt: cmd or self.live_cmd()):
            return vfr.natural_run_for("claude", self.TARGET, self.BOUNDARY,
                                       runs=[rec],
                                       receipt=self.receipt() if receipt is None
                                       else receipt)

    def test_matching_generation_and_proof_is_accepted(self):
        """正向：本代 generation + 相符 hash 必须能翻绿。

        缺了这条，下面所有负测都可能是「闸恒报红」造成的假绿。
        """
        hit, notes = self.find(self.rec())
        self.assertIsNotNone(hit, notes)
        self.assertTrue(any("proof 与本代收据相符" in n for n in notes))

    def test_direct_wrapper_run_without_proof_is_rejected(self):
        """手工直接跑包装器：环境里没有 proof，包装器降级为 manual-wrapper。"""
        hit, notes = self.find(self.rec(sign=False, source=vfr_ws.MANUAL_SOURCE,
                                        proof_ok=False, proof_sha256=None))
        self.assertIsNone(hit)
        self.assertTrue(any("不是排程自然触发" in n for n in notes))

    def test_wrong_proof_is_rejected(self):
        """proof 对不上收据 hash——可能来自另一端，或是伪造的。"""
        hit, notes = self.find(self.rec(sign=False, proof_sha256="0" * 64))
        self.assertIsNone(hit)
        self.assertTrue(any("proof 与当前收据不符" in n for n in notes))

    def test_stale_generation_after_reinstall_is_rejected(self):
        """重装换了 generation：上一代 job 留下的 sentinel 不能给新 job 充数。

        改作息就会重装。若旧 sentinel 仍算数，那么「新排程装坏了」会被旧证据盖住，
        而用户以为验收过了。
        """
        hit, notes = self.find(self.rec(sign=False,
                                        job_generation="20260715T060000-99999999"))
        self.assertIsNone(hit)
        self.assertTrue(any("上一代 job" in n for n in notes))

    def test_forged_source_without_proof_fields_is_rejected(self):
        """手工往 sentinel 里写一行 `source=os-scheduler`，但拿不出 proof。"""
        hit, notes = self.find(self.rec(sign=False, proof_ok=False,
                                        proof_sha256=None, job_generation=None))
        self.assertIsNone(hit)
        self.assertFalse(any("相符 ✓" in n for n in notes))

    def test_receipt_without_proof_fields_cannot_be_verified(self):
        """旧版安装器装的排程收据里没有这两个字段——那时无法判定，故不翻绿。

        不是把它当通过：无法判定与判定通过是两件事，混在一起等于默认放行。
        """
        hit, notes = self.find(self.rec(), receipt={"boundary_hour": 6})
        self.assertIsNone(hit)
        self.assertTrue(any("旧版安装器" in n for n in notes))

    def test_no_receipt_argument_keeps_the_old_looser_path(self):
        """反向哨兵：不传收据时只做原有三条判据，不因缺字段误报红。"""
        hit, _ = vfr.natural_run_for("claude", self.TARGET, self.BOUNDARY,
                                     runs=[self.rec(sign=False, job_generation=None,
                                                    proof_sha256=None)])
        self.assertIsNotNone(hit)


class CurrentJobStateTest(unittest.TestCase):
    """A11#2：验收当刻必须重新看一眼 job，不能只靠旧 sentinel。

    sentinel 记的是**过去某一刻**排程触发过。装完之后 job 被停用、被别的工具覆盖、
    或被改成指向临时 clone 里的脚本——这些都不会让旧 sentinel 消失。于是拿旧 sentinel
    就能把一个当下已经不跑的系统判成验收通过，而它从明天起每天静默丢一天。
    """

    GEN = "20260801T063000-a1b2c3d4"
    PROOF = "test-proof-value"

    def stub(self, *, enabled=True, cmd=None):
        """替掉两个平台探测函数。真装一个 job 来测会污染本机排程。"""
        if cmd is None:
            cmd = (f"{vfr.sched.PROOF_ENV}='{self.PROOF}' "
                   f"{vfr.sched.GEN_ENV}='{self.GEN}' "
                   f"python3 '{vfr.sched.scripts_dir_for('claude') / vfr.sched.WRAPPER_NAME}' "
                   f"--runtime claude --assistant-root '/tmp/a'")
        return (unittest.mock.patch.object(
                    vfr.sched, "verify",
                    lambda rt, *a, **k: (enabled, "stub", {"enabled": enabled})),
                unittest.mock.patch.object(
                    vfr.sched, "installed_command", lambda rt: cmd))

    def run_check(self, **kw):
        v, c = self.stub(**kw)
        with v, c:
            return vfr.current_job_state("claude", self.GEN)

    def test_healthy_job_passes(self):
        ok, notes = self.run_check()
        self.assertTrue(ok, notes)

    def test_disabled_job_fails_even_with_a_valid_sentinel(self):
        """job 被停用：昨夜跑过是真的，今晚不会跑也是真的。验收要报后者。"""
        ok, notes = self.run_check(enabled=False)
        self.assertFalse(ok)
        self.assertTrue(any("未启用" in n for n in notes))

    def test_command_drifted_away_from_the_wrapper_fails(self):
        """命令被改成直接调 CLI：以后再也写不出自然运行凭据。"""
        ok, notes = self.run_check(cmd="claude -p '/daily-dream' --dangerously-skip")
        self.assertFalse(ok)
        self.assertTrue(any(vfr.sched.WRAPPER_NAME in n for n in notes))

    def test_command_pointing_at_a_temp_clone_fails(self):
        """指向临时 clone：clone 一删就静默不跑，而删 clone 是部署流程里的正常动作。"""
        tmp = f"/tmp/pgh-clone/scripts/{vfr.sched.WRAPPER_NAME}"
        ok, notes = self.run_check(
            cmd=f"{vfr.sched.PROOF_ENV}='{self.PROOF}' "
                f"{vfr.sched.GEN_ENV}='{self.GEN}' python3 '{tmp}' --runtime claude")
        self.assertFalse(ok)
        self.assertTrue(any("持久根" in n for n in notes))

    def test_stale_generation_in_the_installed_command_fails(self):
        """job 命令里带的是上一代 generation——装的不是收据描述的那个 job。"""
        cmd = (f"{vfr.sched.PROOF_ENV}='{self.PROOF}' "
               f"{vfr.sched.GEN_ENV}='20260715T060000-99999999' "
               f"python3 '{vfr.sched.scripts_dir_for('claude') / vfr.sched.WRAPPER_NAME}' "
               f"--runtime claude")
        ok, notes = self.run_check(cmd=cmd)
        self.assertFalse(ok)
        self.assertTrue(any("generation" in n for n in notes))

    def test_unreadable_command_is_not_treated_as_ok(self):
        """读不到命令原文时不得放行——无法判定与判定通过是两件事。"""
        v, c = self.stub()
        with v, unittest.mock.patch.object(vfr.sched, "installed_command",
                                           lambda rt: None):
            ok, notes = vfr.current_job_state("claude", self.GEN)
        self.assertFalse(ok)
        self.assertTrue(any("读不到" in n for n in notes))


class ScheduledAtAcceptanceTest(unittest.TestCase):
    """验收侧的 `scheduled_at`：名义触发时刻要与**当前 job 声明的时刻**核得上。

    它与 `fired_at` 回答的是两个不同问题：后者是实际开跑的墙钟（唤醒补触发时能晚几个
    小时），前者是「排程本该几点跑」。只留 `fired_at` 时，「job 时刻被改过 / 记录来自
    另一个 job」这一类在凭据上看不出来——实际墙钟本来就允许漂。
    """

    BOUNDARY = 6
    TARGET = datetime.date(2026, 7, 31)
    FIRED = "2026-08-01T06:30:12+08:00"
    SCHED = "2026-08-01T06:30:00+08:00"
    GEN = "20260801T063000-a1b2c3d4"
    PROOF = "test-proof-value-high-entropy"

    @property
    def HASH(self):
        return vfr.sched.proof_hash(self.PROOF, self.GEN)

    def rec(self, sign=True, **kw):
        base = {"label": "pgh.daily-dream.claude", "runtime": "claude",
                "source": vfr.NATURAL_SOURCE, "scheduled_at": self.SCHED,
                "fired_at": self.FIRED,
                "finished_at": "2026-08-01T06:31:00+08:00",
                "exit": 0, "status": "ok",
                "job_generation": self.GEN, "proof_ok": True,
                "proof_sha256": self.HASH}
        base.update(kw)
        if sign:
            base["mac"] = vfr.sched.sentinel_mac(
                self.PROOF, str(base.get("job_generation") or ""), base)
        return base

    def find(self, rec, job_time="06:30"):
        cmd = (f"cd '/tmp/a' && {vfr.sched.PROOF_ENV}='{self.PROOF}' "
               f"{vfr.sched.GEN_ENV}='{self.GEN}' ")
        if job_time:
            cmd += f"{vfr.sched.SCHED_TIME_ENV}='{job_time}' "
        cmd += "python3 wrapper.py"
        with unittest.mock.patch.object(vfr.sched, "installed_command",
                                        lambda rt: cmd):
            return vfr.natural_run_for(
                "claude", self.TARGET, self.BOUNDARY, runs=[rec],
                receipt={"job_generation": self.GEN,
                         "scheduler_proof_sha256": self.HASH})

    # ── 正测 ────────────────────────────────────────────────────────────────
    def test_matching_nominal_time_is_accepted(self):
        """正测。缺了它，下面的负测可能是「闸恒红」造成的假绿。"""
        hit, notes = self.find(self.rec())
        self.assertIsNotNone(hit, notes)

    def test_acceptance_reports_the_nominal_time_non_null(self):
        """验收放行时必须把这个字段原样报出来，且非空。"""
        hit, _ = self.find(self.rec())
        self.assertIn("scheduled_at", hit)
        self.assertIsNotNone(hit["scheduled_at"])
        self.assertEqual(hit["scheduled_at"], self.SCHED)

    def test_both_fields_are_reported_side_by_side(self):
        """`fired_at` 必须仍在场——兼容口径，且两者内容不同。"""
        hit, _ = self.find(self.rec())
        self.assertIsNotNone(hit.get("fired_at"))
        self.assertNotEqual(hit["scheduled_at"], hit["fired_at"])

    # ── 负测 ────────────────────────────────────────────────────────────────
    def test_nominal_time_disagreeing_with_the_job_is_rejected(self):
        """记录说 06:30，job 现在装的是 04:30 → 判红。

        改过作息但没重装时正是这个形状：旧凭据描述的是一个已经不存在的排程。
        """
        hit, notes = self.find(self.rec(), job_time="04:30")
        self.assertIsNone(hit)
        self.assertTrue(any("与当前 job 声明的" in n for n in notes), notes)

    def test_unparsable_nominal_time_is_rejected(self):
        hit, notes = self.find(self.rec(scheduled_at="not-a-timestamp"))
        self.assertIsNone(hit)
        self.assertTrue(any("无法解析" in n for n in notes), notes)

    def test_non_string_nominal_time_is_rejected(self):
        hit, notes = self.find(self.rec(scheduled_at=630))
        self.assertIsNone(hit)
        self.assertTrue(any("不是时刻字符串" in n for n in notes), notes)

    def legacy_absent(self):
        """旧版包装器写的凭据：**键根本不在场**，MAC 按旧集合签。"""
        rec = self.rec(sign=False)
        rec.pop("scheduled_at")
        rec["mac"] = vfr.sched.sentinel_mac(self.PROOF, self.GEN, rec,
                                            vfr.sched.LEGACY_MAC_FIELDS)
        return rec

    def test_a_legacy_record_without_the_key_still_passes_with_a_note(self):
        """正测（唯一放行的兼容形状）：键不在场 → 放行，说明里点出来。

        判红等于让升级本身把用户已经验过的首跑打回未验，而那不是安全收益。
        """
        hit, notes = self.find(self.legacy_absent())
        self.assertIsNotNone(hit, notes)
        self.assertTrue(any("没有 scheduled_at 键" in n for n in notes), notes)

    def test_legacy_absent_key_passes_even_with_no_job_time_installed(self):
        """兼容形状在「job 里也读不到名义时刻」时同样放行——两者本来同源。"""
        hit, notes = self.find(self.legacy_absent(), job_time=None)
        self.assertIsNotNone(hit, notes)

    # ── 键在场但值为空：与「键不在场」不是同一件事 ──────────────────────────
    def test_present_but_null_is_rejected(self):
        """**核心负测**：键在场而值是 null → 判红，验收保持待验。

        本代包装器无条件写这个键，故这个形状意味着自然触发时 job 定义里没有名义时刻
        （脚本升过级但 job 没重装）。放行它等于让一条不含名义时刻的新凭据把
        `first_run_verified` 翻成 true——而该字段的全部理由就是证明排程按它声明的时刻在跑。
        """
        hit, notes = self.find(self.rec(scheduled_at=None))
        self.assertIsNone(hit)
        self.assertTrue(any("空值" in n for n in notes), notes)

    def test_present_but_empty_string_is_rejected(self):
        hit, notes = self.find(self.rec(scheduled_at=""))
        self.assertIsNone(hit)
        self.assertTrue(any("空值" in n for n in notes), notes)

    def test_present_but_whitespace_only_is_rejected(self):
        hit, notes = self.find(self.rec(scheduled_at="   "))
        self.assertIsNone(hit)
        self.assertTrue(any("空值" in n for n in notes), notes)

    def test_present_null_stays_rejected_with_no_job_time_installed(self):
        """读不到 job 里的名义时刻**不能**把「键在场而值空」救回来。

        两条判据各自独立：前者只是「无法交叉核对」，后者是「这条凭据本身不含名义时刻」。
        合流的话，把 job 换成不带该变量的旧命令就能让空值凭据翻绿。
        """
        hit, notes = self.find(self.rec(scheduled_at=None), job_time=None)
        self.assertIsNone(hit)
        self.assertTrue(any("空值" in n for n in notes), notes)

    def test_acceptance_stays_pending_on_a_null_nominal_time(self):
        """机械判据：空值那条不得放行，故 `first_run_verified` 无从被置 true。

        直接调判据函数，避免上一条的判红被别的原因（MAC / generation）顶替。
        """
        for bad in (None, "", "  "):
            with unittest.mock.patch.object(vfr.sched, "installed_sched_time",
                                            lambda rt: None):
                ok, note = vfr.scheduled_at_ok({"scheduled_at": bad}, "claude")
            self.assertFalse(ok, f"{bad!r} 被放行了")
            self.assertIn("空值", note or "")

    def test_the_two_compat_shapes_are_told_apart(self):
        """反向哨兵：兼容只对「键不在场」开放，两个形状必须判出不同结果。

        用 `in` 判空会把两者塌成一个，于是 null 值搭上兼容通道。
        """
        with unittest.mock.patch.object(vfr.sched, "installed_sched_time",
                                        lambda rt: None):
            absent_ok, _ = vfr.scheduled_at_ok({}, "claude")
            null_ok, _ = vfr.scheduled_at_ok({"scheduled_at": None}, "claude")
        self.assertTrue(absent_ok, "键不在场应放行（旧凭据）")
        self.assertFalse(null_ok, "键在场而值空应判红")

    def test_tampering_with_the_nominal_time_breaks_the_mac(self):
        """签名覆盖它：把值改掉后 MAC 复算不上，故改不动。"""
        rec = self.rec()
        rec["scheduled_at"] = "2026-08-01T04:30:00+08:00"
        hit, notes = self.find(rec, job_time="04:30")
        self.assertIsNone(hit)
        self.assertTrue(any("MAC 复算不上" in n for n in notes), notes)

    def test_no_job_time_available_does_not_turn_the_gate_red(self):
        """job 命令里读不到名义时刻（旧 job）→ 不据此判红，交给「键缺失」那条。

        这里要防的是反向失效：把「读不到」当成「不符」会让所有旧 job 恒红。
        """
        hit, notes = self.find(self.rec(), job_time=None)
        self.assertIsNotNone(hit, notes)

    def test_the_gate_is_not_vacuous(self):
        """反向哨兵：`scheduled_at_ok` 必须真的在比对，而不是恒真。

        直接调它——名义时刻与 job 声明不同必须返回 False。上面那条负测若因为别的原因
        判红（比如 MAC），这条能把「闸恒真」单独钉出来。
        """
        with unittest.mock.patch.object(vfr.sched, "installed_sched_time",
                                        lambda rt: "04:30"):
            ok, note = vfr.scheduled_at_ok({"scheduled_at": self.SCHED}, "claude")
        self.assertFalse(ok)
        self.assertIn("04:30", note or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
