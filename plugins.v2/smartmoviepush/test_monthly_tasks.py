"""Focused regression tests for the five independent month/score tasks."""

import ast
import calendar
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from urllib.parse import urlencode


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
methods = {"_load_monthly_tasks", "_monthly_task", "_update_monthly_task",
           "_production_country_codes", "_scan_monthly_task", "_api_monthly_action"}
selected = [node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name in methods]


class FakeDiscover:
    _urls = {"movies": "discover/movie"}

    def _request_obj(self, _url, _params, **_kwargs):
        return {"total_pages": 1, "results": [
            {"id": 1, "title": "美国电影", "release_date": "2026-01-02", "vote_average": 8.0},
            {"id": 2, "title": "台湾电影", "release_date": "2026-01-03", "vote_average": 7.4},
            {"id": 3, "title": "其他地区", "release_date": "2026-01-04", "vote_average": 9.0},
        ]}


class FakeChain:
    def tmdb_info(self, movie_id, _type):
        countries = {1: "US", 2: "TW", 3: "IN"}
        return {"id": movie_id, "title": f"影片 {movie_id}",
                "production_countries": [{"iso_3166_1": countries[movie_id]}]}


class NoopThread:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


namespace = {
    "calendar": calendar, "datetime": datetime,
    "pytz": SimpleNamespace(timezone=lambda _name: timezone.utc), "urlencode": urlencode,
    "Optional": Optional,
    "threading": SimpleNamespace(Thread=NoopThread),
    "ModuleManager": lambda: SimpleNamespace(get_running_module=lambda _name: SimpleNamespace(
        tmdb=SimpleNamespace(discover=FakeDiscover()))),
    "TmdbChain": FakeChain, "MediaType": SimpleNamespace(MOVIE="movie"),
    "settings": SimpleNamespace(TZ="Asia/Shanghai"),
    "logger": SimpleNamespace(warning=lambda *_args: None),
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="MonthlyUnderTest", bases=[], keywords=[], body=selected,
    decorator_list=[])], type_ignores=[])), str(SOURCE), "exec"), namespace)
MonthlyUnderTest = namespace["MonthlyUnderTest"]


class MonthlyTasksTest(unittest.TestCase):
    def setUp(self):
        self.subject = MonthlyUnderTest()
        self.subject._monthly_tasks_key = "monthly_movie_tasks"
        self.subject._monthly_tasks_lock = threading.RLock()
        self.subject._monthly_scan_lock = threading.Lock()
        self.subject._allowed_countries = {"US", "TW", "JP", "KR", "CN", "HK"}
        self.store = {}
        self.subject.get_data = self.store.get
        self.subject.save_data = self.store.__setitem__
        self.logs = []
        self.subject._append_plugin_log = lambda *args: self.logs.append(args)

    def test_month_scan_includes_us_taiwan_and_excludes_other_country(self):
        self.store["monthly_movie_tasks"] = [{
            "id": "one", "year": 2026, "month": 1, "min_score": 7.0,
            "scan_state": "pending", "candidates": [],
        }]
        self.subject._scan_monthly_task("one")
        task = self.subject._monthly_task("one")
        self.assertEqual(task["scan_state"], "complete")
        self.assertEqual([item["tmdb_id"] for item in task["candidates"]], [1, 2])
        self.assertTrue(all("info" in item for item in task["candidates"]))

    def test_five_task_limit_does_not_overwrite_existing_tasks(self):
        self.store["monthly_movie_tasks"] = [{"id": str(i)} for i in range(5)]
        result = self.subject._api_monthly_action("monthly_save", {
            "year": 2026, "month": 1, "min_score": 7,
        })
        self.assertFalse(result["success"])
        self.assertEqual(len(self.subject._load_monthly_tasks()), 5)


if __name__ == "__main__":
    unittest.main()
