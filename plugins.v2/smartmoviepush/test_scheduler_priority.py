"""Keep site searches available for an existing download backlog."""

import ast
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
method = next(node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name == "scheduled_run")
namespace = {
    "datetime": datetime,
    "pytz": SimpleNamespace(timezone=lambda _name: timezone.utc),
    "settings": SimpleNamespace(TZ="Asia/Shanghai"),
    "time": time,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="SchedulerUnderTest", bases=[], keywords=[], body=[method], decorator_list=[]
)], type_ignores=[])), str(SOURCE), "exec"), namespace)


class SchedulerPriorityTest(unittest.TestCase):
    def setUp(self):
        self.subject = namespace["SchedulerUnderTest"]()
        self.subject._push_interval_minutes = 1
        self.subject._enabled = True
        self.subject._auto_push = True
        self.subject._auto_download = True
        self.subject._random_download_enabled = True
        self.subject._limit = 20
        self.subject._max_active_downloads = 10
        self.subject._pt_cooldown_key = "mteam_cooldown_until"
        self.subject.get_data = lambda _key: 0
        self.subject._disk_guard_blocks_new = lambda: False
        self.logs = []
        self.runs = []
        self.subject._append_plugin_log = lambda *args: self.logs.append(args)
        self.subject.run_once = lambda **kwargs: self.runs.append(kwargs)

    def test_large_random_backlog_pauses_new_scan(self):
        self.subject._load_download_queue = lambda: [{"source": "random"}] * 21
        self.subject.scheduled_run()
        self.assertEqual(self.runs, [])
        self.assertTrue(any("优先给现有队列补位" in row[1] for row in self.logs))

    def test_small_random_backlog_allows_scan(self):
        self.subject._load_download_queue = lambda: [{"source": "random"}] * 5
        self.subject.scheduled_run()
        self.assertEqual(self.runs, [{"limit": 20, "test_mode": False}])


if __name__ == "__main__":
    unittest.main()
