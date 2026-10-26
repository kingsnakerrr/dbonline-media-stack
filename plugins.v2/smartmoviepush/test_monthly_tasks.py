"""Focused regression tests for the five independent month/score tasks."""

import ast
import calendar
import copy
import json
import re
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple
from urllib.parse import urlencode


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
methods = {"_load_monthly_tasks", "_monthly_task", "_update_monthly_task",
           "_scan_monthly_task", "_api_monthly_action",
           "_monthly_scan_key", "_monthly_archive", "_save_monthly_archive",
           "_load_monthly_archive", "_load_monthly_archive_month", "_monthly_archive_summaries", "_api_secure_monthly",
           "_chinese_movie_title", "_monthly_resource_rank", "_monthly_resource_options",
           "_torrent_identity", "_start_monthly_batch_download", "_run_monthly_batch_download",
           "_remember_monthly_resource_contexts", "_cached_monthly_resource_context",
           "_start_monthly_resource_scan",
           "_scan_monthly_resources", "_load_monthly_resource_cache", "_save_monthly_resource_cache",
           "_load_download_queue", "_load_no_resource", "_remove_queued_movie", "_mp_active_movie_ids", "_download_value",
           "_recheck_no_resource_worker",
           "_submit_download", "_api_clear_queue", "_search_best",
           "process_download_queue", "_active_download_counts", "_active_download_snapshot",
           "_is_plugin_download_row", "_format_speed", "_localized_download_state",
           "_archived_chinese_movie_title"}
selected = [node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name in methods]


class FakeDiscover:
    _urls = {"movies": "discover/movie"}

    def _request_obj(self, _url, _params, **_kwargs):
        self.last_params = _params
        assert "language=" not in _params, "TMDB client appends language automatically"
        return {"total_pages": 1, "results": [
            {"id": 1, "title": "美国电影", "release_date": "2026-01-02", "vote_average": 8.0,
             "poster_path": "/1.jpg"},
            {"id": 2, "title": "台湾电影", "release_date": "2026-01-03", "vote_average": 7.4},
            {"id": 3, "title": "其他地区", "release_date": "2026-01-04", "vote_average": 9.0},
        ]}


class FakeTmdbApi:
    def __init__(self, language=None):
        assert language == "zh-CN"
        self.discover = FakeDiscover()

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
    "calendar": calendar, "datetime": datetime, "timedelta": timedelta, "time": time,
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
    "PTSearchUnavailable": type("PTSearchUnavailable", (RuntimeError,), {}),
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
        self.subject._annual_last_check_key = "annual_last_check_at"
        self.subject._pt_annual_daily_limit = 300
        self.subject._pt_cooldown_key = "mteam_cooldown_until"
        self.subject._download_queue_key = "download_queue"
        self.subject._no_resource_key = "no_resource_movies"
        self.subject._resource_recheck_key = "no_resource_recheck"
        self.subject._resource_recheck_lock = threading.Lock()
        self.subject._push_interval_minutes = 60
        self.subject._enabled = True
        self.subject._annual_dispatch_enabled = False
        self.subject._random_download_enabled = True
        self.subject._annual_dispatch_count = 5
        self.subject._max_active_downloads = 10
        self.subject._annual_max_active_downloads = 5
        self.subject._disk_guard_blocks_new = lambda: False
        self.subject.get_data_path = lambda: Path(self.tempdir.name)
        self.store = {}
        self.subject.get_data = self.store.get
        self.subject.save_data = self.store.__setitem__
        self.subject._load_stats_history = lambda: []
        self.logs = []
        self.subject._append_plugin_log = lambda *args: self.logs.append(args)
        self.subject._report_error = lambda category, message, **_kwargs: self.logs.append((category, message, "error"))
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: namespace["SearchChain"]().search_by_id(
            tmdbid=movie_id, mtype=namespace["MediaType"].MOVIE,
            sites=getattr(self.subject, "_site_ids", [1]), cache_local=False) or []

    def test_queue_removes_movies_already_in_emby_or_active_in_mp(self):
        self.store["download_queue"] = [
            {"key": "emby", "tmdb_id": 11, "title": "已入库"},
            {"key": "mp", "tmdb_id": 22, "title": "MP 下载中"},
        ]
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": {"11"}}
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            SimpleNamespace(media={"tmdbid": 22})])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.subject.process_download_queue()
        self.assertEqual(self.store["download_queue"], [])
        self.assertTrue(any("移除 2 条" in log[1] for log in self.logs))

    def test_queue_waits_when_emby_cannot_be_verified(self):
        self.store["download_queue"] = [{"key": "waiting", "tmdb_id": 33, "title": "待核对"}]
        self.subject._library_snapshot_for_scan = lambda force=False: None
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.subject.process_download_queue()
        self.assertEqual(len(self.store["download_queue"]), 1)

    def test_queue_removes_movie_already_submitted_by_random_download(self):
        self.store["download_queue"] = [{"key": "annual", "tmdb_id": 11,
                                         "title": "重复电影", "source": "annual"}]
        self.subject._load_stats_history = lambda: [{"tmdb_id": 11, "source": "random"}]
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.subject.process_download_queue()
        self.assertEqual(self.store["download_queue"], [])

    def test_clearing_annual_waiting_keeps_random_waiting(self):
        self.store["download_queue"] = [
            {"key": "year", "tmdb_id": 1, "source": "annual"},
            {"key": "random", "tmdb_id": 2, "source": "random"},
        ]
        result = self.subject._api_clear_queue("annual")
        self.assertTrue(result["success"])
        self.assertEqual([item["key"] for item in self.store["download_queue"]], ["random"])

    def test_clearing_non_annual_waiting_keeps_annual_candidates(self):
        self.store["download_queue"] = [
            {"key": "year", "tmdb_id": 1, "source": "annual"},
            {"key": "random", "tmdb_id": 2, "source": "random"},
        ]
        result = self.subject._api_clear_queue("non_annual")
        self.assertTrue(result["success"])
        self.assertEqual([item["key"] for item in self.store["download_queue"]], ["year"])

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

    def test_single_movie_recheck_ignores_empty_cache_and_scans_only_target(self):
        candidates = [
            {"tmdb_id": 1136867, "score": 6.3, "vote_count": 1467, "title": "物质主义者"},
            {"tmdb_id": 2, "score": 8.0, "vote_count": 2000, "title": "其他影片"},
        ]
        self.subject._load_monthly_archive_month = lambda *_args: {
            "min_score": 6, "candidates": candidates}
        self.subject._load_monthly_resource_cache = lambda *_args: {"1136867": []}
        self.subject._load_download_queue = lambda: [{"tmdb_id": 1136867, "source": "random"}]
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._scan_monthly_resources = lambda *_args: None
        result = self.subject._start_monthly_resource_scan(
            2025, 0, 6, force=True, target_tmdb_id="1136867")
        self.assertTrue(result["success"])
        self.assertEqual(self.subject._monthly_resource_job["total"], 1)
        self.assertEqual(self.subject._monthly_resource_job["target_tmdb_id"], "1136867")

    def test_single_movie_recheck_jumps_ahead_of_running_annual_scan(self):
        candidates = [
            {"tmdb_id": 2, "score": 8, "vote_count": 2000, "title": "其他影片"},
            {"tmdb_id": 1136867, "score": 6.3, "vote_count": 1467, "title": "物质主义者"},
        ]
        self.subject._load_monthly_archive_month = lambda *_args: {
            "min_score": 6, "candidates": candidates}
        self.subject._load_monthly_resource_cache = lambda *_args: {"1136867": []}
        self.subject._load_download_queue = lambda: [{"tmdb_id": 1136867}]
        self.subject._load_stats_history = lambda: []
        self.subject._library_snapshot_for_scan = lambda: {"tmdb_ids": set()}
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._site_ids = [1]
        self.subject._monthly_resource_options = lambda contexts: [{"id": "found"}] if contexts else []
        self.subject._remember_monthly_resource_contexts = lambda *_args: None
        saved, searched = [], []
        self.subject._save_monthly_resource_cache = lambda _year, _month, movie_id, options: saved.append((movie_id, options))
        def search_by_id(**kwargs):
            searched.append(kwargs["tmdbid"])
            return [SimpleNamespace()] if kwargs["tmdbid"] == 1136867 else []
        original = namespace.get("SearchChain")
        namespace["SearchChain"] = lambda: SimpleNamespace(search_by_id=search_by_id)
        self.addCleanup(lambda: namespace.__setitem__("SearchChain", original))
        self.assertTrue(self.subject._start_monthly_resource_scan(2025, 0, 6)["success"])
        self.assertTrue(self.subject._start_monthly_resource_scan(
            2025, 0, 6, force=True, target_tmdb_id="1136867")["success"])
        self.assertEqual(self.subject._monthly_resource_job["priority_ids"], ["1136867"])
        self.subject._scan_monthly_resources(2025, 0, candidates, False)
        self.assertEqual(searched, [1136867, 2], (self.subject._monthly_resource_job, self.logs))
        self.assertIn(("1136867", [{"id": "found"}]), saved)

    def test_bulk_recheck_prioritizes_selected_movies_during_scan(self):
        candidates = [{"tmdb_id": index, "score": 8, "vote_count": index}
                      for index in range(1, 5)]
        self.subject._load_monthly_archive_month = lambda *_args: {
            "min_score": 7, "candidates": candidates}
        self.subject._load_monthly_resource_cache = lambda *_args: {}
        self.subject._load_download_queue = lambda: []
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._scan_monthly_resources = lambda *_args: None
        self.assertTrue(self.subject._start_monthly_resource_scan(2026, 0, 7)["success"])
        result = self.subject._start_monthly_resource_scan(
            2026, 0, 7, force=True, target_tmdb_ids=["1", "3"])
        self.assertTrue(result["success"])
        self.assertEqual(self.subject._monthly_resource_job["priority_ids"], ["1", "3"])

    def test_empty_resource_cache_expires_earlier_than_matched_resources(self):
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._save_monthly_resource_cache(2025, 0, "empty", [])
        self.subject._save_monthly_resource_cache(2025, 0, "found", [{"id": "torrent"}])
        with closing(self.subject._monthly_archive()) as db:
            db.execute("UPDATE monthly_resource_cache SET checked_at=?",
                       (time.time() - 10 * 60,))
            db.commit()
        cached = self.subject._load_monthly_resource_cache(2025, 0)
        self.assertNotIn("empty", cached)
        self.assertEqual(cached["found"], [{"id": "torrent"}])

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

    def test_month_scan_does_not_filter_production_country(self):
        self.store["monthly_movie_tasks"] = [{
            "id": "one", "year": 2026, "month": 1, "min_score": 7.0,
            "scan_state": "pending", "candidates": [],
        }]
        self.subject._scan_monthly_task("one")
        task = self.subject._monthly_task("one")
        self.assertEqual(task["scan_state"], "complete")
        self.assertEqual({item["tmdb_id"] for item in task["candidates"]}, {1, 2, 3})
        self.assertTrue(all("info" in item for item in task["candidates"]))
        first = next(item for item in task["candidates"] if item["tmdb_id"] == 1)
        self.assertEqual(first["display_title"], "美国电影")
        self.assertEqual(first["poster_path"], "/1.jpg")
        self.assertEqual(self.subject._load_monthly_archive(task["scan_key"])["candidate_count"], 3)

    def test_annual_scan_error_identifies_rejected_tmdb_window(self):
        class RejectingDiscover(FakeDiscover):
            def _request_obj(self, _url, _params, **_kwargs):
                raise RuntimeError("Invalid parameters: Your request parameters are incorrect.")

        original = namespace["TmdbApi"]
        namespace["TmdbApi"] = lambda language: SimpleNamespace(discover=RejectingDiscover())
        self.addCleanup(lambda: namespace.__setitem__("TmdbApi", original))
        self.store["monthly_movie_tasks"] = [{
            "id": "year2024", "year": 2024, "month": 0, "min_score": 6.0,
            "min_votes": 50, "scan_state": "pending", "candidates": [],
        }]
        self.subject._scan_monthly_task("year2024")
        task = self.subject._monthly_task("year2024")
        self.assertEqual(task["scan_state"], "error")
        self.assertIn("2024 年 1 月 1–31 日", task["scan_error"])
        self.assertIn("Invalid parameters", task["scan_error"])

    def test_annual_scan_keeps_mainstream_below_score_floor_and_deduplicates(self):
        class AnnualDiscover(FakeDiscover):
            def _request_obj(self, _url, _params, **_kwargs):
                return {"total_pages": 1, "results": [
                    {"id": 1, "release_date": "2026-01-02", "vote_average": 8.0,
                     "vote_count": 100},
                    {"id": 2, "release_date": "2026-01-03", "vote_average": 5.0,
                     "vote_count": 80},
                ]}

        original = namespace["TmdbApi"]
        namespace["TmdbApi"] = lambda language: SimpleNamespace(discover=AnnualDiscover())
        self.addCleanup(lambda: namespace.__setitem__("TmdbApi", original))
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

    def test_annual_list_keeps_unmatched_titles_without_presearch(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 8, "title": "有资源"},
            {"tmdb_id": 2, "release_date": "2026-01-03", "score": 8, "title": "无资源"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_monthly_resource_cache = lambda *_args: self.fail("opening list must not search PT cache")
        self.subject._load_stats_history = lambda: []
        self.subject._load_download_queue = lambda: []
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {"2": {"status": "no_resource"}}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": set()}
        result = self.subject._api_secure_monthly({
            "archive_key": key, "min_score": 7,
            "status": "not_downloaded", "access_token": "test",
        })
        self.assertEqual(result["data"]["total"], 2)
        unmatched = next(item for item in result["data"]["items"] if item["tmdb_id"] == 2)
        self.assertEqual(unmatched["status"], "candidate")
        self.assertNotIn("resources", unmatched)

    def test_new_pt_match_replaces_stale_no_resource_status(self):
        task = {"year": 2026, "month": 0, "min_score": 7, "scanned_at": "2026-12-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 2, "release_date": "2026-01-03", "score": 8, "title": "重新找到资源"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_monthly_resource_cache = lambda *_args: {"2": [{"id": "new-match"}]}
        self.subject._load_stats_history = lambda: []
        self.subject._load_download_queue = lambda: []
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {"2": {"status": "no_resource"}}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": set()}
        result = self.subject._api_secure_monthly({
            "archive_key": key, "resources_only": True, "min_score": 7,
            "status": "not_downloaded", "access_token": "test",
        })
        self.assertEqual(result["data"]["total"], 1)
        self.assertEqual(result["data"]["items"][0]["status"], "candidate")

    def test_annual_list_shows_random_queue_and_filters_not_downloaded(self):
        task = {"year": 2026, "month": 0, "min_score": 7, "scanned_at": "2026-12-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 8, "title": "随机等候"},
            {"tmdb_id": 2, "release_date": "2026-01-03", "score": 8, "title": "可下载"},
            {"tmdb_id": 3, "release_date": "2026-01-04", "score": 8, "title": "已入库"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_monthly_resource_cache = lambda *_args: {
            str(movie_id): [{"id": f"option{movie_id}"}] for movie_id in (2, 3)}
        self.subject._load_stats_history = lambda: []
        self.subject._load_download_queue = lambda: [{"tmdb_id": 1, "source": "random"}]
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": {"3"}}
        result = self.subject._api_secure_monthly({
            "archive_key": key, "resources_only": True, "min_score": 7,
            "page_size": 1000, "status": "not_downloaded", "access_token": "test",
        })
        self.assertEqual(result["data"]["total"], 2)
        self.assertEqual(result["data"]["page_size"], 1000)
        queued = next(item for item in result["data"]["items"] if item["tmdb_id"] == 1)
        self.assertEqual((queued["status"], queued["queue_source"]), ("queued", "random"))
        self.assertNotIn("resources", queued)
        ingested = self.subject._api_secure_monthly({
            "archive_key": key, "min_score": 7, "status": "emby_all", "access_token": "test",
        })
        self.assertEqual(ingested["data"]["counts"]["emby_all"], 1)
        self.assertEqual([item["tmdb_id"] for item in ingested["data"]["items"]], [3])

    def test_annual_list_marks_random_active_download_and_disallows_new_candidate(self):
        task = {"year": 2026, "month": 0, "min_score": 7, "scanned_at": "2026-12-31"}
        key = self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 8, "title": "随机正在下载"},
        ])
        self.subject._valid_access_token = lambda _token: True
        self.subject._load_stats_history = lambda: [{"tmdb_id": 1, "source": "random",
                                                      "download_id": "abc", "submitted_at": "2026-01-02"}]
        self.subject._history_view_status = lambda *_args: "unfinished"
        self.subject._load_download_queue = lambda: []
        self.subject._load_recent_pushes = lambda: {}
        self.subject._load_suppressed = lambda: {}
        self.subject._load_scan_cache = lambda **_kwargs: {}
        self.subject._library_snapshot_for_scan = lambda **_kwargs: {"tmdb_ids": set()}
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            {"download_hash": "abc", "media": {"tmdbid": 1}}])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        result = self.subject._api_secure_monthly({
            "archive_key": key, "min_score": 7, "access_token": "test",
        })
        row = result["data"]["items"][0]
        self.assertEqual((row["status"], row["download_source"]), ("downloading", "random"))

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

    def test_no_resource_selection_is_queued_without_pt_search(self):
        task = {"year": 2026, "month": 1, "min_score": 7, "scanned_at": "2026-01-31"}
        self.subject._save_monthly_archive(task, [
            {"tmdb_id": 1, "release_date": "2026-01-02", "score": 8,
             "title": "待搜影片", "info": {"id": 1, "title": "待搜影片"}},
        ])
        self.subject._load_monthly_resource_cache = lambda *_args: {"1": []}
        self.subject._load_stats_history = lambda: []
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._already_in_library = lambda _media: False
        self.subject._site_ids = [1]
        self.subject._submit_download = lambda *_args, **_kwargs: (True, "")
        original_media = namespace["MediaInfo"]
        original_search = namespace.get("SearchChain")
        original_download = namespace.get("DownloadChain")
        namespace["MediaInfo"] = lambda tmdb_info: SimpleNamespace(
            title_year=tmdb_info["title"], tmdb_id=tmdb_info["id"])
        searches = []
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: searches.append(movie_id) or [SimpleNamespace()]
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("MediaInfo", original_media))
        self.addCleanup(lambda: namespace.__setitem__("SearchChain", original_search))
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original_download))
        result = self.subject._start_monthly_batch_download(2026, 1, [
            {"tmdb_id": 1, "resource_id": ""},
        ])
        self.assertTrue(result["success"])
        self.subject._run_monthly_batch_download(2026, 1, [
            ({"tmdb_id": 1, "info": {"id": 1, "title": "待搜影片"}}, ""),
        ])
        self.assertEqual(searches, [])
        self.assertEqual(self.subject._monthly_batch_job["queued"], 1)
        self.assertEqual(self.store["download_queue"][0]["source"], "annual")

    def test_selected_twenty_register_immediately_and_skip_random_duplicates(self):
        movies = [( {"tmdb_id": movie_id, "info": {"id": movie_id, "title": f"影片 {movie_id}"}}, "")
                  for movie_id in range(1, 21)]
        self.subject._load_stats_history = lambda: []
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.store["download_queue"] = [
            {"key": f"random-{movie_id}", "tmdb_id": movie_id, "source": "random"}
            for movie_id in range(1, 6)]
        original_media = namespace["MediaInfo"]
        original_download = namespace.get("DownloadChain")
        namespace["MediaInfo"] = lambda tmdb_info: SimpleNamespace(
            title_year=tmdb_info["title"], tmdb_id=tmdb_info["id"])
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            SimpleNamespace(media={"tmdbid": 999}) for _ in range(10)])
        self.addCleanup(lambda: namespace.__setitem__("MediaInfo", original_media))
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original_download))
        self.subject._monthly_batch_job = {"running": True, "total": 20, "done": 0,
                                           "submitted": 0, "queued": 0, "skipped": 0,
                                           "errors": 0, "message": ""}
        self.subject._monthly_batch_lock.acquire()
        self.subject._run_monthly_batch_download(2024, 0, movies)
        queue = self.store["download_queue"]
        self.assertEqual(len(queue), 20)
        self.assertEqual(sum(row["source"] == "annual" for row in queue), 15)
        self.assertEqual([row["tmdb_id"] for row in queue[:15]], list(range(6, 21)))
        self.assertEqual(self.subject._monthly_batch_job["done"], 20)

    def test_previously_matched_resource_reuses_context_without_new_search(self):
        context = SimpleNamespace()
        self.subject._monthly_resource_scope = lambda: "sites"
        self.subject._torrent_identity = lambda _context: "matched"
        self.subject._monthly_resource_contexts = {}
        self.subject._remember_monthly_resource_contexts(2026, 1, "1", [context], [{"id": "matched"}])
        self.assertIs(self.subject._cached_monthly_resource_context(2026, 1, "1", "matched"), context)
        self.assertIsNone(self.subject._cached_monthly_resource_context(2026, 1, "1", "other"))

    def test_successful_submission_removes_same_movie_from_shared_waiting_queue(self):
        class FakeDownloadChain:
            succeed = False

            def downloading(self):
                return []

            def download_single(self, **_kwargs):
                return ("download-id", None) if self.succeed else (None, "下载失败")

        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = FakeDownloadChain
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        recorded = []
        self.subject._record_download = lambda *_args, **kwargs: recorded.append(kwargs)
        self.store["download_queue"] = [
            {"key": "same", "tmdb_id": 1}, {"key": "other", "tmdb_id": 2},
        ]
        media = SimpleNamespace(tmdb_id=1)
        with self.subject._queue_lock:
            self.assertFalse(self.subject._submit_download(media, SimpleNamespace())[0])
        self.assertEqual(len(self.store["download_queue"]), 2)
        FakeDownloadChain.succeed = True
        with self.subject._queue_lock:
            self.assertTrue(self.subject._submit_download(media, SimpleNamespace(), origin="annual")[0])
        self.assertEqual([item["key"] for item in self.store["download_queue"]], ["other"])
        self.assertEqual(recorded[-1]["source"], "annual")

    def test_queue_drain_does_not_restore_removed_entry_from_old_snapshot(self):
        media = SimpleNamespace(tmdb_id=1, title_year="测试影片")
        context = SimpleNamespace(media_info=media)
        class FakeSearchChain:
            def search_by_id(self, **_kwargs):
                return [context]

        original = namespace.get("SearchChain")
        namespace["SearchChain"] = FakeSearchChain
        self.addCleanup(lambda: namespace.__setitem__("SearchChain", original))
        original_download = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original_download))
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
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

    def test_annual_no_resource_does_not_block_next_candidate(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: ([] if movie_id == 1 else [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=2))])
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "one", "tmdb_id": 1, "title": "无资源", "source": "annual"},
            {"key": "two", "tmdb_id": 2, "title": "有资源", "source": "annual"},
        ]
        def submit(movie, _context, **_kwargs):
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual([item["key"] for item in self.store["download_queue"]], ["one"])
        self.assertEqual(self.store["download_queue"][0]["resource_misses"], 1)

    def test_annual_refill_searches_untouched_before_previous_misses(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        searched = []
        self.subject._search_site_contexts = lambda movie_id, **kwargs: searched.append(
            (movie_id, kwargs.get("keyword_index"))) or []
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "retry", "tmdb_id": 1, "title": "已搜空", "source": "annual",
             "resource_misses": 2,
             "last_resource_check": (datetime.now() - timedelta(minutes=61)).isoformat(timespec="seconds")},
            {"key": "fresh", "tmdb_id": 2, "title": "新候选", "source": "annual"},
        ]
        self.subject.process_download_queue()
        self.assertEqual(searched, [(2, 0), (1, 0)])
        self.assertEqual(self.store["download_queue"][0]["resource_keyword_index"], 1)
        self.assertTrue(self.store["annual_last_check_at"])

    def test_annual_check_time_updates_even_when_queue_is_empty(self):
        self.subject._annual_dispatch_enabled = True
        self.subject.process_download_queue()
        self.assertIsNotNone(datetime.fromisoformat(self.store["annual_last_check_at"]))

    def test_three_empty_searches_move_random_and_annual_to_no_resource(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        keyword_turns = []
        self.subject._search_site_contexts = lambda movie_id, **kwargs: keyword_turns.append(
            (movie_id, kwargs.get("keyword_index"))) or []
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "random", "tmdb_id": 1, "title": "随机无资源", "source": "random"},
            {"key": "annual", "tmdb_id": 2, "title": "年度无资源", "source": "annual"},
        ]
        for round_number in range(1, 4):
            for row in self.store["download_queue"]:
                row["last_resource_check"] = (datetime.now() - timedelta(minutes=61)).isoformat(timespec="seconds")
            self.subject.process_download_queue()
            if round_number < 3:
                self.assertEqual([row["resource_misses"] for row in self.store["download_queue"]],
                                 [round_number, round_number])
        self.assertEqual(self.store["download_queue"], [])
        self.assertEqual({row["source"] for row in self.store["no_resource_movies"]}, {"random", "annual"})
        self.assertTrue(all(row["resource_misses"] == 3 for row in self.store["no_resource_movies"]))
        self.assertEqual(keyword_turns, [(1, 0), (2, 0), (1, 1), (2, 1), (1, 2), (2, 2)])

    def test_site_limit_does_not_count_as_missing_resource(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        attempted = []
        def search(movie_id, **_kwargs):
            attempted.append(movie_id)
            raise namespace["PTSearchUnavailable"]("安全额度不足")
        self.subject._search_site_contexts = search
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "one", "tmdb_id": 1, "title": "一", "source": "random"},
            {"key": "two", "tmdb_id": 2, "title": "二", "source": "annual"},
        ]
        self.subject.process_download_queue()
        self.assertEqual(attempted, [1])
        self.assertEqual(len(self.store["download_queue"]), 2)
        self.assertFalse(self.store.get("no_resource_movies"))
        self.assertTrue(all(not row.get("resource_misses") for row in self.store["download_queue"]))

    def test_random_candidate_gets_search_turn_before_large_annual_backlog(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        attempted = []
        def search(movie_id, **_kwargs):
            attempted.append(movie_id)
            raise namespace["PTSearchUnavailable"]("安全额度不足")
        self.subject._search_site_contexts = search
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": str(movie_id), "tmdb_id": movie_id, "title": "年度", "source": "annual"}
            for movie_id in range(1, 30)
        ] + [{"key": "random", "tmdb_id": 100, "title": "随机", "source": "random"}]
        self.subject.process_download_queue()
        self.assertEqual(attempted, [100])

    def test_manual_recheck_found_resource_returns_to_original_queue(self):
        context = SimpleNamespace(media_info=SimpleNamespace(tmdb_id=2))
        self.subject._search_site_contexts = lambda _movie_id, **_kwargs: [context]
        self.subject._torrent_identity = lambda _context: "new-torrent"
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        item = {"key": "annual", "tmdb_id": 2, "title": "重查影片", "source": "annual",
                "resource_misses": 3, "last_error": "无资源"}
        self.store["no_resource_movies"] = [item]
        self.store["download_queue"] = []
        job = {"running": True, "total": 1, "done": 0, "found": 0, "still_missing": 0, "skipped": 0, "message": ""}
        self.subject._resource_recheck_lock.acquire()
        self.subject._recheck_no_resource_worker([item], job)
        self.assertEqual(self.store["no_resource_movies"], [])
        self.assertEqual(self.store["download_queue"][0]["source"], "annual")
        self.assertEqual(self.store["download_queue"][0]["torrent_identity"], "new-torrent")
        self.assertEqual(self.store["no_resource_recheck"]["found"], 1)

    def test_failed_annual_candidate_does_not_block_next_and_cools_down(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._annual_dispatch_count = 2
        self.subject.get_data = lambda key: copy.deepcopy(self.store.get(key))
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "failed", "tmdb_id": 1, "title": "种子故障", "source": "annual"},
            {"key": "working", "tmdb_id": 2, "title": "正常影片", "source": "annual"},
        ]
        attempts = []
        def submit(movie, _context, **_kwargs):
            attempts.append(movie.tmdb_id)
            if movie.tmdb_id == 1:
                return False, "下载种子内容为空"
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(attempts, [1, 2])
        self.assertEqual([row["key"] for row in self.store["download_queue"]], ["failed"])
        self.assertEqual(self.store["download_queue"][0]["attempts"], 1)
        self.subject.process_download_queue()
        self.assertEqual(attempts, [1, 2], "手动重试也应尊重单片冷却期")
        self.store["download_queue"][0]["last_attempt"] = (
            datetime.now() - timedelta(minutes=16)).isoformat(timespec="seconds")
        self.subject.process_download_queue()
        self.assertEqual(attempts, [1, 2, 1])

    def test_failed_random_candidate_does_not_block_next(self):
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "failed", "tmdb_id": 1, "title": "种子故障", "source": "random"},
            {"key": "waiting", "tmdb_id": 2, "title": "后续影片", "source": "random"},
        ]
        attempts = []
        self.subject._submit_download = lambda movie, _context, **_kwargs: (
            attempts.append(movie.tmdb_id) or False, "下载种子内容为空")
        self.subject.process_download_queue()
        self.assertEqual(attempts, [1, 2])
        self.assertEqual(len(self.store["download_queue"]), 2)

    def test_failed_random_candidate_does_not_block_annual_refill(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "random-failed", "tmdb_id": 1, "title": "随机故障", "source": "random"},
            {"key": "annual", "tmdb_id": 2, "title": "年度影片", "source": "annual"},
            {"key": "random-later", "tmdb_id": 3, "title": "随机后续", "source": "random"},
        ]
        attempts = []
        def submit(movie, _context, **_kwargs):
            attempts.append(movie.tmdb_id)
            if movie.tmdb_id == 1:
                return False, "下载种子内容为空"
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(attempts, [1, 2, 3])
        self.assertEqual([row["key"] for row in self.store["download_queue"]],
                         ["random-failed"])

    def test_twenty_annual_candidates_fill_five_available_slots(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._max_active_downloads = 5
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": str(movie_id), "tmdb_id": movie_id, "title": f"影片 {movie_id}",
             "source": "annual", "torrent_identity": ""} for movie_id in range(1, 21)]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [1, 2, 3, 4, 5])
        self.assertEqual(len(self.store["download_queue"]), 15)

    def test_annual_candidates_wait_until_homepage_dispatch_is_started(self):
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "annual", "tmdb_id": 1, "title": "年度电影", "source": "annual"},
            {"key": "random", "tmdb_id": 2, "title": "随机电影", "source": "random"},
        ]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [2])
        self.assertEqual(len(self.store["download_queue"]), 1)
        self.subject._annual_dispatch_enabled = True
        self.subject.process_download_queue()
        self.assertEqual(submitted, [2, 1])

    def test_annual_refills_each_minute_with_per_check_limit(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._annual_dispatch_count = 2
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": str(movie_id), "tmdb_id": movie_id, "title": f"影片 {movie_id}", "source": "annual"}
            for movie_id in range(1, 6)]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [1, 2])
        self.subject.process_download_queue()
        self.assertEqual(submitted, [1, 2, 3, 4])
        self.subject.process_download_queue()
        self.assertEqual(submitted, [1, 2, 3, 4, 5])

    def test_random_slots_full_do_not_block_annual_download(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            {"download_hash": f"random-{i}", "media": {"tmdbid": 100 + i}} for i in range(10)])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "annual", "tmdb_id": 1, "title": "年度电影", "source": "annual"}]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [1])
        self.assertEqual(self.store["download_queue"], [])

    def test_annual_slots_full_do_not_block_random_download(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        self.subject._load_stats_history = lambda: [
            {"download_id": f"annual-{i}", "tmdb_id": 100 + i, "source": "annual"}
            for i in range(5)]
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            {"download_hash": f"annual-{i}", "media": {"tmdbid": 100 + i}}
            for i in range(5)])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "annual", "tmdb_id": 1, "title": "年度电影", "source": "annual"},
            {"key": "random", "tmdb_id": 2, "title": "随机电影", "source": "random"},
        ]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [2])
        self.assertEqual([row["tmdb_id"] for row in self.store["download_queue"]], [1])

    def test_mixed_queue_uses_one_slot_from_each_independent_limit(self):
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        self.subject._load_stats_history = lambda: [
            {"download_id": f"annual-{i}", "tmdb_id": 100 + i, "source": "annual"}
            for i in range(4)]
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            *({"download_hash": f"annual-{i}", "media": {"tmdbid": 100 + i}}
              for i in range(4)),
            *({"download_hash": f"random-{i}", "media": {"tmdbid": 200 + i}}
              for i in range(9)),
        ])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "annual", "tmdb_id": 1, "title": "年度电影", "source": "annual"},
            {"key": "random", "tmdb_id": 2, "title": "随机电影", "source": "random"},
        ]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [2, 1])
        self.assertEqual(self.store["download_queue"], [])

    def test_paused_random_queue_does_not_block_annual_download(self):
        self.subject._random_download_enabled = False
        self.subject._annual_dispatch_enabled = True
        self.subject._library_snapshot_for_scan = lambda force=False: {"tmdb_ids": set()}
        self.subject._search_site_contexts = lambda movie_id, **_kwargs: [
            SimpleNamespace(media_info=SimpleNamespace(tmdb_id=movie_id))]
        self.subject._torrent_identity = lambda _context: "resource"
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        self.store["download_queue"] = [
            {"key": "annual", "tmdb_id": 1, "title": "年度电影", "source": "annual"},
            {"key": "random", "tmdb_id": 2, "title": "随机电影", "source": "random"},
        ]
        submitted = []
        def submit(movie, _context, **_kwargs):
            submitted.append(movie.tmdb_id)
            self.subject._remove_queued_movie(movie.tmdb_id)
            return True, None
        self.subject._submit_download = submit
        self.subject.process_download_queue()
        self.assertEqual(submitted, [1])
        self.assertEqual([row["tmdb_id"] for row in self.store["download_queue"]], [2])

    def test_active_download_uses_saved_chinese_movie_title_and_state(self):
        self.subject._load_download_history = lambda: [
            {"download_id": "hash-1", "title": "二号陪审员 (2024)", "source": "annual"}]
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            {"download_hash": "hash-1", "name": "Juror 2 2024 2160p WEB-DL", "state": "downloading",
             "progress": 0.904, "dlspeed": 1024 * 1024},
        ])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        count, items = self.subject._active_download_snapshot()
        self.assertEqual(count, 1)
        self.assertEqual(items[0]["title"], "二号陪审员 (2024)")
        self.assertEqual(items[0]["state"], "下载中")
        self.assertEqual(items[0]["source"], "annual")

    def test_active_download_recovers_chinese_title_from_year_archive(self):
        archive = Path(self.tempdir.name) / "monthly_scans.sqlite"
        with closing(sqlite3.connect(archive)) as db:
            db.execute("CREATE TABLE monthly_scan_movies (tmdb_id TEXT, payload TEXT)")
            db.execute("INSERT INTO monthly_scan_movies VALUES (?, ?)",
                       ("123", json.dumps({"display_title": "二号陪审员", "year": 2024})))
            db.commit()
        self.subject._load_download_history = lambda: [
            {"download_id": "hash-1", "tmdb_id": 123, "title": "Juror #2 (2024)", "source": "annual"}]
        original = namespace.get("DownloadChain")
        namespace["DownloadChain"] = lambda: SimpleNamespace(downloading=lambda: [
            {"download_hash": "hash-1", "name": "Juror 2 2024 2160p WEB-DL", "state": "stalledDL"},
        ])
        self.addCleanup(lambda: namespace.__setitem__("DownloadChain", original))
        count, items = self.subject._active_download_snapshot()
        self.assertEqual(count, 1)
        self.assertEqual(items[0]["title"], "二号陪审员 (2024)")
        self.assertEqual(items[0]["state"], "等待下载")

    def test_five_task_limit_does_not_overwrite_existing_tasks(self):
        self.store["monthly_movie_tasks"] = [{"id": str(i)} for i in range(5)]
        result = self.subject._api_monthly_action("monthly_save", {
            "year": 2026, "month": 1, "min_score": 7,
        })
        self.assertFalse(result["success"])
        self.assertEqual(len(self.subject._load_monthly_tasks()), 5)


if __name__ == "__main__":
    unittest.main()
