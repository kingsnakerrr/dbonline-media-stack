"""TG 管理按钮的轻量回归测试，不依赖 MoviePilot 运行环境。"""
import ast
import html
import shutil
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).with_name("__init__.py")
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SmartMoviePush")
selected = {"_telegram_control_action", "_telegram_disk_message", "_show_telegram_controls"}
methods = [node for node in plugin.body if isinstance(node, ast.FunctionDef) and node.name in selected]
namespace = {"Any": object, "html": html, "shutil": shutil, "threading": threading, "logger": SimpleNamespace(error=lambda *_: None)}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="TelegramMethods", bases=[], keywords=[], body=methods, decorator_list=[])] , type_ignores=[])), str(SOURCE), "exec"), namespace)
TelegramMethods = namespace["TelegramMethods"]


class TelegramControlTests(unittest.TestCase):
    def setUp(self):
        self.bot = TelegramMethods()
        self.bot._enabled = True
        self.bot._auto_push = False
        self.bot._auto_download = False
        self.bot._random_download_enabled = True
        self.bot._annual_dispatch_enabled = False
        self.bot._disk_guard_blocks_new = lambda: False
        self.bot._current_config = lambda: {"random_download_enabled": self.bot._random_download_enabled}
        self.configs = []
        self.bot.update_config = lambda value: self.configs.append(value)
        self.bot._append_plugin_log = lambda *_: None
        self.bot.process_download_queue = lambda: None

    def test_random_pause_is_independent_of_annual_and_push(self):
        self.assertIn("暂停", self.bot._telegram_control_action("random_stop"))
        self.assertFalse(self.bot._random_download_enabled)
        self.assertFalse(self.bot._auto_push)
        self.assertFalse(self.bot._annual_dispatch_enabled)
        self.assertIn("启动", self.bot._telegram_control_action("annual_start"))
        self.assertTrue(self.bot._annual_dispatch_enabled)
        self.assertFalse(self.bot._random_download_enabled)
        self.assertIn("启动", self.bot._telegram_control_action("push_start"))
        self.assertTrue(self.bot._auto_push)
        self.assertFalse(self.bot._random_download_enabled)

    def test_random_start_enables_automatic_mode_and_keeps_other_settings(self):
        self.bot._random_download_enabled = False
        self.assertIn("启动", self.bot._telegram_control_action("random_start"))
        self.assertTrue(self.bot._random_download_enabled)
        self.assertTrue(self.bot._auto_download)
        self.assertFalse(self.bot._annual_dispatch_enabled)

    def test_start_blocked_by_disk_guard_but_stop_allowed(self):
        self.bot._disk_guard_blocks_new = lambda: True
        self.assertIn("硬盘保护", self.bot._telegram_control_action("annual_start"))
        self.assertFalse(self.bot._annual_dispatch_enabled)
        self.bot._auto_push = True
        self.assertIn("暂停", self.bot._telegram_control_action("push_stop"))
        self.assertFalse(self.bot._auto_push)

    def test_disk_message_has_used_free_and_guard(self):
        self.bot._disk_guard_path = "/tmp"
        self.bot._disk_guard_enabled = True
        self.bot._disk_guard_threshold_gb = 300
        self.bot._disk_guard_recover_gb = 500
        usage = SimpleNamespace(total=1000 * 1024 ** 3, used=600 * 1024 ** 3, free=400 * 1024 ** 3)
        with patch.object(shutil, "disk_usage", return_value=usage):
            message = self.bot._telegram_disk_message()
        self.assertIn("已使用：600.0 GB", message)
        self.assertIn("剩余：400.0 GB", message)
        self.assertIn("60.0%", message)

    def test_control_menu_denies_non_admin(self):
        self.bot._is_telegram_admin = lambda *_: False
        replies = []
        self.bot._reply_telegram_action = lambda *args: replies.append(args)
        self.bot._show_telegram_controls("123", "guest")
        self.assertEqual("无操作权限", replies[0][0])


if __name__ == "__main__":
    unittest.main()
