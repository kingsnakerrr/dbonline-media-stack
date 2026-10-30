"""Monitor the standalone Rclone Manager without replacing its task engine."""

import http.client
import json
import socket
from datetime import datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit
from urllib.request import urlopen

from fastapi import Body
from app.plugins import _PluginBase


class _DockerConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=5)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect("/var/run/docker.sock")


class DockerError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Docker 接口返回 {status}")


class RcloneManager(_PluginBase):
    plugin_name = "Rclone Manager 控制台"
    plugin_desc = "独立 Rclone Manager 的运行开关、实时传输监控与原站跳转。"
    plugin_icon = "https://rclone.org/img/rclone-32x32.png"
    plugin_version = "0.3.4"
    plugin_author = "kingsnakerrr"
    plugin_config_prefix = "rclonemanager_"
    plugin_order = 70
    auth_level = 1

    def init_plugin(self, config: dict = None):
        configured_url = str((config or {}).get("url") or "").strip().rstrip("/")
        parsed = urlsplit(configured_url) if configured_url else None
        self._url = configured_url if parsed and parsed.scheme in ("http", "https") and parsed.netloc else ""

    def get_state(self) -> bool:
        return True

    def get_page(self) -> List[dict]:
        return []

    def stop_service(self):
        pass

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return ([{"component": "VForm", "content": [{"component": "VTextField",
                 "props": {"model": "url", "label": "Rclone Manager 网页地址（留空则使用当前主机的 7071 端口）"}}]}],
                {"url": ""})

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/state", "endpoint": self._api_state, "methods": ["POST"], "auth": "bear"},
            {"path": "/control", "endpoint": self._api_control, "methods": ["POST"], "auth": "bear"},
        ]

    @staticmethod
    def _docker(method: str, path: str, body: dict = None) -> dict:
        connection = _DockerConnection()
        try:
            data = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"} if data is not None else {}
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            data = response.read()
            if response.status not in (200, 201, 204, 304):
                raise DockerError(response.status)
            return json.loads(data) if data else {}
        finally:
            connection.close()

    @staticmethod
    def _manager(path: str):
        with urlopen("http://127.0.0.1:7071/api/" + path, timeout=5) as response:
            return json.load(response)

    @staticmethod
    def _error_hint(value: Any) -> str:
        message = str(value or "").strip()
        if not message:
            return "运行出错，请到原管理界面查看"
        if message.startswith("内存不足：系统 OOM"):
            return "内存不足：系统 OOM 已确认"
        if "signal: killed" in message:
            return "进程被强制终止，原因尚未确认"
        summary = message.split("（原始错误：", 1)[0]
        return summary[:60] + ("…" if len(summary) > 60 else "")

    def _api_state(self, payload: dict = Body(default={})) -> dict:
        try:
            requested_limit = (payload or {}).get("transfer_limit", 0)
            try:
                transfer_limit = int(requested_limit)
            except (TypeError, ValueError):
                transfer_limit = 0
            if transfer_limit not in (0, 20, 50, 100, 1000):
                transfer_limit = 0
            try:
                container = self._docker("GET", "/containers/rclone-manager/json")
            except DockerError as exc:
                if exc.status != 404:
                    raise
                container = None
            installed = container is not None
            image_available = True
            if not installed:
                try:
                    self._docker("GET", "/images/zzmrclone-manager:local/json")
                except DockerError as exc:
                    if exc.status != 404:
                        raise
                    image_available = False
            running = bool((container or {}).get("State", {}).get("Running"))
            result = {"success": True, "version": self.plugin_version,
                      "url": self._url, "installed": installed, "image_available": image_available,
                      "running": running,
                      "container_status": (container or {}).get("State", {}).get("Status", "not installed"),
                      "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                      "tasks": [], "stats": {}, "transferring": [], "transfer_count": 0}
            if running:
                try:
                    tasks = self._manager("tasks")
                    stats = self._manager("system/rclone-stats")
                    result["tasks"] = [{"id": t.get("id"), "name": t.get("name"),
                                         "display_status": ("stopped" if not t.get("enabled", True)
                                                            else "running" if t.get("status") == "running"
                                                            else "idle"),
                                         "error_hint": self._error_hint(t.get("last_error"))
                                         if t.get("status") == "error" else ""}
                                        for t in tasks if isinstance(t, dict)]
                    result["stats"] = {key: stats.get(key) for key in
                                       ("bytes", "totalBytes", "speed", "eta", "transfers", "totalTransfers", "errors")}
                    transferring = stats.get("transferring") or []
                    result["transfer_count"] = len(transferring)
                    result["transferring"] = [{key: row.get(key) for key in
                                              ("name", "bytes", "size", "speed", "eta", "percentage")}
                                             for row in transferring[:transfer_limit]
                                             if isinstance(row, dict)]
                except Exception as exc:
                    result["warning"] = f"管理器运行中，但读取传输数据失败：{type(exc).__name__}"
            return result
        except Exception as exc:
            return {"success": False, "message": f"无法读取 Rclone Manager 容器：{type(exc).__name__}: {exc}"}

    def _api_control(self, payload: dict = Body(default={})) -> dict:
        action = str((payload or {}).get("action") or "")
        if action not in ("start", "stop", "install", "uninstall"):
            return {"success": False, "message": "不支持此操作"}
        try:
            if action == "install":
                spec = {"Image": "zzmrclone-manager:local",
                        "Env": ["TZ=Asia/Shanghai", "RCLONE_MANAGER_DATA_DIR=/app/data",
                                "RCLONE_MANAGER_LOG_DIR=/app/logs", "RCLONE_MANAGER_PORT=7070",
                                "RCLONE_CONFIG=/root/.config/rclone/rclone.conf"],
                        "ExposedPorts": {"80/tcp": {}},
                        "HostConfig": {
                            "Binds": ["/opt/docker-compose/zzmrclone-manager/data:/app/data",
                                      "/opt/docker-compose/zzmrclone-manager/logs:/app/logs",
                                      "/root/.config/rclone:/root/.config/rclone", "/home:/home"],
                            "PortBindings": {"80/tcp": [{"HostPort": "7071"}]},
                            "Devices": [{"PathOnHost": "/dev/fuse", "PathInContainer": "/dev/fuse", "CgroupPermissions": "rwm"}],
                            "CapAdd": ["SYS_ADMIN"], "SecurityOpt": ["apparmor:unconfined"],
                            "ExtraHosts": ["host.docker.internal:host-gateway"],
                            "RestartPolicy": {"Name": "unless-stopped"}}}
                self._docker("POST", "/containers/create?name=rclone-manager", spec)
                self._docker("POST", "/containers/rclone-manager/start")
                return {"success": True, "message": "已从本机现有镜像安装并启动；原任务数据保留"}
            if action == "uninstall":
                try:
                    tasks = self._manager("tasks")
                    if any(t.get("status") == "running" for t in tasks if isinstance(t, dict)):
                        return {"success": False, "message": "有任务正在传输，请先等待完成或停止服务"}
                except Exception:
                    pass
                try:
                    self._docker("POST", "/containers/rclone-manager/stop?t=10")
                except DockerError as exc:
                    if exc.status not in (304,):
                        raise
                self._docker("DELETE", "/containers/rclone-manager")
                return {"success": True, "message": "已卸载服务容器；镜像和任务数据保留，可重新安装"}
            self._docker("POST", f"/containers/rclone-manager/{action}?t=10")
            return {"success": True, "message": "Rclone Manager 已启动" if action == "start" else "Rclone Manager 已停止"}
        except Exception as exc:
            return {"success": False, "message": f"操作失败：{type(exc).__name__}: {exc}"}
