"""Focused regression tests for the five independent month/score tasks."""

import ast
import calendar
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from urllib.parse import urlencode


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
methods = {"_load_monthly_tasks", "_monthly_task", "_update_monthly_task",
           "_production_country_codes", "_scan_monthly_task", "_api_monthly_action",
           "_monthly_scan_key", "_monthly_archive", "_save_monthly_archive",
           "_load_monthly_archive", "_monthly_archive_summaries", "_api_secure_monthly",
           "_chinese_movie_title"}
selected = [node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name in methods]


class FakeDiscover:
    _urls = {"movies": "discover/movie"}

    def _request_obj(self, _url, _params, **_kwargs):
        return {"total_pages": 1, "results": [
            {"id": 1, "title": "美国电影", "release_date": "2026-01-02", "vote_average": 8.0},
            {"id": 2, "title": "台湾电影", "release_date": "2026-01-03", "vote_average": 7.4},
            {"id": 3, "title": "其他地区", "release_date": "2026-01-04", "vote_average": 9.0},
        ]}


class FakeTmdbApi:
    def __init__(self, language=None):
        assert language == "zh-CN"

    def get_info(self, _type, movie_id):
        countries = {1: "US", 2: "TW", 3: "IN"}
        return {"id": movie_id, "title": f"中文影片 {movie_id}", "poster_path": f"/{movie_id}.jpg",
                "production_countries": [{"iso_3166_1": countries[movie_id]}]}


class NoopThread:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


namespace = {
    "calendar": calendar, "datetime": datetime,
    "sqlite3": sqlite3, "json": json, "re": re, "closing": closing,
    "Body": lambda default=None: default,
    "pytz": SimpleNamespace(timezone=lambda _name: timezone.utc), "urlencode": urlencode,
    "Optional": Optional,
    "threading": SimpleNamespace(Thread=NoopThread),
    "ModuleManager": lambda: SimpleNamespace(get_running_module=lambda _name: SimpleNamespace(
        tmdb=SimpleNamespace(discover=FakeDiscover()))),
    "TmdbApi": FakeTmdbApi, "MediaType": SimpleNamespace(MOVIE="movie"),
    "settings": SimpleNamespace(TZ="Asia/Shanghai"),
    "logger": SimpleNamespace(warning=lambda *_args: None),
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="MonthlyUnderTest", bases=[], keywords=[], body=selected,
    decorator_list=[])], type_ignores=[])), str(SOURCE), "exec"), namespace)
MonthlyUnderTest = namespace["MonthlyUnderTest"]


class MonthlyTasksTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.subject = MonthlyUnderTest()
        self.subject._monthly_tasks_key = "monthly_movie_tasks"
        self.subject._monthly_tasks_lock = threading.RLock()
        self.subject._monthly_scan_lock = threading.Lock()
        self.subject._monthly_archive_lock = threading.RLock()
        self.subject.get_data_path = lambda: Path(self.tempdir.name)
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
        self.assertEqual(task["candidates"][0]["display_title"], "中文影片 1")
        self.assertEqual(task["candidates"][0]["poster_path"], "/1.jpg")
        self.assertEqual(self.subject._load_monthly_archive(task["scan_key"])["candidate_count"], 2)

    def test_saved_calendar_survives_task_removal(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "title": "中文影片 1"},
            {"tmdb_id": 2, "release_date": "2026-01-02", "title": "中文影片 2"},
        ])
        self.store["monthly_movie_tasks"] = []
        self.assertEqual(self.subject._monthly_archive_summaries()[0]["days"]["2026-01-02"], 2)
        self.assertEqual(len(self.subject._load_monthly_archive(key)["candidates"]), 2)

    def test_archive_day_uses_live_plugin_history_and_emby_index(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "title": "中文影片 1"},
            {"tmdb_id": 2, "release_date": "2026-01-03", "title": "中文影片 2"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_stats_history = lambda: [{"tmdb_id": 1, "submitted_at": "2026-01-02",
                                                       "download_completed_at": "2026-01-03"}]
        self.subject._load_download_queue = lambda: []
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": {"1"}}
        self.subject._history_view_status = lambda *_args: "awaiting_library"
        result = self.subject._api_secure_monthly({
            "archive_key": key, "date": "2026-01-02", "access_token": "test",
        })
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total"], 1)
        self.assertEqual(result["data"]["items"][0]["status"], "emby_ingested")

    def test_chinese_translation_falls_back_to_tw_before_english(self):
        detail = {"title": "English title", "translations": {"translations": [
            {"iso_639_1": "zh", "iso_3166_1": "TW", "data": {"title": "繁體譯名"}},
        ]}}
        self.assertEqual(self.subject._chinese_movie_title(detail), "繁體譯名")

    def test_five_task_limit_does_not_overwrite_existing_tasks(self):
        self.store["monthly_movie_tasks"] = [{"id": str(i)} for i in range(5)]
        result = self.subject._api_monthly_action("monthly_save", {
            "year": 2026, "month": 1, "min_score": 7,
        })
        self.assertFalse(result["success"])
        self.assertEqual(len(self.subject._load_monthly_tasks()), 5)


if __name__ == "__main__":
    unittest.main()
