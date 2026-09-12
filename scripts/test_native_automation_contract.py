#!/usr/bin/env python3
"""Native Codex automation authority regression tests."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR = (
    ROOT / ".codex" / "skills" / "daily-dream" / "scripts"
    / "extract_daily_transcripts.py"
)
AUDIT = ROOT / "scripts" / "audit_stale_routes.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class NativeAuthorityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = load_module("pgh_native_extractor", EXTRACTOR)
        cls.audit = load_module("pgh_stale_route_audit", AUDIT)

    def test_agents_authority_wins_even_when_legacy_receipt_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            (home / ".codex").mkdir()
            (home / ".pgh").mkdir()
            (home / ".codex" / "AGENTS.md").write_text(
                "IANA 时区 = America/New_York\n"
                "物理 hour < 04:00 → 逻辑日期 = 物理日期 − 1\n",
                encoding="utf-8",
            )
            (home / ".pgh" / "schedule_receipt.codex.json").write_text(
                json.dumps({"timezone_iana": "Asia/Shanghai"}),
                encoding="utf-8",
            )

            with mock.patch.object(self.extractor.Path, "home", return_value=home):
                timezone_name, timezone_source = self.extractor.resolve_timezone()
                boundary, boundary_source = self.extractor.resolve_boundary_hour()

            self.assertEqual(timezone_name, "America/New_York")
            self.assertIn("AGENTS.md", timezone_source)
            self.assertEqual(boundary, 4)
            self.assertIn("AGENTS.md", boundary_source)

    def test_legacy_receipt_alone_never_becomes_current_authority(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            (home / ".pgh").mkdir()
            (home / ".pgh" / "schedule_receipt.codex.json").write_text(
                json.dumps({"timezone_iana": "America/Los_Angeles"}),
                encoding="utf-8",
            )

            with mock.patch.object(self.extractor.Path, "home", return_value=home):
                timezone_name, timezone_source = self.extractor.resolve_timezone()

            self.assertEqual(timezone_name, self.extractor.DEFAULT_TZ)
            self.assertIn("兜底", timezone_source)

    def test_stale_route_gate_scans_skill_scripts(self) -> None:
        files = {
            path.relative_to(ROOT).as_posix()
            for path in self.audit.active_files(ROOT)
        }
        self.assertIn(
            ".codex/skills/daily-dream/scripts/extract_daily_transcripts.py",
            files,
        )
        hits, _waived, count = self.audit.scan(ROOT)
        self.assertGreater(count, 0)
        self.assertEqual(hits, [])

    def test_stale_route_rule_rejects_legacy_scheduler_code(self) -> None:
        rule = next(
            item for item in self.audit.RULES
            if item.name == "retired-os-scheduler-artifact"
        )
        self.assertTrue(
            rule.fires_on(
                'path = Path.home() / ".pgh" / "schedule_receipt.codex.json"'
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
