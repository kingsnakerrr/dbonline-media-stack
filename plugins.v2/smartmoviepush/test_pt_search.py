"""Regression checks for M-Team API errors that used to appear as empty resources."""

import ast
import math
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
method = next(node for node in plugin.body if isinstance(node, ast.FunctionDef)
              and node.name == "_request_mteam_torrents")


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
    "time": time, "math": math,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[
    next(node for node in tree.body if isinstance(node, ast.ClassDef)
         and node.name == "PTSearchUnavailable"),
    ast.ClassDef(name="SearchUnderTest", bases=[], keywords=[], body=[method], decorator_list=[]),
], type_ignores=[])), str(SOURCE), "exec"), namespace)
SearchUnderTest = namespace["SearchUnderTest"]
PTSearchUnavailable = namespace["PTSearchUnavailable"]


class PTSearchTest(unittest.TestCase):
    def setUp(self):
        SearchUnderTest._pt_request_lock = threading.RLock()
        SearchUnderTest._pt_next_request_at = 0.0
        SearchUnderTest._pt_cooldown_until = 0.0
        self.subject = SearchUnderTest()
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


if __name__ == "__main__":
    unittest.main()
