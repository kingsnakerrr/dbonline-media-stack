"""Regression checks for timestamps at the end of run results."""

import ast
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
methods = [node for node in plugin.body if isinstance(node, ast.FunctionDef)
           and node.name in {"_format_result_time", "_display_run_status"}]
namespace = {"datetime": datetime, "pytz": SimpleNamespace(timezone=ZoneInfo),
             "settings": SimpleNamespace(TZ="Asia/Shanghai"), "Any": Any}
test_class = ast.ClassDef(name="StatusUnderTest", bases=[], keywords=[], body=methods, decorator_list=[])
exec(compile(ast.fix_missing_locations(ast.Module(body=[test_class], type_ignores=[])), str(SOURCE), "exec"), namespace)
StatusUnderTest = namespace["StatusUnderTest"]


class RunStatusDisplayTest(unittest.TestCase):
    def test_completed_result_ends_with_requested_time_and_keeps_counts(self):
        raw = {"stage": "已完成", "detail": "TMDB候选 284", "target": 10,
               "searched": 3, "selected": 0, "sent": 0,
               "updated_at": "2026-01-23T13:20:59+08:00"}
        shown = StatusUnderTest()._display_run_status(raw)
        self.assertEqual(shown["detail"], "TMDB候选 284（目标 10，已查询 3，选中 0，已推送 0） · 2026.1.23 13:20")
        self.assertNotIn("target", shown)
        self.assertTrue(shown["time_in_detail"])
        self.assertEqual(raw["target"], 10)

    def test_running_result_keeps_progress_counts(self):
        raw = {"stage": "搜索站点", "detail": "正在查询", "target": 10,
               "updated_at": "2026-01-23T13:20:59+08:00"}
        self.assertEqual(StatusUnderTest()._display_run_status(raw), raw)


if __name__ == "__main__":
    unittest.main()
