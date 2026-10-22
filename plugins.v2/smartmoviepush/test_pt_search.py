"""Regression checks for M-Team API errors that used to appear as empty resources."""

import ast
import math
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
method = next(node for node in plugin.body if isinstance(node, ast.FunctionDef)
              and node.name == "_request_mteam_torrents")
search_method = next(node for node in plugin.body if isinstance(node, ast.FunctionDef)
                     and node.name == "_search_site_contexts")


class MTorrentSpider:
    def __init__(self, _site):
        self._apikey = "test-key"
        self._ua = "test"
        self._proxy = None
        self._domain = "m-team.cc"
        self._timeout = 15
        self._searchurl = "https://api.m-team.cc/api/torrent/search"

    def __get_params(self, *_args):
        return {"keyword": "test"}

    def __parse_result(self, rows):
        assert all(isinstance(row.get("status"), dict) for row in rows)
        return [{"title": row["name"], "size": 1024} for row in rows]


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


namespace = {
    "MTorrentSpider": MTorrentSpider,
    "MediaType": SimpleNamespace(MOVIE="movie"),
    "TorrentInfo": lambda **values: SimpleNamespace(**values),
    "RequestUtils": lambda **_kwargs: SimpleNamespace(post_res=lambda **_kwargs: namespace["response"]),
    "time": time, "math": math, "Optional": Optional,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[
    next(node for node in tree.body if isinstance(node, ast.ClassDef)
         and node.name == "PTSearchUnavailable"),
    ast.ClassDef(name="SearchUnderTest", bases=[], keywords=[], body=[method], decorator_list=[]),
], type_ignores=[])), str(SOURCE), "exec"), namespace)
SearchUnderTest = namespace["SearchUnderTest"]
PTSearchUnavailable = namespace["PTSearchUnavailable"]
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="SearchKeywordsUnderTest", bases=[], keywords=[], body=[search_method], decorator_list=[]
)], type_ignores=[])), str(SOURCE), "exec"), namespace)


class PTSearchTest(unittest.TestCase):
    def setUp(self):
        SearchUnderTest._pt_request_lock = threading.RLock()
        SearchUnderTest._pt_next_request_at = 0.0
        SearchUnderTest._pt_cooldown_until = 0.0
        SearchUnderTest._pt_request_log_key = "mteam_search_attempts_24h"
        self.subject = SearchUnderTest()
        self.data = {}
        self.subject.get_data = lambda key: self.data.get(key)
        self.subject.save_data = lambda key, value: self.data.__setitem__(key, value)
        self.site = {"id": 1, "name": "馒头"}

    def test_rate_limit_is_error_not_empty_result_and_starts_cooldown(self):
        namespace["response"] = FakeResponse({"code": 4, "message": "請求過於頻繁", "data": None})
        with self.assertRaisesRegex(PTSearchUnavailable, "限流|频繁"):
            self.subject._request_mteam_torrents(self.site, "They Will Kill You")
        self.assertGreater(SearchUnderTest._pt_cooldown_until, time.monotonic())

    def test_null_status_in_torrent_is_parsed_safely(self):
        namespace["response"] = FakeResponse({"code": 0, "data": {
            "data": [{"name": "They Will Kill You 2026 2160p", "status": None}]}})
        torrents = self.subject._request_mteam_torrents(self.site, "They Will Kill You")
        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0].site, 1)

    def test_daily_budget_stops_search_before_site_request(self):
        self.data[self.subject._pt_request_log_key] = [time.time() - 10] * 600
        namespace["response"] = FakeResponse({"code": 0, "data": {"data": []}})
        with self.assertRaisesRegex(PTSearchUnavailable, "安全额度"):
            self.subject._request_mteam_torrents(self.site, "They Will Kill You")

    def test_success_records_attempt(self):
        namespace["response"] = FakeResponse({"code": 0, "data": {"data": []}})
        self.subject._request_mteam_torrents(self.site, "They Will Kill You")
        self.assertEqual(len(self.data[self.subject._pt_request_log_key]), 1)

    def test_queue_tries_chinese_title_before_english_and_original(self):
        namespace["SitesHelper"] = lambda: SimpleNamespace(get_indexers=lambda: [
            {"id": 1, "parser": "mTorrent"}])
        namespace["SearchChain"] = lambda: SimpleNamespace(recognize_media=lambda **_kwargs: SimpleNamespace(
            title="默杀", en_title="A Place Called Silence", original_title="Un lugar llamado silencio"))
        subject = namespace["SearchKeywordsUnderTest"]()
        subject._site_ids = [1]
        searched = []
        subject._request_mteam_torrents = lambda _site, keyword: searched.append(keyword) or []
        for index in range(3):
            self.assertEqual(subject._search_site_contexts(1300945, keyword_index=index), [])
        self.assertEqual(searched, ["默杀", "A Place Called Silence", "Un lugar llamado silencio"])


if __name__ == "__main__":
    unittest.main()

