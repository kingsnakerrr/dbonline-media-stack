"""Regression checks for plugin error logging and Telegram alert throttling."""

import ast
import hashlib
import re
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import List
from zoneinfo import ZoneInfo


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
names = {"_load_plugin_logs", "_append_plugin_log", "_safe_error_text",
         "_notify_plugin_error", "_report_error"}
methods = [node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name in names]


class ImmediateThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


warnings = []
namespace = {
    "Any": object,
    "List": List,
    "datetime": datetime,
    "hashlib": hashlib,
    "re": re,
    "threading": SimpleNamespace(Thread=ImmediateThread),
    "time": time,
    "pytz": SimpleNamespace(timezone=ZoneInfo),
    "settings": SimpleNamespace(TZ="Asia/Shanghai"),
    "logger": SimpleNamespace(error=lambda *_a, **_kw: None,
                              warning=lambda message: warnings.append(message)),
}
test_class = ast.ClassDef(name="ErrorAlertsUnderTest", bases=[], keywords=[], body=methods, decorator_list=[])
exec(compile(ast.fix_missing_locations(ast.Module(body=[test_class], type_ignores=[])), str(SOURCE), "exec"), namespace)
ErrorAlertsUnderTest = namespace["ErrorAlertsUnderTest"]


class ErrorAlertTest(unittest.TestCase):
    def setUp(self):
        self.subject = ErrorAlertsUnderTest()
        self.subject._plugin_logs_key = "plugin_logs"
        self.subject._error_alerts_key = "error_alerts"
        self.subject._plugin_log_lock = threading.RLock()
        self.subject._error_alert_lock = threading.RLock()
        self.data = {}
        self.sent = []
        self.subject.get_data = lambda key: self.data.get(key)
        self.subject.save_data = lambda key, value: self.data.__setitem__(key, value)
        self.subject._telegram_target = lambda: "admin"
        self.subject._send_telegram_direct = lambda **kwargs: self.sent.append(kwargs) or ("bot", {"success": True})

    def test_errors_are_logged_each_time_but_telegram_is_throttled(self):
        self.subject._report_error("Emby", "connection timeout")
        self.subject._report_error("Emby", "connection timeout")
        self.assertEqual(len(self.data["plugin_logs"]), 2)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("connection timeout", self.sent[0]["text"])
        self.assertIn("时间：", self.sent[0]["text"])

    def test_telegram_failure_does_not_trigger_recursive_alert(self):
        self.subject._report_error("Telegram", "bot unavailable", notify=False)
        self.assertEqual(self.data["plugin_logs"][0]["level"], "error")
        self.assertEqual(self.sent, [])

    def test_credentials_are_redacted_from_logs_and_alerts(self):
        self.subject._report_error("Emby", "GET https://host/Items?api_key=private123&Limit=1 token: secret456")
        self.assertNotIn("private123", self.data["plugin_logs"][0]["message"])
        self.assertNotIn("secret456", self.sent[0]["text"])
        self.assertIn("[REDACTED]", self.sent[0]["text"])


if __name__ == "__main__":
    unittest.main()
