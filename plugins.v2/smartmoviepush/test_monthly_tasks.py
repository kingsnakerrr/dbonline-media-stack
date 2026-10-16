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
from typing import Any, List, Optional, Tuple
from urllib.parse import urlencode


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
methods = {"_load_monthly_tasks", "_monthly_task", "_update_monthly_task",
           "_production_country_codes", "_scan_monthly_task", "_api_monthly_action",
           "_monthly_scan_key", "_monthly_archive", "_save_monthly_archive",
           "_load_monthly_archive", "_load_monthly_archive_month", "_monthly_archive_summaries", "_api_secure_monthly",
           "_chinese_movie_title", "_monthly_resource_rank", "_monthly_resource_options",
           "_torrent_identity", "_start_monthly_batch_download", "_start_monthly_resource_scan",
           "_load_download_queue", "_remove_queued_movie", "_submit_download",
           "process_download_queue"}
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
    "hashlib": __import__("hashlib"),
    "Context": SimpleNamespace,
    "Body": lambda default=None: default,
    "pytz": SimpleNamespace(timezone=lambda _name: timezone.utc), "urlencode": urlencode,
    "Optional": Optional, "Any": Any, "List": List, "Tuple": Tuple,
    "MediaInfo": SimpleNamespace,
    "threading": SimpleNamespace(Thread=NoopThread),
    "ModuleManager": lambda: SimpleNamespace(get_running_module=lambda _name: SimpleNamespace(
        tmdb=SimpleNamespace(discover=FakeDiscover()))),
    "TmdbApi": FakeTmdbApi, "MediaType": SimpleNamespace(MOVIE="movie"),
    "settings": SimpleNamespace(TZ="Asia/Shanghai"),
    "logger": SimpleNamespace(warning=lambda *_args: None, info=lambda *_args: None,
                               error=lambda *_args: None),
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
        self.subject._monthly_resource_job = {}
        self.subject._monthly_resource_lock = threading.Lock()
        self.subject._monthly_resource_job_lock = threading.RLock()
        self.subject._monthly_batch_job = {}
        self.subject._monthly_batch_lock = threading.Lock()
        self.subject._queue_lock = threading.RLock()
        self.subject._download_queue_key = "download_queue"
        self.subject._enabled = True
        self.subject._disk_guard_blocks_new = lambda: False
        self.subject.get_data_path = lambda: Path(self.tempdir.name)
        self.subject._allowed_countries = {"US", "TW", "JP", "KR", "CN", "HK"}
        self.store = {}
        self.subject.get_data = self.store.get
        self.subject.save_data = self.store.__setitem__
        self.logs = []
        self.subject._append_plugin_log = lambda *args: self.logs.append(args)

    def test_resource_scan_limits_one_click_to_sixty_top_voted_candidates(self):
        candidates = [{"tmdb_id": index, "score": 7.5, "vote_count": index}
                      for index in range(1, 131)]
        self.subject._load_monthly_archive_month = lambda *_args: {
            "min_score": 7, "candidates": candidates}
        self.subject._load_monthly_resource_cache = lambda *_args: {"130": []}
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._scan_monthly_resources = lambda *_args: None
        result = self.subject._start_monthly_resource_scan(2026, 1, 7)
        self.assertTrue(result["success"])
        self.assertEqual(self.subject._monthly_resource_job["total"], 60)
        self.assertEqual(self.subject._monthly_resource_job["checked"], 1)
        self.assertEqual(self.subject._monthly_resource_job["candidates"], 130)

    def test_annual_resource_scan_covers_all_candidates_including_mainstream(self):
        candidates = [{"tmdb_id": index, "score": 5 if index == 1 else 8,
                       "vote_count": index, "categories": ["mainstream"] if index == 1 else ["high_quality"]}
                      for index in range(1, 132)]
        self.subject._load_monthly_archive_month = lambda *_args: {
            "min_score": 7, "candidates": candidates}
        self.subject._load_monthly_resource_cache = lambda *_args: {}
        self.subject._load_download_queue = lambda: []
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._scan_monthly_resources = lambda *_args: None
        result = self.subject._start_monthly_resource_scan(2026, 0, 7)
        self.assertTrue(result["success"])
        self.assertEqual(self.subject._monthly_resource_job["total"], 131)

    def test_annual_archive_filters_category_and_release_month(self):
        task = {"year": 2026, "month": 0, "min_score": 7, "min_votes": 50,
                "scanned_at": "2026-10-16"}
        self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 5,
             "categories": ["mainstream"], "title": "主流低分"},
            {"tmdb_id": 2, "release_date": "2026-02-03", "score": 8,
             "categories": ["high_quality"], "title": "高口碑"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_stats_history = lambda: []
        self.subject._load_download_queue = lambda: []
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": set()}
        result = self.subject._api_secure_monthly({
            "archive_year": 2026, "archive_month": 0, "category": "mainstream",
            "release_month": 1, "min_score": 7, "access_token": "test",
        })
        self.assertTrue(result["success"])
        self.assertEqual([item["tmdb_id"] for item in result["data"]["items"]], [1])

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

    def test_annual_scan_keeps_mainstream_below_score_floor_and_deduplicates(self):
        class AnnualDiscover(FakeDiscover):
            def _request_obj(self, _url, _params, **_kwargs):
                return {"total_pages": 1, "results": [
                    {"id": 1, "release_date": "2026-01-02", "vote_average": 8.0,
                     "vote_count": 100},
                    {"id": 2, "release_date": "2026-01-03", "vote_average": 5.0,
                     "vote_count": 80},
                ]}

        original = namespace["ModuleManager"]
        namespace["ModuleManager"] = lambda: SimpleNamespace(get_running_module=lambda _name:
            SimpleNamespace(tmdb=SimpleNamespace(discover=AnnualDiscover())))
        self.addCleanup(lambda: namespace.__setitem__("ModuleManager", original))
        self.store["monthly_movie_tasks"] = [{
            "id": "annual", "year": 2026, "month": 0, "min_score": 7.0,
            "min_votes": 50, "scan_state": "pending", "candidates": [],
        }]
        self.subject._scan_monthly_task("annual")
        task = self.subject._monthly_task("annual")
        self.assertEqual(task["scan_state"], "complete")
        self.assertEqual(len(task["candidates"]), 2)
        categories = {item["tmdb_id"]: item["categories"] for item in task["candidates"]}
        self.assertEqual(categories[1], ["high_quality", "mainstream"])
        self.assertEqual(categories[2], ["mainstream"])
        self.assertEqual(self.subject._load_monthly_archive_month(2026, 0)["candidate_count"], 2)

    def test_saved_calendar_survives_task_removal(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "title": "中文影片 1"},
            {"tmdb_id": 2, "release_date": "2026-01-02", "title": "中文影片 2"},
        ])
        self.store["monthly_movie_tasks"] = []
        self.assertEqual(self.subject._monthly_archive_summaries()[0]["days"]["2026-01-02"], 2)
        self.assertEqual(len(self.subject._load_monthly_archive(key)["candidates"]), 2)

    def test_scan_count_increases_only_for_real_rescans(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        movies = [{"tmdb_id": 1, "release_date": "2026-01-02", "title": "影片"}]
        key = self.subject._save_monthly_archive(task, movies, count_scan=True)
        self.subject._save_monthly_archive(task, movies)
        self.assertEqual(self.subject._load_monthly_archive(key)["scan_count"], 1)
        self.subject._save_monthly_archive(task, movies, count_scan=True)
        self.assertEqual(self.subject._monthly_archive_summaries()[0]["scan_count"], 2)

    def test_month_combines_different_score_scans_without_duplicates(self):
        first = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-10"}
        second = {"year": 2026, "month": 1, "min_score": 8, "scanned_at": "2026-01-11"}
        self.subject._save_monthly_archive(first, [
            {"tmdb_id": 1, "title": "旧名", "release_date": "2026-01-02"},
            {"tmdb_id": 2, "title": "只在旧扫描", "release_date": "2026-01-03"},
        ], count_scan=True)
        self.subject._save_monthly_archive(second, [
            {"tmdb_id": 1, "title": "新名", "release_date": "2026-01-02"},
        ], count_scan=True)
        month = self.subject._load_monthly_archive_month(2026, 1)
        self.assertEqual(month["candidate_count"], 2)
        self.assertEqual(month["scan_count"], 2)
        self.assertEqual(next(item for item in month["candidates"] if item["tmdb_id"] == 1)["title"], "新名")
        self.assertEqual(self.subject._monthly_archive_summaries()[0]["month_candidate_count"], 2)

    def test_legacy_archive_adds_scan_count_without_erasing_movies(self):
        path = Path(self.tempdir.name) / "monthly_scans.sqlite"
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute("CREATE TABLE monthly_scans (scan_key TEXT PRIMARY KEY, year INTEGER, "
                           "month INTEGER, min_score REAL, scanned_at TEXT, candidate_count INTEGER)")
                db.execute("INSERT INTO monthly_scans VALUES ('2026-01-7', 2026, 1, 7, '', 1)")
        self.assertEqual(self.subject._monthly_archive_summaries()[0]["scan_count"], 1)

    def test_archive_day_uses_live_plugin_history_and_emby_index(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 7, "title": "中文影片 1"},
            {"tmdb_id": 2, "release_date": "2026-01-03", "score": 7, "title": "中文影片 2"},
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

    def test_two_resources_prioritize_resolution_then_seeders(self):
        def context(name, seeders, size):
            return SimpleNamespace(meta_info=SimpleNamespace(resource_pix=""),
                                   torrent_info=SimpleNamespace(site=1, site_name="测试站点",
                                       enclosure=name, page_url=name, title=name,
                                       size=size, seeders=seeders))
        options = self.subject._monthly_resource_options([
            context("Film.1080p", 100, 2 * 1024 ** 3),
            context("Film.2160p.low", 2, 9 * 1024 ** 3),
            context("Film.2160p.high", 20, 12 * 1024 ** 3),
        ])
        self.assertEqual(len(options), 2)
        self.assertEqual([item["seeders"] for item in options], [20, 2])
        self.assertEqual(options[0]["resolution"], "2160P")

    def test_resource_only_hides_unmatched_titles(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 8, "title": "有资源"},
            {"tmdb_id": 2, "release_date": "2026-01-03", "score": 8, "title": "无资源"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_monthly_resource_cache = lambda *_args: {"1": [{"id": "option1"}], "2": []}
        self.subject._load_stats_history = lambda: []
        self.subject._load_download_queue = lambda: []
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": set()}
        result = self.subject._api_secure_monthly({
            "archive_key": key, "resources_only": True, "min_score": 7,
            "access_token": "test",
        })
        self.assertEqual(result["data"]["total"], 1)
        self.assertEqual(result["data"]["items"][0]["tmdb_id"], 1)

    def test_manual_batch_rejects_forged_or_duplicate_resource_ids(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 8, "title": "影片"},
        ])
        self.subject._load_monthly_resource_cache = lambda *_args: {"1": [{"id": "allowed"}]}
        result = self.subject._start_monthly_batch_download(2026, 1, [
            {"tmdb_id": 1, "resource_id": "forged"},
        ])
        self.assertFalse(result["success"])
        result = self.subject._start_monthly_batch_download(2026, 1, [
            {"tmdb_id": 1, "resource_id": "allowed"},
            {"tmdb_id": 1, "resource_id": "allowed"},
        ])
        self.assertFalse(result["success"])

    def test_successful_submission_removes_same_movie_from_shared_waiting_queue(self):
        class FakeDownloadChain:
            succeed = False

            def download_single(self, **_kwargs):
                return ("download-id", None) if self.succeed else (None, "下载失败")

        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = FakeDownloadChain
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.subject._record_download = lambda *_args: None
        self.store["download_queue"] = [
            {"key": "same", "tmdb_id": 1}, {"key": "other", "tmdb_id": 2},
        ]
        media = SimpleNamespace(tmdb_id=1)
        with self.subject._queue_lock:
            self.assertFalse(self.subject._submit_download(media, SimpleNamespace())[0])
        self.assertEqual(len(self.store["download_queue"]), 2)
        FakeDownloadChain.succeed = True
        with self.subject._queue_lock:
            self.assertTrue(self.subject._submit_download(media, SimpleNamespace())[0])
        self.assertEqual([item["key"] for item in self.store["download_queue"]], ["other"])

    def test_queue_drain_does_not_restore_removed_entry_from_old_snapshot(self):
        media = SimpleNamespace(tmdb_id=1, title_year="测试影片")
        context = SimpleNamespace(media_info=media)
        class FakeSearchChain:
            def search_by_id(self, **_kwargs):
                return [context]

        original = namespace.get("SearchChain")
        namespace["SearchChain"] = FakeSearchChain
        self.addCleanup(lambda: namespace.__setitem__("SearchChain", original))
        self.subject._torrent_identity = lambda _context: "resource"
        self.subject._active_download_count = lambda: 0
        self.subject._max_active_downloads = 2
        self.subject._site_ids = [1]
        self.store["download_queue"] = [
            {"key": "one", "tmdb_id": 1, "title": "测试影片", "torrent_identity": "resource"},
        ]
        def submit(movie, _context, **_kwargs):
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(self.store["download_queue"], [])

    def test_five_task_limit_does_not_overwrite_existing_tasks(self):
        self.store["monthly_movie_tasks"] = [{"id": str(i)} for i in range(5)]
        result = self.subject._api_monthly_action("monthly_save", {
            "year": 2026, "month": 1, "min_score": 7,
        })
        self.assertFalse(result["success"])
        self.assertEqual(len(self.subject._load_monthly_tasks()), 5)


if __name__ == "__main__":
    unittest.main()
