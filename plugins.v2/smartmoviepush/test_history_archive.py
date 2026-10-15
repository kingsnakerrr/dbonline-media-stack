"""Regression test for status changes after a plugin download is archived."""

import ast
import json
import sqlite3
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List


SOURCE = Path(__file__).with_name("__init__.py")
METHODS = {
    "_load_download_history",
    "_history_archive",
    "_save_download_history",
    "_load_stats_history",
    "_save_reconciled_history",
    "_history_view_status",
}
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
selected = [node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name in METHODS]
namespace = {"json": json, "sqlite3": sqlite3, "threading": threading,
             "closing": closing, "List": List, "datetime": datetime, "timedelta": timedelta,
             "logger": type("Logger", (), {"error": print})()}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
                 name="HistoryUnderTest", bases=[], keywords=[], body=selected,
                 decorator_list=[])], type_ignores=[])),
             str(SOURCE), "exec"), namespace)
HistoryUnderTest = namespace["HistoryUnderTest"]


class HistoryArchiveTest(unittest.TestCase):
    def test_status_distinguishes_recent_organization_from_overdue_ingestion(self):
        subject = HistoryUnderTest()
        subject._parse_history_time = lambda value, _: datetime.fromisoformat(value)
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        self.assertEqual(subject._history_view_status({}, now, timezone.utc), "unfinished")
        self.assertEqual(subject._history_view_status(
            {"download_completed_at": now.isoformat()}, now, timezone.utc), "awaiting_library")
        self.assertEqual(subject._history_view_status(
            {"organized_at": (now - timedelta(hours=23)).isoformat()}, now, timezone.utc), "organized")
        self.assertEqual(subject._history_view_status(
            {"organized_at": (now - timedelta(hours=24)).isoformat()}, now, timezone.utc),
            "organized_not_ingested")
        self.assertEqual(subject._history_view_status(
            {"organized_at": (now - timedelta(hours=30)).isoformat(),
             "emby_ingested_at": now.isoformat()}, now, timezone.utc), "emby_ingested")

    def test_archived_movie_updates_without_moving_submission_date(self):
        with TemporaryDirectory() as directory:
            subject = HistoryUnderTest()
            subject._history_archive_lock = threading.RLock()
            subject.get_data_path = lambda: Path(directory)
            storage = {}
            subject.get_data = lambda key: storage.get(key)
            subject.save_data = lambda key, value: storage.__setitem__(key, value)
            subject._download_history_key = "download_history"
            movies = [{"record_uid": str(index), "submitted_at": "2026-10-15T12:00:00+08:00",
                       "download_id": str(index), "title": f"电影 {index}"}
                      for index in range(1001)]
            subject._save_download_history(movies)
            self.assertEqual(len(subject._load_download_history()), 1000)
            archived = subject._load_stats_history()[0]
            self.assertEqual(archived["record_uid"], "0")

            archived["download_completed_at"] = "2026-10-16T01:00:00+08:00"
            subject._save_reconciled_history([archived])
            archived = subject._load_stats_history()[0]
            archived["emby_ingested_at"] = "2026-10-16T02:00:00+08:00"
            subject._save_reconciled_history([archived])

            result = subject._load_stats_history()[0]
            self.assertEqual(result["submitted_at"], "2026-10-15T12:00:00+08:00")
            self.assertEqual(result["download_completed_at"], "2026-10-16T01:00:00+08:00")
            self.assertEqual(result["emby_ingested_at"], "2026-10-16T02:00:00+08:00")
            self.assertEqual(len(subject._load_download_history()), 1000)


if __name__ == "__main__":
    unittest.main()
