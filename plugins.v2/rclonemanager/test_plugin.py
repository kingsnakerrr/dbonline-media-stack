import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


fastapi = types.ModuleType("fastapi")
fastapi.Body = lambda default=None: default
sys.modules["fastapi"] = fastapi
sys.modules["app"] = types.ModuleType("app")
sys.modules["app.plugins"] = types.ModuleType("app.plugins")
sys.modules["app.plugins"]._PluginBase = object
spec = importlib.util.spec_from_file_location("rclone_panel", Path(__file__).with_name("__init__.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.panel = module.RcloneManager()
        self.panel.init_plugin({})

    def test_only_moviepilot_authenticated_routes(self):
        self.assertEqual({route["path"] for route in self.panel.get_api()}, {"/state", "/control"})
        self.assertTrue(all(route["auth"] == "bear" for route in self.panel.get_api()))

    def test_status_does_not_expose_task_secrets(self):
        task = {"id": 3, "name": "upload", "status": "running", "enabled": True, "qb_password": "secret"}
        with patch.object(self.panel, "_docker", return_value={"State": {"Running": True, "Status": "running"}}), patch.object(self.panel, "_manager", side_effect=[[task], {"speed": 1024, "transferring": []}]):
            result = self.panel._api_state({})
        self.assertTrue(result["success"])
        self.assertNotIn("qb_password", str(result))
        self.assertEqual(result["stats"]["speed"], 1024)
        self.assertEqual(result["tasks"][0]["display_status"], "running")

    def test_transfer_limit_and_simple_task_states(self):
        tasks = [
            {"id": 1, "name": "active", "enabled": True, "status": "running"},
            {"id": 2, "name": "waiting", "enabled": True, "status": "error", "last_error": "signal: killed"},
            {"id": 3, "name": "disabled", "enabled": False, "status": "idle"},
        ]
        files = [{"name": f"file-{i}", "bytes": i} for i in range(120)]
        container = {"State": {"Running": True, "Status": "running"}}
        with patch.object(self.panel, "_docker", return_value=container), patch.object(self.panel, "_manager", side_effect=[tasks, {"transferring": files}]):
            result = self.panel._api_state({"transfer_limit": 50})
        self.assertEqual(result["transfer_count"], 120)
        self.assertEqual(len(result["transferring"]), 50)
        self.assertEqual([task["display_status"] for task in result["tasks"]], ["running", "idle", "stopped"])
        self.assertEqual(result["tasks"][1]["error_hint"], "进程被强制终止，原因尚未确认")
        self.assertNotIn("signal: killed", str(result))
        with patch.object(self.panel, "_docker", return_value=container), patch.object(self.panel, "_manager", side_effect=[tasks, {"transferring": files}]):
            result = self.panel._api_state({"transfer_limit": 9999})
        self.assertEqual(result["transferring"], [])

    def test_error_hint_distinguishes_confirmed_oom_and_other_failures(self):
        self.assertEqual(self.panel._error_hint("内存不足：系统 OOM 击杀了 rclone（原始错误：signal: killed）"),
                         "内存不足：系统 OOM 已确认")
        self.assertEqual(self.panel._error_hint("存储空间不足（原始错误：exit status 1；disk full）"), "存储空间不足")
        self.assertEqual(self.panel._error_hint("signal: killed"), "进程被强制终止，原因尚未确认")

    def test_control_is_container_only(self):
        self.assertFalse(self.panel._api_control({"action": "restart"})["success"])
        with patch.object(self.panel, "_docker", return_value={}) as docker:
            self.assertTrue(self.panel._api_control({"action": "stop"})["success"])
            docker.assert_called_once_with("POST", "/containers/rclone-manager/stop?t=10")

    def test_missing_container_shows_install_state(self):
        def docker(method, path, body=None):
            if path == "/containers/rclone-manager/json":
                raise module.DockerError(404)
            return {}
        with patch.object(self.panel, "_docker", side_effect=docker):
            result = self.panel._api_state({})
        self.assertFalse(result["installed"])
        self.assertTrue(result["image_available"])

    def test_install_preserves_data_bind_and_existing_image(self):
        with patch.object(self.panel, "_docker", return_value={}) as docker:
            result = self.panel._api_control({"action": "install"})
        self.assertTrue(result["success"])
        spec = docker.call_args_list[0].args[2]
        self.assertEqual(spec["Image"], "zzmrclone-manager:local")
        self.assertIn("/opt/docker-compose/zzmrclone-manager/data:/app/data", spec["HostConfig"]["Binds"])
        self.assertEqual(docker.call_args_list[1].args[1], "/containers/rclone-manager/start")


if __name__ == "__main__":
    unittest.main()
