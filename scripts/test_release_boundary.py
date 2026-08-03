#!/usr/bin/env python3
"""test_release_boundary.py — 四个公开入口的发布边界闸

跑法：python3 test_release_boundary.py

四个仓同时挂在 GitHub 上，四个 README 长得像同一个系统的四个变体。新用户挑哪个装，
取决于他先点开哪个链接——而其中两个装完得到的是没有夜间固化的半截系统。

故边界必须机械可判：**两个 current 必须能走到动态作息排程链；两个 legacy 必须在
mutation 之前停下并重定向。** 「README 里提了一句」不可判定，「§-2 出现在 §-1 之前
且包含目标仓 URL」可判定。
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import unittest
import unittest.mock
from pathlib import Path

#: 本文件所在仓的根（`<repo>/scripts/test_release_boundary.py` → `<repo>`）。
SELF_ROOT = Path(__file__).resolve().parents[1]

#: 母版树的根（四仓 + `_shared` 的共同父目录）。**只在私区母版里存在。**
MOTHER_ROOT = Path(__file__).resolve().parents[2]

ALL_REPOS = ("PGH-dreaming", "PGH-dreaming-for-codex",
             "claude-code-harness", "codex-code-harness")


#: 母版树的权威哨兵：`_shared/init/` 母版正文。**按设计不随任何仓 push。**
MOTHER_SENTINEL = Path("_shared") / "init" / "schedule_interview.md"


def _in_mother_tree(root: Path | None = None) -> bool:
    """当前是不是跑在私区母版树里。

    判据 = 四仓齐备 **且** 私区母版哨兵在场。**这条判断决定闸的作用域**：公开仓被单独
    clone 时，同级没有兄弟仓、也没有 `_shared` 母版，按母版布局去读它们只会得到
    `FileNotFoundError`——而那是 error，与「契约真的坏了」在输出上同形。

    **只看四仓并排是不够的。** 维护者把四个公开仓 clone 进同一个文件夹是完全正常的用法，
    那个布局里没有 `_shared`；只按「四仓齐备」判定会把它当成母版树，随后去读一个不存在的
    母版文件而报 error。故母版的判据必须包含只有私区才有的那份哨兵。
    """
    root = MOTHER_ROOT if root is None else root
    return (all((root / r).is_dir() for r in ALL_REPOS)
            and (root / MOTHER_SENTINEL).is_file())


#: 作用域。母版树里 = 四仓全扫；单独 clone 里 = 只扫自己这一个仓。
IN_MOTHER = _in_mother_tree()

#: 仓根的解析基准。单独 clone 时把「仓名」映射到自己的根。
PGH = MOTHER_ROOT if IN_MOTHER else SELF_ROOT.parent


def repo_root(repo: str) -> Path:
    """仓名 → 磁盘路径。单独 clone 里只有自己这一个名字能解析。"""
    return (MOTHER_ROOT / repo) if IN_MOTHER else SELF_ROOT


CURRENT = {
    "PGH-dreaming": {
        "cfg": ".claude/CLAUDE.md",
        "runtime": "claude",
        "legacy_url": "https://github.com/Hang-Yuan/claude-code-harness",
    },
    "PGH-dreaming-for-codex": {
        "cfg": ".codex/AGENTS.md",
        "runtime": "codex",
        "legacy_url": "https://github.com/Hang-Yuan/codex-code-harness",
    },
}

LEGACY = {
    "claude-code-harness": {
        "cfg": ".claude/CLAUDE.md",
        "current_url": "https://github.com/Hang-Yuan/PGH-dreaming",
    },
    "codex-code-harness": {
        "cfg": ".codex/AGENTS.md",
        "current_url": "https://github.com/Hang-Yuan/PGH-dreaming-for-codex",
    },
}

BLOCK_MARK = "Legacy · no new installs"

#: 母版树里的四仓全表，留给「作用域自己」的回归用（见 ScopeResolutionTest）。
ALL_CURRENT, ALL_LEGACY = dict(CURRENT), dict(LEGACY)

def detect_self_role() -> str:
    """认出**本仓是四个发布包里的哪一个**，只看仓内内容。

    **不能用目录名判定。** `git clone <url> my-agent` 是完全正常的用法，目录名是用户
    的选择，不是包的属性。按 basename 匹配的话，任何非标准目录名都会让作用域筛成空集
    ——而空集不报错：所有 `for repo in CURRENT` 的循环体零次执行，套件全绿，闸实际什么
    都没查。空集比 error 更危险，因为它看起来是通过。

    判据取仓内不变量，两个维度正交：
      · 端（claude / codex）—— 看运行时目录哪个在场；
      · 线（现役 / 退役）—— 看 README 有没有退役阻断横幅。
    两者都是这个包的定义性内容：换掉任何一个，它就不再是那个发布包了。
    """
    is_legacy = False
    for name in ("README.md",):
        p = SELF_ROOT / name
        if p.exists() and BLOCK_MARK in p.read_text(encoding="utf-8",
                                                    errors="replace"):
            is_legacy = True
    claude = (SELF_ROOT / ".claude").is_dir()
    codex = (SELF_ROOT / ".codex").is_dir()
    if claude == codex:                      # 两个都有或都没有：认不出端
        return ""
    if codex:
        return "codex-code-harness" if is_legacy else "PGH-dreaming-for-codex"
    return "claude-code-harness" if is_legacy else "PGH-dreaming"


#: 单独 clone 时本仓扮演的角色（母版树里为空，因为那时四仓都在场、无需自指）。
SELF_ROLE = "" if IN_MOTHER else detect_self_role()

#: 本次运行**真正要判**的仓名。
#:
#: 单独 clone 里只剩自己那一个：同级没有兄弟仓，跨仓断言无从成立。早先无条件按四仓
#: 迭代，于是公开仓单独跑时 8 个 error + 34 个 skip——而发布验收要求零 error 零 skip，
#: 且 error 与真契约破损同形，看的人分不出哪个是真问题。
def _scoped(table: dict) -> dict:
    if IN_MOTHER:
        return dict(table)
    return {k: v for k, v in table.items() if k == SELF_ROLE}


CURRENT, LEGACY = _scoped(CURRENT), _scoped(LEGACY)


def read(repo: str, rel: str) -> str:
    p = repo_root(repo) / rel
    if not p.exists():
        raise unittest.SkipTest(f"缺 {repo}/{rel}")
    return p.read_text(encoding="utf-8", errors="replace")


class CurrentReposTest(unittest.TestCase):
    """两个现役仓必须真的能把新用户带到排程链上。"""

    def test_readme_asks_for_sleep_wake(self):
        """作息访谈是排程的输入。README 不问，用户就不知道要答。"""
        for repo in CURRENT:
            body = read(repo, "README.md")
            self.assertRegex(body, r"作息", f"{repo} README 没问作息")
            self.assertRegex(body, r"几点睡", f"{repo} README 没问入睡时间")
            self.assertRegex(body, r"几点起", f"{repo} README 没问起床时间")

    def test_readme_names_the_installer_command(self):
        """必须给出可复制的重装命令——改作息是常态，不是一次性动作。"""
        for repo in CURRENT:
            body = read(repo, "README.md")
            self.assertIn("install_schedule.py", body, f"{repo} 没给安装器命令")
            self.assertIn("--sleep", body)
            self.assertIn("--wake", body)

    def test_readme_points_at_the_persistent_script_root(self):
        """命令里的路径必须是持久根，不是临时 clone 里的相对路径。

        写 `python3 scripts/install_schedule.py` 的话，用户删掉 clone 之后照着 README
        敲会得到 FileNotFoundError，而那时他要做的恰恰是改作息或卸载。
        """
        for repo in CURRENT:
            body = read(repo, "README.md")
            self.assertRegex(body, r"~/\.pgh/scripts/(claude|codex)/install_schedule\.py",
                             f"{repo} 的安装器命令没指向按端分开的持久根")

    def test_readme_mentions_first_run_acceptance(self):
        """装好 ≠ 跑成功。不写这条，用户会把 READY 当成已经在跑。"""
        for repo in CURRENT:
            body = read(repo, "README.md")
            self.assertIn("verify_first_run.py", body,
                          f"{repo} 没提首跑验收")

    def test_readme_flags_the_legacy_repo_by_url(self):
        """必须写出旧仓的**具体 URL**。

        泛称「旧 PGH」不可执行：用户手上那个链接到底算不算旧的，他判断不了，AI 也判断
        不了。写死 URL 才能让两端都机械对上。
        """
        for repo, meta in CURRENT.items():
            body = read(repo, "README.md")
            self.assertIn(meta["legacy_url"], body,
                          f"{repo} 没点明旧仓 URL")
            self.assertRegex(body, r"禁止新装|不要用它做新部署",
                             f"{repo} 没说明旧仓禁止新装")

    def test_config_has_no_legacy_block(self):
        """反向哨兵：现役仓不能带阻断标记，否则新装会被自己挡住。"""
        for repo, meta in CURRENT.items():
            self.assertNotIn(BLOCK_MARK, read(repo, meta["cfg"]),
                             f"{repo} 的宪法层带了 legacy 阻断标记")

    def test_deploy_protocol_still_present(self):
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            self.assertIn("## §-1", body, f"{repo} 没有部署协议节")

    def test_config_carries_a_dynamic_boundary_not_a_constant(self):
        """宪法层的日界线必须标明是部署期写入的，不是模板里的定值。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            self.assertIn("install_schedule.py", body,
                          f"{repo} 宪法层没说明日界线由安装器写入")


class LegacyReposTest(unittest.TestCase):
    """两个 legacy 仓必须在 mutation 之前停下。"""

    def test_readme_carries_the_block_banner(self):
        for repo in LEGACY:
            body = read(repo, "README.md")
            self.assertIn(BLOCK_MARK, body, f"{repo} README 没有阻断横幅")

    def test_readme_redirects_to_the_current_repo(self):
        for repo, meta in LEGACY.items():
            self.assertIn(meta["current_url"], read(repo, "README.md"),
                          f"{repo} README 没给现役仓 URL")

    def test_runtime_config_blocks_before_the_deploy_protocol(self):
        """阻断节必须**排在** §-1 之前。

        顺序就是本条的全部内容。AI 顺序读文件，把阻断放在 §-1 之后等于让它先照着旧
        协议复制完文件、再看到「不该装」——那时该发生的已经发生了。
        """
        for repo, meta in LEGACY.items():
            body = read(repo, meta["cfg"])
            self.assertIn(BLOCK_MARK, body, f"{repo} 宪法层没有阻断节")
            # 锚在**标题**上，不是任意一处 `§-1` 字样。阻断节的正文里会引用 §-1
            # （「不执行 §-1 的任何步骤」），拿那次出现当基准会让顺序断言恒真。
            blk = body.index(BLOCK_MARK)
            dep = body.index("## §-1")
            self.assertLess(blk, dep,
                            f"{repo} 的阻断节排在部署协议之后，等于没拦住")

    def test_block_forbids_copying_before_redirect(self):
        """阻断文本必须明确「复制任何文件之前」——含糊的措辞挡不住动作。"""
        for repo, meta in LEGACY.items():
            body = read(repo, meta["cfg"])
            self.assertRegex(body, r"在复制任何文件.{0,20}之前",
                             f"{repo} 没写明在复制前就停")

    def test_deploy_protocol_is_marked_do_not_execute(self):
        for repo, meta in LEGACY.items():
            body = read(repo, meta["cfg"])
            start = body.index("## §-1")
            head = body[start:start + 400]
            self.assertRegex(head, r"已停用|不得执行",
                             f"{repo} 的 §-1 没标停用")

    def test_changelog_marks_the_line_retired(self):
        for repo, meta in LEGACY.items():
            body = read(repo, "CHANGELOG.md")
            self.assertIn(BLOCK_MARK, body, f"{repo} CHANGELOG 没标退役")
            self.assertIn(meta["current_url"], body)

    def test_history_is_preserved_not_deleted(self):
        """反向哨兵：退役不是删除。

        旧仓要留着——存量用户还在跑它，迁移也要拿它当取证源。把它删掉会让「我装的到底
        是哪一版」变成无法回答的问题。
        """
        for repo, meta in LEGACY.items():
            self.assertTrue((repo_root(repo) / meta["cfg"]).exists(),
                            f"{repo} 的宪法层不该被删掉")
            body = read(repo, "CHANGELOG.md")
            self.assertRegex(body, r"v5\.",
                             f"{repo} 的历史条目被清掉了")


class OnboardingContractTest(unittest.TestCase):
    """新用户入口必须**可达**：从一句话安装走到 READY，每一步都在文件里写着。

    A9#1 的形态是「仓里已经有 install_schedule.py，但首次用户走不到」——脚本在位不等于
    入口可达。可达性只能靠这类契约测断言：问了作息、给了命令、说了验收。
    """

    def test_deploy_protocol_copies_scripts_and_docs(self):
        """只复制 assistant/ 与运行时目录的话，clone 一删就断路。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            head = body[:body.index("## §0")] if "## §0" in body else body
            self.assertIn("scripts/", head, f"{repo} §-1 没复制 scripts/")
            self.assertIn("docs/", head, f"{repo} §-1 没复制 docs/")

    def test_init_asks_all_four_questions(self):
        """作息 / 留机 / 关机 / 时区，四问齐了才够算出排程并进 READY。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            for probe in ("几点睡", "留机", "关机", "IANA"):
                self.assertIn(probe, body, f"{repo} §0 没问「{probe}」")

    def test_init_runs_the_installer_inline(self):
        """访谈完必须**立即执行**安装，不能留到最后。

        留到最后等于留给「后面再说」——而排程没装上时，系统的缺失是静默的。
        """
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            self.assertIn("install_schedule.py", body,
                          f"{repo} §0 没给安装器调用")
            self.assertIn("--smoke", body, f"{repo} §0 没开 smoke")
            self.assertRegex(body, r"--timezone", f"{repo} §0 没传时区")

    def test_init_states_that_ready_is_not_running(self):
        """「装好了」与「已经在跑了」是两件事，且失败形态不同。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            self.assertIn("READY", body)
            self.assertIn("verify_first_run.py", body,
                          f"{repo} §0 没给首跑验收命令")

    def test_lid_close_warning_is_accurate(self):
        """合盖会睡眠。早先写「合盖也行」是错的，而错的方向是让人以为夜里会跑。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            self.assertRegex(body, r"别合盖|合盖不行|合盖默认睡眠",
                             f"{repo} 的供电说明没讲准合盖行为")

    def test_boundary_is_written_by_the_installer_in_both_places(self):
        """两处口径同数由安装器保证。手改必漏一处，而漏一处不报错。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            self.assertIn("install_schedule.py", body)
            self.assertRegex(body, r"两处同数|各两处|两处口径",
                             f"{repo} 没说明日界线要两处同数")


class BoundarySeparationTest(unittest.TestCase):
    """四个入口两两不混。"""

    def test_every_repo_in_scope_exists(self):
        """作用域内的仓必须都在。

        母版树里作用域 = 四仓，这条等于原先的「四仓齐备」；单独 clone 里作用域 = 自己
        那一个，四仓齐备无从断言（同级本来就没有兄弟仓）。
        """
        for repo in list(CURRENT) + list(LEGACY):
            self.assertTrue(repo_root(repo).is_dir(), f"缺仓：{repo}")

    def test_the_mother_tree_still_holds_all_four(self):
        """母版树里必须四仓齐备——这条只在母版树里判。

        单独 clone 里跳过会让「零 skip」破功，故改为按作用域分支：不在母版树时它断言的
        是另一件事（自己这个仓名属于已知四仓之一），仍然是一条真断言。
        """
        if IN_MOTHER:
            for repo in ALL_REPOS:
                self.assertTrue((MOTHER_ROOT / repo).is_dir(), f"母版缺仓：{repo}")
        else:
            self.assertIn(SELF_ROLE, ALL_REPOS,
                          "按仓内内容认不出本仓是四个发布包里的哪一个——"
                          "作用域会筛成空集，闸随之恒绿")

    def test_no_repo_is_both_current_and_legacy(self):
        self.assertEqual(set(ALL_CURRENT) & set(ALL_LEGACY), set())

    def test_legacy_repos_do_not_ship_the_scheduler(self):
        """legacy 不升级进本轮排程链。

        给它装上排程等于让「已退役」这条判断失效：一个能装排程的仓和现役仓的差别就只剩
        版本号了，而 A10 的整个前提是这两条线不该混。
        """
        for repo in LEGACY:
            self.assertFalse((repo_root(repo) / "scripts" / "install_schedule.py").exists(),
                             f"{repo} 里出现了排程安装器")

    def test_current_repos_ship_the_scheduler_and_verifier(self):
        for repo in CURRENT:
            for name in ("install_schedule.py", "verify_first_run.py",
                         "run_scheduled_dream.py"):
                self.assertTrue((repo_root(repo) / "scripts" / name).exists(),
                                f"{repo} 缺 scripts/{name}")

    def test_current_repos_ship_the_interview_spec(self):
        for repo in CURRENT:
            self.assertTrue((repo_root(repo) / "docs" / "schedule_interview.md").exists(),
                            f"{repo} 缺 docs/schedule_interview.md")


class SmokeSemanticsTest(unittest.TestCase):
    """文档对 `--smoke` 的口径必须与安装器的实际行为同数。

    实际行为（`install_schedule.py`）：`--smoke` 是 `action="store_true"` 的可选开关。
    不加不会阻止安装——排程照样装上，收据落 `state=INSTALLED_SMOKE_NOT_RUN`；加了才跑
    headless 实跑，且跑在启用 job **之前**，跑不通就回滚。

    把它写成「必经步 / 不是可选的」会造成两种误判，方向相反且都不报错：AI 以为不加就装
    不上，于是在 smoke 跑不通的机器上判断整个部署失败；或者反过来，以为加了就等于装好，
    把 `INSTALLED_SMOKE_NOT_RUN` 当成 `READY` 念给用户。
    """

    #: 现役仓里会描述 smoke 语义的文件。
    #:
    #: **README 也在内。** 两仓 README 的安装命令行里就带着 `--smoke`，是新用户最先看到
    #: 的那一份说明；把它漏在扫描外，README 上出现「必经步」措辞时本闸照旧全绿——而闸
    #: 恰好在最该判的那个文件上不判。
    SMOKE_DOC_RELS = ("README.md", "docs/schedule_interview.md", "CHANGELOG.md")

    def smoke_doc_paths(self, repo: str, meta: dict) -> tuple[str, ...]:
        return (meta["cfg"],) + self.SMOKE_DOC_RELS

    def smoke_docs(self):
        out = []
        for repo, meta in CURRENT.items():
            for rel in self.smoke_doc_paths(repo, meta):
                body = read(repo, rel)
                for line in body.splitlines():
                    if "--smoke" in line or "smoke " in line:
                        out.append((repo, rel, line))
        self.assertTrue(out, "一处 smoke 描述都没扫到——定位条件失效了，本闸恒绿")
        return out

    def test_no_doc_calls_smoke_mandatory(self):
        """反向断言：不得出现「必经 / 不是可选 / 必选」这类把可选开关说成强制的措辞。"""
        bad = re.compile(r"不是可选|必经步|必经|必选|强制加|mandatory")
        for repo, rel, line in self.smoke_docs():
            self.assertIsNone(
                bad.search(line),
                f"{repo}/{rel} 把 --smoke 说成强制：{line.strip()[:110]}")

    def test_the_installer_actually_keeps_smoke_optional(self):
        """正向锚：措辞对不对，取决于代码里它究竟是不是可选的。

        这一条把上面那句反向断言钉在实现上。若哪天 smoke 真的改成必填，上面的断言就该
        跟着翻——而这里会先红，提示要一起改，不会让文档与代码悄悄反向。
        """
        # **读随仓发布的那一份**，不读 `_shared` 母版。母版只在私区存在，单独 clone 里
        # 这一句会抛 `FileNotFoundError`——公开包被 clone 下来跑套件必报 error，而
        # 「闸依赖一个不随包发布的私区文件」正是发布边界要挡的那类越界。
        # 随仓那份才是用户真正会执行的代码，也正是文档要对得上的对象。
        for repo in CURRENT:
            src = read(repo, "scripts/install_schedule.py")
            self.assertIn('"--smoke", action="store_true"', src.replace("'", '"'),
                          f"{repo}/scripts/install_schedule.py 里 --smoke 不再是"
                          "可选开关了——文档口径要跟着一起改")
            self.assertIn("INSTALLED_SMOKE_NOT_RUN", src,
                          f"{repo} 的安装器里不跑 smoke 的状态没了")
        self.assertTrue(CURRENT, "没有任何现役仓落在作用域内——本闸恒绿")

    def joined_docs(self, repo: str, meta: dict) -> str:
        return "\n".join(read(repo, rel)
                         for rel in self.smoke_doc_paths(repo, meta))

    def test_docs_state_that_omitting_smoke_blocks_ready(self):
        """正向覆盖：可选之外还得说清代价，否则读者会以为不加也能 READY。"""
        for repo, meta in CURRENT.items():
            self.assertIn("INSTALLED_SMOKE_NOT_RUN", self.joined_docs(repo, meta),
                          f"{repo} 的文档没写「不跑 smoke 会落哪个状态」")

    def test_docs_state_smoke_runs_before_job_activation(self):
        """顺序也是语义的一部分：先启用后 smoke，失败就会留下一个已启用的坏 job。"""
        for repo, meta in CURRENT.items():
            self.assertRegex(self.joined_docs(repo, meta),
                             r"启用\s*job\s*\*{0,2}之前\*{0,2}",
                             f"{repo} 的文档没写 smoke 跑在启用 job 之前")

    def test_the_readme_is_actually_in_the_scanned_set(self):
        """自指哨兵：README 必须真的被扫到。

        上面那条反向断言的效力全在于扫描集合覆盖了 README。集合里漏掉它不会让任何测试
        变红——断言照旧对着剩下几份文件通过，而 README 上的错措辞无人看管。故这里直接
        断言扫描结果里有 README 的行。
        """
        scanned = {(repo, rel) for repo, rel, _ in self.smoke_docs()}
        for repo in CURRENT:
            self.assertIn((repo, "README.md"), scanned,
                          f"{repo}/README.md 没被 smoke 扫描集合覆盖——"
                          "README 退回「必经步」措辞时本闸会全绿")


#: 私区标识清单的落点，**由环境变量给出**，本文件里不含任何具体路径。
#:
#: 清单本身就是私区数据：把真实姓名与各端代号逐个写成字面量放进闸源码，等于为了检查泄
#: 露而把要查的东西完整发布一遍——而闸从来把自己的源码排除在扫描之外，故这份泄露不会
#: 被任何一次绿灯发现。审计的判据是「每一个被 push 的字节都已脱敏」，闸源码也是被 push
#: 的字节。
#:
#: 写成绝对路径同样不行：那条路径里含真实用户名与私区库名，本身就是要查的那类字节。故
#: 只认环境变量（或仓外相对路径），默认值留空。
MARKS_ENV = "PGH_RELEASE_MARKS_FILE"

#: 发布模式开关。置为 `1` 时缺清单 = **失败**，不是跳过。
#:
#: 只有 `skipTest` 一种处置是漏洞：clean clone 与 CI 里都没有这份清单，于是唯一的内容
#: 扫描被静默跳过，而套件报 OK。「绿」与「查过了」由此脱钩——push 前跑一遍全绿，什么都
#: 没扫。故发布把关必须以 fail-closed 的方式跑：
#:     PGH_RELEASE_MODE=1 PGH_RELEASE_MARKS_FILE=<仓外清单> python3 -m unittest ...
RELEASE_MODE_ENV = "PGH_RELEASE_MODE"


def marks_file() -> Path | None:
    raw = os.environ.get(MARKS_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def release_mode() -> bool:
    return os.environ.get(RELEASE_MODE_ENV, "").strip() in ("1", "true", "yes")


def load_private_marks() -> tuple[str, ...]:
    p = marks_file()
    if p is None:
        return ()
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    return tuple(s.strip() for s in lines
                 if s.strip() and not s.lstrip().startswith("#"))


PRIVATE_MARKS = load_private_marks()


def require_marks(case: unittest.TestCase) -> None:
    """没有清单时的处置：发布模式下失败，普通开发跑下跳过。

    两种模式分开是因为它们回答不同的问题。发布把关问「这些字节能不能公开」——缺输入时
    唯一安全的答案是「不知道，故不放行」。仓外使用者跑套件问的是「我这份装得对不对」，
    脱敏与他无关，那时跳过是诚实的。
    """
    if PRIVATE_MARKS:
        return
    msg = (f"读不到私区标识清单：环境变量 {MARKS_ENV} "
           f"{'未设置' if marks_file() is None else f'指向 {marks_file()} 但读不到'}")
    if release_mode():
        case.fail(f"{msg}——{RELEASE_MODE_ENV}=1 下缺少脱敏输入即判失败，"
                  "不得以跳过充当通过（跳过会让 clean clone / CI 全绿而实际零扫描）")
    case.skipTest(f"{msg}；发布把关请用 {RELEASE_MODE_ENV}=1 跑")

#: 扫描前先摘掉获得豁免的 v5 skill 标识符——它们是**已公开**的 skill 名（两仓
#: CHANGELOG 的已发布历史里就有），且 stale-route 闸要靠它们抓住从 v5 升上来的部署里
#: 残留的旧 skill 名。只匹配小写带连字符的形式，故同词根的私区代号（首字母大写的正文
#: 写法）不会被顺手摘掉。
#: 词根由片段拼出：写成字面量的话，这一行自己就是源码里的一截裸词根，而豁免只认「词根
#: + 连字符 + 名字」的完整形态，匹配不上，于是全仓扫描会把本行判成漏项——闸恒红。
EXEMPT_TOKEN_RE = re.compile("me" + "rak" + r"-[a-z-]+")


def assert_no_private_marks(case: unittest.TestCase, repo: str, rel: str,
                            _body_override: str | None = None) -> None:
    """扫一份发布仓文件里的私区标识，**大小写变体一并算命中**。

    早先直接用 `assertNotIn(mark, body)`，而 `assertNotIn` 是大小写敏感的：清单里存的
    是小写形式，于是正文里首字母大写的写法（英文 SKILL 里最自然的形态，因为它出现在句
    首与人称位置）一路绿灯通过。漏项就出在那里——两份退役 SKILL 的正文带着真实姓名的
    首字母大写形式，逐仓扫描红了，这个闸是绿的。

    故这里统一折成小写再比。代价是折叠后无法再按大小写区分「私区代号」与「已公开的
    v5 skill 名」——所以豁免那一步必须在折叠**之前**做完，靠原文的大小写把两者分开。
    顺序反了会把已公开的 skill 名也判成漏项，闸从此恒红，而恒红等于没有闸。
    """
    require_marks(case)
    raw = read(repo, rel) if _body_override is None else _body_override
    body = EXEMPT_TOKEN_RE.sub("", raw).lower()
    for mark in PRIVATE_MARKS:
        case.assertNotIn(mark.lower(), body,
                         f"{repo}/{rel} 出现私区标识 {mark!r}（不分大小写）")

#: 版本号形态：`vMAJOR.MINOR.PATCH`。
VERSION_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def _first_version(body: str, needle: str, label: str, case, repo: str) -> str:
    """取含 `needle` 的第一行里的第一个版本号。找不到就判失败，不静默放过。"""
    for line in body.splitlines():
        if needle in line:
            m = VERSION_RE.search(line)
            case.assertIsNotNone(
                m, f"{repo} 的{label}那一行没有版本号：{line.strip()[:80]}")
            return m.group(0)
    case.fail(f"{repo} 找不到{label}（按 {needle!r} 定位）")


class VersionAuthorityTest(unittest.TestCase):
    """一个发布版本号在四处出现，四处必须同数。

    四处 = README「当前发布」行 / README 里给用户照抄的安装口令 / CHANGELOG 顶部条目 /
    宪法层 §-1 的触发条件。

    不一致不会报错，报错的形态是**用户装错版本而不自知**：README 说当前发布是 X、安装
    口令写着 Y，用户照抄口令装了 Y；而 CHANGELOG 里根本没有 Y 的条目，于是「我装的到底
    是哪一版、带哪些行为」变成无法回答的问题——这正是发布边界要挡的那一类。

    判据可机械判定：四个字符串相等。「版本号要保持同步」不可判定。
    """

    #: 四个取值点：(定位串, 人话标签, 取哪份文件)。
    SITES = (
        ("当前发布", "README 当前发布行", "README.md"),
        ("release v", "README 安装口令", "README.md"),
        ("## v", "CHANGELOG 顶部条目", "CHANGELOG.md"),
        ("触发条件", "宪法层 §-1 触发条件", None),   # None = 取该仓的宪法层
    )

    def versions(self, repo: str, meta: dict) -> dict[str, str]:
        out = {}
        for needle, label, rel in self.SITES:
            body = read(repo, rel or meta["cfg"])
            out[label] = _first_version(body, needle, label, self, repo)
        return out

    def test_all_four_version_sites_agree(self):
        for repo, meta in CURRENT.items():
            got = self.versions(repo, meta)
            distinct = set(got.values())
            self.assertEqual(
                len(distinct), 1,
                f"{repo} 的版本口径不一致：" +
                "；".join(f"{k} = {v}" for k, v in got.items()))

    def test_the_declared_release_has_a_changelog_entry(self):
        """README 声明的版本必须在 CHANGELOG 里真有条目。

        上一条只保证「四处写着同一个数」。四处一起写错同一个数、而 CHANGELOG 顶部那条
        是别的版本 —— 上一条会红；但四处同数且 CHANGELOG 顶部就是它、正文里却没有对应
        小节的情况，得靠这一条兜。
        """
        for repo, meta in CURRENT.items():
            declared = _first_version(read(repo, "README.md"), "当前发布",
                                      "README 当前发布行", self, repo)
            entries = [ln for ln in read(repo, "CHANGELOG.md").splitlines()
                       if ln.startswith("## ") and declared in ln]
            self.assertTrue(entries,
                            f"{repo} CHANGELOG 没有 {declared} 的条目——"
                            f"README 声明发布 {declared} 但变更记录里查不到它带哪些行为")

    def test_changelog_entries_descend_from_the_top(self):
        """顶部条目必须是最高版本。

        新条目插在旧条目下面的话，上面两条仍全绿（四处同数、条目也在），而读者看到的
        「最新版」是个旧版本。
        """
        for repo in CURRENT:
            vs = [VERSION_RE.search(ln).groups()
                  for ln in read(repo, "CHANGELOG.md").splitlines()
                  if ln.startswith("## ") and VERSION_RE.search(ln)]
            nums = [tuple(int(x) for x in g) for g in vs]
            self.assertEqual(nums, sorted(nums, reverse=True),
                             f"{repo} CHANGELOG 条目不是从高到低：{nums}")

    def test_the_public_v5_history_is_preserved(self):
        """反向哨兵：脱敏与更名都不得吃掉已公开的 v5 skill 名历史。

        Codex 端 v6.2.0 做的正是「去掉 `<前缀>` 前缀」，而 v6.0/v6.1 的历史条目记的是
        改名**之前**的名字。把历史条目里的旧名改成新名，会让「我该把哪些旧名换掉」这个
        迁移问题失去唯一取证源；而脱敏闸看不出差别——旧名属于已发布标识，在豁免内。
        """
        # 只有 Codex 端做过去前缀更名，故这条只对它成立。作用域外时整条无对象——但
        # 不能跳过（跳过破坏零 skip），改为断言另一件仍然真的事：Claude 端从来没有过
        # 那个前缀，它的 CHANGELOG 里就不该出现 v5 前缀标识。
        codex = "PGH-dreaming-for-codex"
        if codex not in CURRENT:
            for repo in CURRENT:
                self.assertFalse(EXEMPT_TOKEN_RE.findall(read(repo, "CHANGELOG.md")),
                                 f"{repo} 从未用过 v5 线前缀，CHANGELOG 里却出现了")
            return
        body = read(codex, "CHANGELOG.md")
        legacy_zone = body[body.index("## v6.1.0"):]
        self.assertTrue(EXEMPT_TOKEN_RE.findall(legacy_zone),
                        "Codex 端 v6.1.0 及更早条目里已公开的 v5 skill 名全没了——"
                        "更名前的历史被改写了，迁移取证源丢失")


ARCH_FILES = ("README.md", "01_topology.md", "02_agents.md", "03_memory_flow.md",
              "04_work_memory_flow.md", "05_runtime.md", "06_cadence_and_gates.md")


class ArchitectureBookTest(unittest.TestCase):
    """架构说明书必须**在场、可达、且脱敏**。

    三条分开测，因为它们的失败形态不同：文件缺了是漏发；文件在而 README 不指向它是
    不可达（A9#1 那类形态——脚本在位不等于入口可达）；正文带私区代号是脱敏漏项，而
    这一条一旦 push 就不可撤回。
    """

    def test_all_seven_files_ship(self):
        for repo in CURRENT:
            for name in ARCH_FILES:
                self.assertTrue((repo_root(repo) / "docs" / "architecture" / name).exists(),
                                f"{repo} 缺 docs/architecture/{name}")

    def test_readme_links_the_book(self):
        """README 不指向它，新用户就找不到——目录名不会自己出现在视野里。"""
        for repo in CURRENT:
            body = read(repo, "README.md")
            self.assertIn("docs/architecture/README.md", body,
                          f"{repo} README 没链到架构说明书")

    def test_index_links_every_chapter(self):
        """索引漏掉某篇 = 那篇实际不可达，而它仍在仓里，看不出少了什么。"""
        for repo in CURRENT:
            idx = read(repo, "docs/architecture/README.md")
            for name in ARCH_FILES:
                if name == "README.md":
                    continue
                self.assertIn(name, idx, f"{repo} 架构索引没列 {name}")

    def test_no_private_marks_anywhere_in_the_book(self):
        for repo in CURRENT:
            for name in ARCH_FILES:
                assert_no_private_marks(self, repo, f"docs/architecture/{name}")

    #: 行为回归用的**合成**标识与豁免样本。
    #:
    #: 刻意不用真实私区标识做样本：样本会跟着闸源码 push 出去，而闸历来不扫自己的源
    #: 码，故那份泄露不会被任何绿灯发现。合成词照样能证明折叠行为——被测的是「折不折
    #: 大小写」「豁免在折叠前还是后」这两个机制，与词本身是谁无关。
    PROBE_MARK = "Zzsyntheticmark"
    PROBE_EXEMPT_PREFIX = "synthkit-"

    def scan(self, body: str, marks=None, exempt=None):
        """用给定清单扫一段正文，复用闸的真实折叠 / 豁免顺序。"""
        with unittest.mock.patch.object(
                sys.modules[__name__], "PRIVATE_MARKS",
                marks or (self.PROBE_MARK,)), \
             unittest.mock.patch.object(
                sys.modules[__name__], "EXEMPT_TOKEN_RE",
                exempt or re.compile(self.PROBE_EXEMPT_PREFIX + r"[a-z-]+")):
            assert_no_private_marks(self, "__probe__", "__probe__/body",
                                    _body_override=body)

    def test_the_scan_is_case_insensitive(self):
        """闸自身的回归：大小写变体必须命中。

        不测这一条的话，`assert_no_private_marks` 哪天被改回大小写敏感，现役文件恰好
        都是小写形式，闸照样全绿——而下一份带首字母大写的英文正文就会直接 push 出去。
        """
        base = self.PROBE_MARK
        for variant in (base.lower(), base.capitalize(), base.upper(),
                        base[:3].upper() + base[3:].lower()):
            with self.assertRaises(AssertionError, msg=variant):
                self.scan(f"# {variant} weekly review\n")

    def test_the_scan_exempts_published_lowercase_skill_names(self):
        """豁免必须活着：小写带连字符的 skill 名是**已公开**的，且 stale-route 闸要靠
        它们抓 v5 残留旧名。折叠大小写时顺手把它摘成漏项，会让闸恒红——而恒红的闸与
        没有闸等价。"""
        root = self.PROBE_MARK.lower()
        self.scan(f"name: {self.PROBE_EXEMPT_PREFIX}daily-review\n",
                  marks=(self.PROBE_MARK,),
                  exempt=re.compile(self.PROBE_EXEMPT_PREFIX + r"[a-z-]+"))
        # 同词根但不是豁免形态（正文代号写法）必须仍然命中，否则豁免过宽。
        with self.assertRaises(AssertionError):
            self.scan(f"# {root.capitalize()} Daily Review\n")

    def test_the_exemption_is_applied_before_case_folding(self):
        """顺序回归：先折小写再摘豁免的话，豁免正则（只匹配小写）依然摘得掉，
        但**同词根的大写代号也被一起摘掉**，于是真漏项静默通过。这一条钉住顺序。"""
        with self.assertRaises(AssertionError):
            self.scan(f"# {self.PROBE_MARK} 出现在正文里\n"
                      f"顺带提一句 {self.PROBE_EXEMPT_PREFIX}daily-review\n")

    def test_no_private_marks_in_the_active_authority_tree(self):
        """说明书之外也扫一遍：脱敏漏项最常出现在随手改过的现役文件里。

        **glob 必须递归到退役目录。** 早先用 `.*/skills/*/SKILL.md` 只够一层，
        `skills/_retired_*/daily-review/SKILL.md` 深一层因此从未被扫到——而退役正文是
        故意留在仓里做迁移取证的，它会跟着 push 出去。漏项就出在那里：两份退役 SKILL
        的正文标题带着私区 Codex 端代号，四仓扫描红了，这个闸却是绿的。
        """
        for repo, meta in CURRENT.items():
            targets = [meta["cfg"], "README.md"]
            targets += [str(p.relative_to(repo_root(repo)))
                        for p in repo_root(repo).glob(".*/skills/**/SKILL.md")]
            for rel in targets:
                assert_no_private_marks(self, repo, rel)

    def test_book_states_it_is_descriptive_not_normative(self):
        """描述层若不声明自己是描述层，读者会照它改系统——方向是反的。"""
        for repo in CURRENT:
            idx = read(repo, "docs/architecture/README.md")
            self.assertRegex(idx, r"描述层", f"{repo} 架构索引没做描述层声明")
            self.assertRegex(idx, r"以规定层为准|规定层与描述层冲突",
                             f"{repo} 没写明冲突时谁为准")

    def test_legacy_repos_do_not_ship_the_book(self):
        """legacy 只带退役与重定向标记（A10#4）。给它一份现役架构书等于劝人继续用它。"""
        for repo in LEGACY:
            self.assertFalse((repo_root(repo) / "docs" / "architecture").exists(),
                             f"{repo} 不该带现役架构说明书")


class WholeRepoSanitizationTest(unittest.TestCase):
    """逐文件全仓扫描，**不排除任何被 push 的文件，包含本闸自己的源码**。

    此前所有脱敏扫描都把闸源码排除在外，理由是「闸里当然有标识表」。那条例外正是漏洞
    本身：表里逐字写着真实姓名与各端代号，而它随仓 push；扫描永远看不见它，故永远绿。
    「除了检查器自己」这种例外，在检查器自己就是泄露源时恰好失效。

    故这里反过来：扫**每一个**会被 push 的文本文件，唯一豁免是已公开的小写 skill 标识
    符。闸需要的私区清单在运行时由环境变量指出，仓里不含它，也不含它的路径。

    **CHANGELOG 也扫。** 早先把它排除掉，理由是「它记录的正是 v5 那些 skill 叫什么」——
    但那个理由只覆盖已公开的小写 skill 标识符，而那一类本来就在豁免正则里。整份文件排除
    等于顺带放过了 changelog 里任何别的私区字节，而变更记录恰恰最容易在描述里带上代号。
    """

    SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build"}

    def pushed_files(self, repo: str):
        """会被 push 的文本文件。**没有按文件名的例外**——例外正是本轮要修的形态。"""
        root = repo_root(repo)
        for p in sorted(root.rglob("*")):
            if not p.is_file() or set(p.parts) & self.SKIP_DIRS:
                continue
            try:
                yield p, p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue          # 二进制 / 不可读：不是文本字节，另论

    def test_every_pushed_byte_is_sanitized(self):
        require_marks(self)
        for repo in list(CURRENT) + list(LEGACY):
            for path, raw in self.pushed_files(repo):
                body = EXEMPT_TOKEN_RE.sub("", raw).lower()
                for mark in PRIVATE_MARKS:
                    self.assertNotIn(
                        mark.lower(), body,
                        f"{path.relative_to(PGH) if PGH in path.parents else path.name} 出现私区标识 {mark!r}（不分大小写）")

    def test_the_gate_source_and_changelog_are_in_scope(self):
        """自指回归：本闸源码与 CHANGELOG 都必须落在扫描范围里。

        不钉住这一条，哪天有人为了让闸通过而把某个文件加回排除名单，全绿依旧——而那正
        是本轮要修的两种形态（闸不扫自己、闸不扫变更记录）。
        """
        for repo in CURRENT:
            names = {p.name for p, _ in self.pushed_files(repo)}
            self.assertIn(Path(__file__).name, names,
                          f"{repo} 的全仓扫描把闸源码排除在外了")
            self.assertIn("CHANGELOG.md", names,
                          f"{repo} 的全仓扫描把 CHANGELOG 排除在外了")

    def test_no_private_path_bytes_in_the_gate_source(self):
        """闸源码里不得出现具体的私区路径。

        路径本身就是要查的那类字节：它含真实用户名与私区库名。写成绝对路径常量时，前一
        条全仓扫描会命中它——但那要等清单里恰好列了这些词。这里独立钉住形态：只认环境
        变量，源码里不留路径。
        """
        src = Path(__file__).read_text(encoding="utf-8")
        self.assertIn(MARKS_ENV, src, "清单路径必须由环境变量给出")
        # 检测式由片段拼出，否则**这一条自己**就是源码里的一处家目录路径字面量，
        # 断言会命中自身而恒红。恒红的闸与没有闸等价。
        roots = ("/" + "Users" + "/", "/" + "home" + "/", "\\" + "Users" + "\\")
        for line in src.splitlines():
            if "roots = (" in line or "for root in roots" in line:
                continue          # 跳过本条自己的构造行
            for root in roots:
                self.assertNotIn(root, line,
                                 f"闸源码里出现具体家目录路径（{root!r}）——那是私区字节")

    def test_release_mode_fails_closed_without_the_marks_file(self):
        """clean clone / CI 里没有清单时，发布模式必须**失败**而不是跳过。

        只有 `skipTest` 一种处置时，缺输入的套件会报 OK——「绿」与「查过了」由此脱钩，
        而 push 前跑的那一遍恰恰是在 clean clone 或 CI 里。这一条直接构造那个环境。
        """
        probe = unittest.TestCase()
        with unittest.mock.patch.dict(
                os.environ, {RELEASE_MODE_ENV: "1", MARKS_ENV: ""}, clear=False), \
             unittest.mock.patch.object(
                sys.modules[__name__], "PRIVATE_MARKS", ()):
            with self.assertRaises(AssertionError) as cm:
                require_marks(probe)
        self.assertIn(RELEASE_MODE_ENV, str(cm.exception))

        # 反面：非发布模式下仍应跳过，否则仓外使用者跑套件会无端报红。
        with unittest.mock.patch.dict(
                os.environ, {RELEASE_MODE_ENV: "", MARKS_ENV: ""}, clear=False), \
             unittest.mock.patch.object(
                sys.modules[__name__], "PRIVATE_MARKS", ()):
            with self.assertRaises(unittest.SkipTest):
                require_marks(probe)

    #: 清单文件的**结构指纹**：第一行的固定标头。
    #:
    #: 按内容认，不按文件名认。早先比对 `marks_file().name`，于是没设环境变量时这一条就
    #: 跳过——而它恰恰是「清单有没有被误 push」的唯一检查，最需要它生效的场合（clean
    #: clone、CI，都没有那个变量）正好是它不生效的场合。发布验收不接受静默跳过。
    #:
    #: 顺带解决另一件事：判据不再依赖那个文件名。文件名本身也是私区信息，把它写进闸源码
    #: 等于用一处泄露去查另一处泄露。标头是清单自己声明的身份，改名也认得出来。
    #: 由片段拼出：写成整串的话，这一行自己就是仓里的一处指纹，而扫描要读闸源码，
    #: 于是断言命中自身、闸恒红。拼接后源码里不存在完整指纹串。
    MARKS_FINGERPRINT = "发布仓" + "脱敏" + "标识清单"

    def test_the_marks_list_is_not_shipped(self):
        """清单绝不能出现在任何发布仓里——**无条件跑**，不依赖清单是否可读。"""
        for repo in list(CURRENT) + list(LEGACY):
            for path, raw in self.pushed_files(repo):
                self.assertNotIn(
                    self.MARKS_FINGERPRINT, raw,
                    f"{path.relative_to(PGH) if PGH in path.parents else path.name} 带着私区标识清单的标头——清单被误 push 了")

    def test_the_fingerprint_actually_identifies_the_marks_list(self):
        """反向哨兵：指纹必须真的能认出清单。

        指纹要是打错了（清单改了标头、或这里写错一个字），上一条就变成一个永远命中不了
        任何东西的断言——绿灯，而清单可以随便 push。故拿真清单验一次；清单不可读时只有
        这一条跳过，不影响上面那条无条件扫描。
        """
        p = marks_file()
        missing = p is None or not p.exists()
        if missing and release_mode():
            # 发布模式下**不许跳过**：这一条跳掉，等于放弃校验上一条的判据是否有效，
            # 而验收要求零静默跳过——「跳过」在汇总里与「没问题」长得一样。
            self.fail(f"{RELEASE_MODE_ENV}=1 下读不到清单（{MARKS_ENV} "
                      f"{'未设置' if p is None else f'指向 {p} 但不存在'}），"
                      "无法校验指纹是否仍能认出清单——缺输入即判失败，不得跳过")
        if missing:
            self.skipTest(f"{MARKS_ENV} 未设置或指向的文件不存在——"
                          "无条件的那条扫描不受影响；发布把关请用 "
                          f"{RELEASE_MODE_ENV}=1 跑")
        self.assertIn(self.MARKS_FINGERPRINT, p.read_text(encoding="utf-8"),
                      "指纹认不出真清单——上一条扫描会恒绿，等于没有这个闸")


class InterviewContractTest(unittest.TestCase):
    """访谈文档与宪法层的**契约**一致性。

    这一组测的不是文风，是可执行契约：部署 AI 照着文档念问题、照着文档敲安装命令。文
    档说「三问」而实际列四问，AI 极可能只念前三问就去装——漏掉的恰是 IANA 时区问题，
    而缺时区会让收据一直非 READY（Windows 探测不到 IANA 名）或让抽取窗口整体平移。这
    类不一致不会有任何报错，故只能靠闸卡住。
    """

    def docs_in_scope(self) -> list[str]:
        """本次要判的访谈文档，路径相对 `PGH` 基准。

        母版树里额外含 `_shared/init/...` 母版一份（**按设计不 push**，只在私区存在）；
        单独 clone 里只有自己那一份 `docs/`。早先无条件列三份并靠「读不到就跳过」兜，
        于是公开仓单独跑时这一类稳定产出 skip——而发布验收要求零 skip。
        """
        out = [repo_root(r) / "docs" / "schedule_interview.md" for r in CURRENT]
        if IN_MOTHER:
            out.insert(0, MOTHER_ROOT / MOTHER_SENTINEL)
        return out

    def each(self):
        """取到的每一份都必须真的读到了。

        不要在这里包 `subTest`：生成器在 `with` 里 yield，调用方一旦提前退出循环（断言
        失败就会），`GeneratorExit` 会在 `with` 内部抛出，报成
        `generator ignored GeneratorExit` 而盖掉真正的断言信息。

        **作用域内的文件必须存在，缺了就判失败**——不是跳过。跳过让「绿」与「查过了」
        脱钩：作用域已经按在场情况算过一遍，此处再缺就是真缺。
        """
        out = []
        for p in self.docs_in_scope():
            self.assertTrue(p.is_file(), f"作用域内的访谈文档不在场：{p.name}")
            out.append((p.name, p.read_text(encoding="utf-8")))
        self.assertTrue(out, "访谈文档集合是空的——本类的断言会零次执行")
        return out

    def test_question_count_matches_the_questions_listed(self):
        """标题声明的问数必须等于正文实际的问数。"""
        for rel, body in self.each():
            listed = len(re.findall(r"^\*\*问 \d+ · ", body, re.M))
            m = re.search(r"## 问询（([一二三四五六])问", body)
            self.assertIsNotNone(m, f"{rel} 问询节标题没写问数")
            declared = "一二三四五六".index(m.group(1)) + 1
            self.assertEqual(declared, listed,
                             f"{rel} 标题声明 {declared} 问，正文实际列了 {listed} 问")

    def test_the_iana_timezone_question_is_present(self):
        """时区必须**问**出来，不能靠自动探测。Windows 上探测拿不到 IANA 名，不传就
        一直非 READY；而 macOS 上探测得到，故这个缺口在开发机上不复现。"""
        for rel, body in self.each():
            # 认「有一条**问句**在问 IANA 名」，不是「全文出现过 IANA 四个字母」。
            # 后者会被安装命令里的 `--timezone Asia/Shanghai` 或任何解释性段落满足，
            # 于是问题被从访谈里删掉、闸照样绿。
            self.assertRegex(
                body, r"\*\*问 \d+ · 时区\*\*", f"{rel} 没有独立的时区问项")
            m = re.search(r"\*\*问 \d+ · 时区\*\*(.{0,400})", body, re.S)
            self.assertIn("IANA", m.group(1), f"{rel} 时区问项没要 IANA 名")
            self.assertRegex(m.group(1), r"[A-Za-z]+/[A-Za-z_]+",
                             f"{rel} 时区问项没给形如 Asia/Shanghai 的示例，"
                             "用户不知道该答什么格式")

    def test_install_command_passes_the_timezone(self):
        """文档里的安装命令是被照抄执行的。漏 `--timezone` 等于每次部署都少传时区，
        而 Windows 上探测不到 IANA 名，收据会一直停在非 READY。

        按 ```bash 代码块整块取，不用「一行加续行」的正则：续行形状（反斜杠 + 换行 +
        缩进）稍有变化正则就整条匹配不上，而匹配不上的表现是**这一条静默通过**——
        闸看起来是绿的，实际什么都没查。以「块里有 `--sleep`」认定它是安装命令。
        """
        docs = self.each()
        checked = 0
        for rel, body in docs:
            for block in re.findall(r"```bash\n(.*?)```", body, re.S):
                if "install_schedule.py" not in block or "--sleep" not in block:
                    continue
                checked += 1
                self.assertIn("--timezone", block,
                              f"{rel} 的安装命令漏了 --timezone")
        # 按**实际读到的**份数要求，不按 DOCS 长度：母版不 push，仓外只有两份副本。
        self.assertGreaterEqual(checked, len(docs),
                                "没找到任何安装命令块——正则失配时这一条会静默通过，"
                                "故必须断言真的查到了东西")

    def test_no_obsolete_state_is_advertised(self):
        """状态表不能宣传安装器已经不会返回的状态。

        `INSTALL_UNVERIFIED` 是事务化改造之前的产物：那时回查失败会把 job 留在机器上。
        现在回查不过即回滚，这个状态永远不会出现。留在文档里的后果是部署 AI 照表解释一
        个不存在的状态，并给出一套无效的复位动作。
        """
        for rel, body in self.each():
            self.assertNotIn("INSTALL_UNVERIFIED", body,
                             f"{rel} 仍在宣传已废弃状态 INSTALL_UNVERIFIED")

    def test_lid_close_is_not_advertised_as_safe(self):
        """合盖不能说成「也行」。

        macOS 合盖默认进睡眠，接电源也不解除（clamshell 需要外接显示器 + 电源 +
        输入设备）。文档说合盖可以，用户就会合盖，然后每夜固化静默不跑——而排程、收据、
        job 定义全都正常，故这个失败在任何产物上都看不出来，只表现为「记忆系统只有白天
        那半截」。
        """
        for rel, body in self.each():
            self.assertNotRegex(body, r"合盖也行|合盖可以|合盖没问题",
                                f"{rel} 把合盖说成安全做法")
            self.assertRegex(body, r"别合盖|不要合盖|不能合盖",
                             f"{rel} 没明确禁止合盖")
            self.assertRegex(body, r"锁屏|关显示器",
                             f"{rel} 没说明锁屏 / 关显示器是允许的")

    def test_runtime_configs_agree_on_the_question_count(self):
        """宪法层与访谈文档必须同口径。宪法层是启动时真正被读的那份，它说三问，
        部署 AI 就问三问——访谈文档改对了也没用。"""
        for repo, meta in CURRENT.items():
            body = read(repo, meta["cfg"])
            listed = len(re.findall(r"^- \*\*问 \d+ · ", body, re.M))
            if not listed:
                continue
            m = re.search(r"([一二三四五六])问，一次一问", body)
            self.assertIsNotNone(m, f"{repo}/{meta['cfg']} 没写问数")
            declared = "一二三四五六".index(m.group(1)) + 1
            self.assertEqual(declared, listed,
                             f"{repo}/{meta['cfg']} 声明 {declared} 问，实际列了 {listed} 问")


class ExtractorTimezoneTest(unittest.TestCase):
    """Codex 抽取器必须从收据取时区，不能写死。

    这是 A13#2 的抽取器半边。窗口平移不报错：`manifest.json` 里日期、条数、路径全都
    自洽，只是抽出来的内容是拼接错的两个半天。
    """

    #: 抽取器只存在于 Codex 端现役仓。作用域外时整类**不注册**（见 `load_tests`），
    #: 而不是逐条跳过——`skipTest` 会让「零 skip」的验收条件破功。
    REQUIRES_REPO = "PGH-dreaming-for-codex"
    REL = ".codex/skills/daily-dream/scripts/extract_daily_transcripts.py"

    def script_path(self) -> Path:
        return repo_root(self.REQUIRES_REPO) / self.REL

    def load(self):
        import importlib.util
        import sys
        p = self.script_path()
        spec = importlib.util.spec_from_file_location("_extractor", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_extractor"] = mod
        spec.loader.exec_module(mod)
        return mod

    def resolve(self, receipt: dict | None, explicit=None):
        import json
        import tempfile
        mod = self.load()
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".pgh").mkdir()
            if receipt is not None:
                (home / ".pgh" / "schedule_receipt.codex.json").write_text(
                    json.dumps(receipt), encoding="utf-8")
            with unittest.mock.patch.object(Path, "home", staticmethod(lambda: home)):
                return mod.resolve_timezone(explicit)

    def test_reads_top_level_zone(self):
        tz, src = self.resolve({"timezone_iana": "America/New_York"})
        self.assertEqual(tz, "America/New_York")
        self.assertIn("收据", src)

    def test_reads_nested_zone_for_already_installed_machines(self):
        tz, _ = self.resolve({"acceptance": {"timezone_iana": "America/New_York"}})
        self.assertEqual(tz, "America/New_York")

    def test_unresolved_top_level_falls_through_to_nested(self):
        tz, _ = self.resolve({"timezone_iana": "UNRESOLVED",
                              "acceptance": {"timezone_iana": "America/New_York"}})
        self.assertEqual(tz, "America/New_York")

    def test_explicit_wins(self):
        tz, src = self.resolve({"timezone_iana": "America/New_York"},
                               explicit="Europe/Berlin")
        self.assertEqual(tz, "Europe/Berlin")
        self.assertIn("显式", src)

    def test_invalid_zone_name_is_not_trusted(self):
        """收据里的值也可能是坏的（手改 / 半截写入）。传给 `ZoneInfo()` 会抛异常，
        而这个异常发生在无人值守的夜里。"""
        tz, src = self.resolve({"timezone_iana": "Not/AZone"})
        self.assertEqual(tz, "Asia/Shanghai")
        self.assertIn("兜底", src)

    def test_fallback_declares_its_own_risk(self):
        tz, src = self.resolve(None)
        self.assertEqual(tz, "Asia/Shanghai")
        self.assertIn("兜底", src)
        self.assertRegex(src, r"平移|偏移")

    def test_cli_default_is_none_so_the_receipt_can_win(self):
        """`--timezone` 的默认值必须是 `None`。填成常量的话解析器永远收到非空值，
        会当成用户显式指定，收据里的真实时区一辈子读不到——A13#2 的原始形态。"""
        body = self.script_path().read_text(encoding="utf-8")
        m = re.search(r'add_argument\("--timezone"[^)]*\)', body, re.S)
        self.assertIsNotNone(m)
        self.assertIn("default=None", m.group(0),
                      "--timezone 的默认值不是 None，收据里的时区会被永久遮住")


class CatchUpContractTest(unittest.TestCase):
    """缺勤补跑的口径必须**单一**：次日首个真人会话自动补，上限三个有效工作日、从最早那天起。

    这是两端 `week-sync` 的实际行为。文档若写成「不会自动补 / 只提议 / 要用户手动开口」，
    部署 AI 会照文档回答，用户于是每天记着手工补——而漏跑的成因（睡了 / 关机 / 断网）都
    发生在夜里，恢复一旦取决于用户是否注意到提示，连漏一周只需要他忙一周。这类损失是静默
    的，故必须是闸而不是建议。
    """

    def each_doc(self):
        """**逐份**产出（仓, 相对路径, 正文）。

        不要把两份拼起来再断言：拼接后「其中一份写了」就能让断言通过，于是另一份退回旧
        口径不会判红——而部署 AI 读的可能正是退回的那一份。要求每一份各自成立才localize
        得到回退位置。
        """
        out = []
        for repo, meta in CURRENT.items():
            for rel in (meta["cfg"], "docs/schedule_interview.md"):
                out.append((repo, rel, read(repo, rel)))
        self.assertTrue(out, "作用域内没有任何文档——本类断言会零次执行")
        return out

    def test_docs_say_catch_up_is_automatic(self):
        for repo, rel, body in self.each_doc():
            self.assertRegex(body, r"自动补",
                             f"{repo}/{rel} 没说漏掉的日子会自动补")
            self.assertRegex(body, r"首个真人会话|首会话",
                             f"{repo}/{rel} 没写清自动补发生在首个真人会话")

    #: 手动 / 仅提议的措辞。命中即回退。
    MANUAL_RE = re.compile(r"不会自动补|不自动补|只提议补|仅提议|等用户开口|"
                           r"需要用户主动要求补|实际节律变成「?手动补跑")

    #: 反面语境。说明「为什么不能只提示等用户开口」的句子会命中上面的模式，而它讲的
    #: 恰好是相反的规定。不区分的话，把理由写得越清楚命中越多——闸会逼人删掉最该留的
    #: 那几行，方向正好是反的（与 stale-route 闸同一个坑）。
    RATIONALE_RE = re.compile(r"这是闸|不是建议|若只|只提示|一旦取决于|"
                              r"故必须|方向正好|会让恢复")

    def test_docs_never_claim_manual_only(self):
        """负向断言：不得回退成「不会自动补 / 只提议 / 得用户开口」。"""
        for repo, meta in CURRENT.items():
            for rel in (meta["cfg"], "docs/schedule_interview.md"):
                for line in read(repo, rel).splitlines():
                    m = self.MANUAL_RE.search(line)
                    if m and self.RATIONALE_RE.search(line):
                        continue          # 在讲「为什么不能这样」，不是在规定它
                    self.assertIsNone(
                        m,
                        f"{repo}/{rel} 把补跑写成手动 / 仅提议：{line.strip()[:110]}")

    def test_the_negation_carve_out_does_not_swallow_a_real_regression(self):
        """反向哨兵：豁免只对**带理由的**句子生效，光秃秃的手动口径仍须判红。

        没有这一条，上面那个豁免可以宽到把真回退也放过——而那时闸看着是绿的，文档却已
        经写成手动补跑。
        """
        plain = "漏掉的日子不会自动补，要用户第二天自己开口让 AI 补。"
        self.assertIsNotNone(self.MANUAL_RE.search(plain))
        self.assertIsNone(self.RATIONALE_RE.search(plain),
                          "豁免模式把一句纯手动口径也当成了「在讲理由」")

    def test_docs_state_the_three_day_bound_and_order(self):
        """上限与顺序都要写：无上限会让积压时一次补穷，顺序错会让状态机按错序推进。"""
        for repo, rel, body in self.each_doc():
            self.assertRegex(body, r"三个有效工作日|3 个有效工作日",
                             f"{repo}/{rel} 没写补跑上限三个有效工作日")
            self.assertRegex(body, r"最早那天起|从最早|oldest",
                             f"{repo}/{rel} 没写从最早那天起补")

    def test_docs_state_the_backlog_overflow_action(self):
        """积压超上限时的处置必须成文，否则更早那些天会被静默跳过。"""
        for repo, rel, body in self.each_doc():
            self.assertRegex(body, r"超过三天|积压超过",
                             f"{repo}/{rel} 没写积压超过三天怎么办")
            self.assertRegex(body, r"接受丢失|已接受",
                             f"{repo}/{rel} 没写更早那些天的信号按接受丢失处理")

    def test_docs_state_the_sunday_branch_follows_the_target_day(self):
        for repo, rel, body in self.each_doc():
            self.assertRegex(body, r"周日.{0,40}周段",
                             f"{repo}/{rel} 没写周段跟着目标逻辑日走")

    def test_the_week_sync_skill_actually_does_it(self):
        """正向锚：文档口径要对得上 skill 的实际行为，不是各说各话。"""
        for repo, meta in CURRENT.items():
            rt = meta["runtime"]
            base = ".claude" if rt == "claude" else ".codex"
            body = read(repo, f"{base}/skills/week-sync/SKILL.md")
            self.assertRegex(body, r"后台|background",
                             f"{repo} 的 week-sync 没写后台补跑")
            self.assertRegex(body, r"三天|three|3 ",
                             f"{repo} 的 week-sync 没写补跑上限")


class BoundaryConfirmationTest(unittest.TestCase):
    """推出来的日界线与固化时刻必须念给部署者确认，或让他显式覆盖。

    设错不报错：它只会每天把一段工作归到错误的日子，而错误发生在夜里、当时没人看着；
    等发现时错归的记录已经积了很多天。念一句话换的是这类静默错误在装机当刻被拦住。
    """

    def test_docs_require_reading_the_derived_values_back(self):
        """逐份判，不拼接——拼接会让一份退化被另一份掩住。"""
        for repo, meta in CURRENT.items():
            for rel in (meta["cfg"], "docs/schedule_interview.md"):
                body = read(repo, rel)
                self.assertRegex(body, r"念给(用户|部署者)确认|念出来等他",
                                 f"{repo}/{rel} 没要求把推算结果念给部署者确认")
                self.assertRegex(body, r"日界线.{0,40}固化",
                                 f"{repo}/{rel} 没写清要念的是日界线与固化时刻两个值")
                self.assertIn("--boundary-hour", body,
                              f"{repo}/{rel} 没给显式覆盖的参数")


class ScheduledAtSchemaTest(unittest.TestCase):
    """发布包必须记 `scheduled_at`（名义触发时刻），且它只能来自 job 定义。

    这一类是**跨仓 schema 闸**：三个脚本随两仓发布，任一仓漏改就会出现「一端记名义
    时刻、另一端不记」，而两端的验收器互不相识，谁也不报错。

    字段名逐字钉住。拼错不报错——验收器读不到就按旧记录放行，整条链看起来正常。
    """

    #: 字面键名：`scheduled` + 下划线 + `at`。用片段拼出来，好让「测试里写的是这个词」
    #: 这件事不依赖读者数下划线。
    KEY = "scheduled" + "_" + "at"
    #: 兼容键：`fired` + 下划线 + `at`。必须继续在场。
    LEGACY_KEY = "fired" + "_" + "at"

    RELS = ("scripts/run_scheduled_dream.py", "scripts/install_schedule.py",
            "scripts/verify_first_run.py")

    def each(self):
        out = [(repo, rel, read(repo, rel))
               for repo in CURRENT for rel in self.RELS]
        self.assertTrue(out, "作用域内没有排程脚本——本类断言会零次执行")
        return out

    def test_every_shipped_script_carries_the_new_key(self):
        for repo, rel, body in self.each():
            self.assertIn(self.KEY, body,
                          f"{repo}/{rel} 里没有 {self.KEY}——该仓的排程链不记名义触发时刻")

    def test_the_compatibility_key_is_still_there(self):
        """`fired_at` 不许被替换掉：旧收据、旧验收路径、日志段头都在读它。"""
        for repo, rel, body in self.each():
            self.assertIn(self.LEGACY_KEY, body,
                          f"{repo}/{rel} 把 {self.LEGACY_KEY} 删了——旧凭据会集体失效")

    def test_the_wrapper_sources_it_from_the_job_definition_only(self):
        """来源闸：名义时刻必须走 job 环境变量，不得从收据里取。

        收据是本机可读的普通 json，手工跑包装器的进程也读得到它；从那里取值会让
        `scheduled_at` 在手工路径上一样被填满，这个字段就退化成又一个 `fired_at`。
        """
        for repo in CURRENT:
            body = read(repo, "scripts/run_scheduled_dream.py")
            self.assertIn("PGH_SCHED_TIME", body,
                          f"{repo} 的包装器没读 job 注入的名义时刻")
            self.assertNotIn("dream_time", body,
                             f"{repo} 的包装器从收据取名义时刻了——手工跑也能填满该字段")

    def test_the_installer_injects_it_into_the_job(self):
        for repo in CURRENT:
            body = read(repo, "scripts/install_schedule.py")
            self.assertIn("PGH_SCHED_TIME", body,
                          f"{repo} 的安装器没把名义时刻写进 job 定义")
            self.assertIn("LEGACY_MAC_FIELDS", body,
                          f"{repo} 的安装器没留旧签名集合——已有 sentinel 会集体判红")

    def test_the_mac_covers_it(self):
        """签名集合必须含它：不签就等于允许在已签名的记录上贴任意名义时刻。"""
        for repo in CURRENT:
            body = read(repo, "scripts/install_schedule.py")
            zone = body[body.index("MAC_FIELDS = ("):]
            head = zone[:zone.index(")")]
            self.assertIn(self.KEY, head,
                          f"{repo} 的 MAC_FIELDS 没覆盖 {self.KEY}")

    def test_the_validator_only_grandfathers_an_absent_key(self):
        """向后兼容只对「键根本不在场」开放。

        `raw in (None, "")` 那种写法会把「旧凭据没有这个键」与「新凭据有键但值是空」
        塌成同一档，于是一条不含名义时刻的新自然凭据能把 `first_run_verified` 翻成
        true——而该字段的全部理由就是证明排程按它声明的时刻在跑。
        """
        for repo in CURRENT:
            body = read(repo, "scripts/verify_first_run.py")
            self.assertIn(f'"{self.KEY}" not in rec', body,
                          f"{repo} 的验收器没按「键是否在场」区分兼容形状")
            self.assertNotIn(f'raw in (None, "")', body,
                             f"{repo} 的验收器把空值与缺键塌成同一档了")

    def test_the_validator_reports_it_in_acceptance(self):
        for repo in CURRENT:
            body = read(repo, "scripts/verify_first_run.py")
            for field in (f"first_run_natural_{self.KEY}",
                          f"first_weekly_run_natural_{self.KEY}"):
                self.assertIn(field, body,
                              f"{repo} 的验收器没回填 {field}——日跑与周段都要报")

    def test_the_docs_state_both_fields_and_their_difference(self):
        """公开文档必须同时给出两个字段，并说明它们**不是**同一件事。

        逐份判，不拼接：拼接后「其中一份写了」就能让断言通过，于是另一份退回单字段口径
        不会判红——而部署 AI 读的可能正是退回的那一份。
        """
        pairs = [(repo, rel) for repo, meta in CURRENT.items()
                 for rel in (meta["cfg"], "docs/schedule_interview.md")]
        self.assertTrue(pairs, "作用域内没有文档——本条会零次执行")
        for repo, rel in pairs:
            body = read(repo, rel)
            self.assertIn(self.KEY, body,
                          f"{repo}/{rel} 没写名义触发时刻字段")
            self.assertIn(self.LEGACY_KEY, body,
                          f"{repo}/{rel} 没保留实际开跑时刻字段")
            self.assertRegex(body, r"名义触发时刻",
                             f"{repo}/{rel} 没说清 {self.KEY} 是名义触发时刻")
            self.assertRegex(
                body, r"(补触发|唤醒补触发).{0,40}差",
                f"{repo}/{rel} 没说明两者在补触发时会不同——"
                "不说明就会被当成同一个值的两种写法")

    def test_all_shipped_copies_are_byte_identical_to_each_other(self):
        """两仓的这三个脚本必须逐字节一致。

        漂开之后「一端修了、另一端没修」不会有任何测试变红——两端各自跑自己的套件，
        而套件读的是同一仓内的文件。

        单仓作用域（真 standalone clone）里只有一份，指纹集合天然只有一个元素，本条
        退化为「这三份都读得到」。**不用 skipTest**：跳过会让发布验收的零跳过要求破在
        这一条上，而跳过与通过在汇总行里长得一样。
        """
        for rel in self.RELS:
            digests = {hashlib.sha256(read(r, rel).encode()).hexdigest()
                       for r in CURRENT}
            self.assertEqual(len(digests), 1, f"{rel} 在作用域内的副本已漂开")


class ScopeResolutionTest(unittest.TestCase):
    """作用域解析本身必须可判——它决定其余每一条断言查不查得到东西。

    这一类挡的是**空集恒绿**：作用域筛空时，所有 `for repo in CURRENT` 的循环体零次
    执行，套件报全绿而实际零扫描。空集比 error 危险，因为它看起来是通过。
    """

    def test_the_scope_is_never_empty(self):
        self.assertTrue(list(CURRENT) + list(LEGACY),
                        "作用域是空集——所有按仓迭代的断言都会零次执行，闸恒绿")

    def test_standalone_scope_is_exactly_one_repo(self):
        if IN_MOTHER:
            self.assertEqual(len(CURRENT) + len(LEGACY), 4,
                             "母版树里应当四仓齐扫")
        else:
            self.assertEqual(len(CURRENT) + len(LEGACY), 1,
                             f"单独 clone 里作用域应当恰好一个仓，实际 "
                             f"{list(CURRENT) + list(LEGACY)}")

    def test_role_detection_ignores_the_directory_name(self):
        """角色判定不得依赖目录名。

        `git clone <url> my-agent` 是正常用法，目录名是用户的选择、不是包的属性。故这里
        直接验证：把仓根改叫任何名字，`detect_self_role()` 的结果都不变。
        """
        if IN_MOTHER:
            self.assertEqual(SELF_ROLE, "", "母版树里不该走自指角色判定")
            return
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            alias = Path(tmp) / "an-arbitrary-name"
            # 只复制判定需要的那几处标记，避免整仓拷贝拖慢套件。
            alias.mkdir()
            for rel in ("README.md",):
                src = SELF_ROOT / rel
                if src.exists():
                    shutil.copy2(src, alias / rel)
            for d in (".claude", ".codex"):
                if (SELF_ROOT / d).is_dir():
                    (alias / d).mkdir()
            with unittest.mock.patch.object(
                    sys.modules[__name__], "SELF_ROOT", alias):
                self.assertEqual(detect_self_role(), SELF_ROLE,
                                 "换个目录名就认不出角色了——判定依赖了 basename")

    def test_role_detection_fails_loudly_when_markers_are_gone(self):
        """反向哨兵：标记不在场时必须返回空串，由上面那条断言把它变红。

        「认不出」不能被当成「没问题」。返回一个默认角色会让闸对着错误的仓做断言。
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare"
            bare.mkdir()
            with unittest.mock.patch.object(
                    sys.modules[__name__], "SELF_ROOT", bare):
                self.assertEqual(detect_self_role(), "",
                                 "空仓里居然认出了角色——判定会把任意目录当发布包")

    def test_four_public_siblings_without_shared_are_not_the_mother_tree(self):
        """四个公开仓并排、但没有 `_shared` —— 这是维护者的正常布局，**不是**母版树。

        判错的后果不是漏判而是 error：闸会按母版布局去读 `_shared/init/...`，而那份文件
        按设计不随任何仓发布。故母版判据必须包含只有私区才有的哨兵。
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for r in ALL_REPOS:
                (root / r).mkdir()
            self.assertFalse(_in_mother_tree(root),
                             "四个公开仓并排被当成了母版树——闸会去读不随仓发布的母版文件")

    def test_four_siblings_plus_shared_is_the_mother_tree(self):
        """正向锚：四仓 + 私区哨兵齐备时必须判为母版树。

        没有这一条，上面那条可以靠「永远返回 False」通过，而那会让母版树也退化成单仓
        作用域，跨仓一致性断言（两端同数、母版与副本同文）全部失去对象。
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for r in ALL_REPOS:
                (root / r).mkdir()
            sentinel = root / MOTHER_SENTINEL
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("占位\n", encoding="utf-8")
            self.assertTrue(_in_mother_tree(root),
                            "四仓 + 私区哨兵齐备却没判成母版树——跨仓断言会失去对象")

    def test_the_live_run_matches_its_detected_layout(self):
        """本次运行的作用域与磁盘实际布局一致。"""
        if IN_MOTHER:
            self.assertTrue((MOTHER_ROOT / MOTHER_SENTINEL).is_file(),
                            "判成母版树但私区哨兵不在场")
        else:
            self.assertFalse(_in_mother_tree(),
                             "判成单仓但磁盘上其实是母版树")

    def test_every_applicable_scan_set_is_non_empty(self):
        """各扫描集合都不得为空——空集合同样恒绿。

        「applicable」按线取：现役专属的两个集合（访谈文档 / smoke 文档）只在作用域含
        现役仓时才有对象；单独 clone 一个退役仓时它们本就不适用，那不是空集缺陷。全仓
        脱敏扫描对四仓都适用，故无条件查。
        """
        for repo in list(CURRENT) + list(LEGACY):
            self.assertTrue(list(WholeRepoSanitizationTest().pushed_files(repo)),
                            f"{repo} 的全仓扫描没扫到任何文件")
        if CURRENT:
            self.assertTrue(InterviewContractTest().docs_in_scope(),
                            "访谈文档集合是空的")
            self.assertTrue(SmokeSemanticsTest().smoke_docs(),
                            "smoke 文档集合是空的")


class ConditionalDreamLayeringTest(unittest.TestCase):
    """现役包必须发布日 / 周 / 季三层条件递归，且保留硬依赖与授权闸。"""

    @staticmethod
    def skill_paths(repo: str) -> tuple[Path, Path, Path]:
        runtime = CURRENT[repo]["runtime"]
        base = repo_root(repo) / (".claude/skills" if runtime == "claude"
                                  else ".codex/skills")
        return (base / "daily-dream/SKILL.md",
                base / "weekly-dream/SKILL.md",
                base / "quarterly-archive/SKILL.md")

    def test_three_skill_layers_ship(self):
        for repo in CURRENT:
            for path in self.skill_paths(repo):
                self.assertTrue(path.is_file(),
                                f"{repo} 缺少条件夜链 skill：{path}")

    def test_daily_hands_one_explicit_transaction_to_weekly(self):
        for repo in CURRENT:
            daily, _, _ = self.skill_paths(repo)
            body = daily.read_text(encoding="utf-8")
            self.assertIn("weekly-dream", body, f"{repo} 日链没有转调周链")
            self.assertIn("--date", body, f"{repo} 日链没有显式传目标日")
            if CURRENT[repo]["runtime"] == "codex":
                self.assertIn("--bundle", body,
                              f"{repo} 有实体转写 bundle 却没有交给周链")
            else:
                self.assertIn("phase_a_receipt.json", body,
                              f"{repo} 没有把父事务的 phase-A 收据纳入交接")

    def test_weekly_keeps_phase_a_guard_and_detect_only_quarter_handoff(self):
        for repo in CURRENT:
            _, weekly, _ = self.skill_paths(repo)
            body = weekly.read_text(encoding="utf-8")
            lowered = body.lower()
            self.assertTrue("phase_a_receipt.json" in lowered or
                            "phase-a completion receipt" in lowered,
                            f"{repo} 周链丢失 phase A 硬依赖")
            self.assertIn("quarterly-archive", body,
                          f"{repo} 周链没有季度点转调")
            self.assertIn("--mode detect", body,
                          f"{repo} 周链可能绕过季度 detect 模式")

    def test_quarter_execute_requires_current_human_authorization(self):
        for repo in CURRENT:
            _, _, quarterly = self.skill_paths(repo)
            body = quarterly.read_text(encoding="utf-8").lower()
            self.assertIn("detect", body, f"{repo} 季链缺 detect 模式")
            self.assertIn("execute", body, f"{repo} 季链缺 execute 模式")
            self.assertTrue("当前真人会话" in body or
                            "current human session" in body,
                            f"{repo} execute 没有当前真人会话授权闸")
            self.assertTrue("c 级" in body or "c-level" in body,
                            f"{repo} 季度归档没有标成 C 级动作")


def load_tests(loader, tests, pattern):
    """按作用域装配套件：作用域外的类**不注册**，而不是注册后逐条跳过。

    `skipTest` 会让「零 skip」的发布验收条件破功，且 skip 与「这条压根没跑」在输出上
    同形。不注册则测试总数直接反映本次真正判了多少条。
    """
    suite = unittest.TestSuite()
    for cls in (CurrentReposTest, LegacyReposTest, OnboardingContractTest,
                BoundarySeparationTest, SmokeSemanticsTest, VersionAuthorityTest,
                ArchitectureBookTest, WholeRepoSanitizationTest,
                InterviewContractTest, ExtractorTimezoneTest,
                CatchUpContractTest, BoundaryConfirmationTest,
                ScheduledAtSchemaTest, ScopeResolutionTest,
                ConditionalDreamLayeringTest):
        need = getattr(cls, "REQUIRES_REPO", None)
        if need and need not in CURRENT and need not in LEGACY:
            continue
        # 现役 / 退役专属类：作用域里没有对应线时整类不注册。
        if cls in (CurrentReposTest, OnboardingContractTest, SmokeSemanticsTest,
                   VersionAuthorityTest, ArchitectureBookTest,
                   InterviewContractTest, CatchUpContractTest,
                   BoundaryConfirmationTest,
                   ScheduledAtSchemaTest,
                   ConditionalDreamLayeringTest) and not CURRENT:
            continue
        if cls is LegacyReposTest and not LEGACY:
            continue
        suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
