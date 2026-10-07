import hashlib
import html
import math
import random
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.chain.download import DownloadChain
from app.chain.search import SearchChain
from app.chain.tmdb import TmdbChain
from app.core.config import settings
from app.core.context import Context, MediaInfo
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfo
from app.core.module import ModuleManager
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType, MessageChannel, NotificationType, SystemConfigKey
from app.utils.string import StringUtils


class SmartMoviePush(_PluginBase):
    plugin_name = "60分钟推送电影_自用"
    plugin_desc = "每小时从新片、近期口碑、经典热门和随机发现中筛选 20 部电影推送到 Telegram。"
    plugin_icon = "Telegram_A.png"
    plugin_version = "0.5.2"
    plugin_author = "kingsnakerrr"
    author_url = "https://github.com/kingsnakerrr"
    plugin_config_prefix = "smartmoviepush_"
    plugin_order = 60
    auth_level = 1

    _enabled = True
    _auto_push = False
    _auto_download = False
    _onlyonce = False
    _cron = "0 * * * *"
    _limit = 20
    _test_limit = 2
    _site_id = 1
    _new_count = 8
    _recent_count = 4
    _classic_count = 4
    _random_count = 4
    _dedupe_days = 30
    _min_score = 6.0
    _min_votes = 100
    _max_active_downloads = 20
    _max_searches = 80
    _scheduler = None
    _running_lock = threading.Lock()
    _queue_lock = threading.Lock()
    _allowed_languages = {
        "zh", "en", "ja", "ko", "fr", "de", "es", "it", "pt",
        "nl", "sv", "no", "da", "fi", "pl", "cs", "hu", "tr",
    }
    _pending_key = "pending_downloads"
    _pushed_key = "pushed_tmdb_ids"
    _scan_cache_key = "scan_cache"
    _suppressed_key = "suppressed_movies"
    _daily_messages_key = "daily_messages"
    _download_queue_key = "download_queue"
    _download_history_key = "download_history"
    _history_backfill_key = "download_history_backfilled_v2"
    _candidate_cursor_key = "candidate_cursor"

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled", True))
        self._auto_push = bool(config.get("auto_push", False))
        self._auto_download = bool(config.get("auto_download", False))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._cron = str(config.get("cron") or "0 * * * *")
        self._limit = max(1, min(int(config.get("limit") or 20), 50))
        self._test_limit = max(1, min(int(config.get("test_limit") or 2), 5))
        self._site_id = int(config.get("site_id") or 1)
        self._new_count = max(0, int(config.get("new_count", 8)))
        self._recent_count = max(0, int(config.get("recent_count", 4)))
        self._classic_count = max(0, int(config.get("classic_count", 4)))
        self._random_count = max(0, int(config.get("random_count", 4)))
        self._dedupe_days = max(1, int(config.get("dedupe_days", 30)))
        self._min_score = max(0.0, float(config.get("min_score", 6.0)))
        self._min_votes = max(0, int(config.get("min_votes", 100)))
        self._max_active_downloads = max(1, min(int(config.get("max_active_downloads") or 20), 100))
        self._max_searches = max(20, min(int(config.get("max_searches") or 80), 200))

        # 旧版本只把下载写进 MoviePilot 下载历史，没有保存到插件页面。
        # 升级时自动补录一次；失败不会写完成标记，下次加载会继续尝试。
        self._backfill_download_history()

        if self._onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                self.run_once,
                "date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=8),
                kwargs={"limit": self._test_limit, "test_mode": True},
                id="SmartMoviePushTest",
                replace_existing=True,
            )
            self._onlyonce = False
            self.update_config(self._current_config())
            self._scheduler.start()

    def _current_config(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "auto_push": self._auto_push,
            "auto_download": self._auto_download,
            "onlyonce": False,
            "cron": self._cron,
            "limit": self._limit,
            "test_limit": self._test_limit,
            "site_id": self._site_id,
            "new_count": self._new_count,
            "recent_count": self._recent_count,
            "classic_count": self._classic_count,
            "random_count": self._random_count,
            "dedupe_days": self._dedupe_days,
            "min_score": self._min_score,
            "min_votes": self._min_votes,
            "max_active_downloads": self._max_active_downloads,
            "max_searches": self._max_searches,
        }

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/toggle_auto_push", "endpoint": self._api_toggle_auto_push,
             "methods": ["GET"], "summary": "切换定时推送"},
            {"path": "/toggle_download_mode", "endpoint": self._api_toggle_download_mode,
             "methods": ["GET"], "summary": "切换自动/手动下载"},
            {"path": "/run_once", "endpoint": self._api_run_once,
             "methods": ["GET"], "summary": "立即试运行"},
            {"path": "/clear_cache", "endpoint": self._api_clear_cache,
             "methods": ["GET"], "summary": "清空扫描缓存"},
            {"path": "/remove_suppressed", "endpoint": self._api_remove_suppressed,
             "methods": ["GET"], "summary": "恢复单部电影推送"},
            {"path": "/clear_suppressed", "endpoint": self._api_clear_suppressed,
             "methods": ["GET"], "summary": "清空不再推送列表"},
            {"path": "/remove_queue", "endpoint": self._api_remove_queue,
             "methods": ["GET"], "summary": "删除单个等候下载"},
            {"path": "/clear_queue", "endpoint": self._api_clear_queue,
             "methods": ["GET"], "summary": "清空等候下载"},
            {"path": "/clear_download_history", "endpoint": self._api_clear_download_history,
             "methods": ["GET"], "summary": "清空下载记录"},
            {"path": "/backfill_download_history", "endpoint": self._api_backfill_download_history,
             "methods": ["GET"], "summary": "重新补录插件旧下载记录"},
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron, timezone=settings.TZ)
        except Exception as err:
            logger.error(f"智能电影推送 cron 配置错误：{err}")
            return []
        return [
            {
                "id": "SmartMoviePushService",
                "name": "60分钟推送电影_自用",
                "trigger": trigger,
                "func": self.scheduled_run,
                "kwargs": {"limit": self._limit, "test_mode": False},
            },
            {
                "id": "SmartMoviePushMidnightCleanup",
                "name": "清理当天电影推荐消息",
                "trigger": CronTrigger.from_crontab("0 0 * * *", timezone=settings.TZ),
                "func": self.cleanup_daily_messages,
            },
            {
                "id": "SmartMoviePushDownloadQueue",
                "name": "智能电影推荐顺序下载队列",
                "trigger": CronTrigger.from_crontab("* * * * *", timezone=settings.TZ),
                "func": self.process_download_queue,
            },
        ]

    def scheduled_run(self):
        if not self._auto_push:
            logger.info("60分钟推送电影已切换为暂停，本轮跳过")
            return
        self.run_once(limit=self._limit, test_mode=False)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件（接收下载按钮）"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "auto_push", "label": "启用定时自动推送"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "auto_download", "label": "自动下载（关闭=手动按钮）"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "onlyonce", "label": "立即试推送"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{
                                "component": "VTextField", "props": {"model": "new_count", "label": "新片热门数量", "type": "number"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{
                                "component": "VTextField", "props": {"model": "recent_count", "label": "近期口碑数量", "type": "number"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{
                                "component": "VTextField", "props": {"model": "classic_count", "label": "经典热门数量", "type": "number"}}]},
                            {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{
                                "component": "VTextField", "props": {"model": "random_count", "label": "随机发现数量", "type": "number"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{
                                "component": "VTextField", "props": {"model": "dedupe_days", "label": "推送去重天数", "type": "number"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{
                                "component": "VTextField", "props": {"model": "min_score", "label": "随机最低评分", "type": "number", "step": "0.1"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{
                                "component": "VTextField", "props": {"model": "min_votes", "label": "随机最低投票数", "type": "number"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{
                                "component": "VTextField", "props": {"model": "max_active_downloads", "label": "最多同时下载", "type": "number"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{
                                "component": "VTextField", "props": {"model": "max_searches", "label": "每轮最多查询 M-Team", "type": "number"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "cron", "label": "推送周期", "placeholder": "0 * * * *"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "limit", "label": "每轮数量", "type": "number"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "test_limit", "label": "试推送数量", "type": "number"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "site_id", "label": "M-Team 站点 ID", "type": "number"},
                                }],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": True,
            "auto_push": False,
            "auto_download": False,
            "onlyonce": False,
            "cron": "0 * * * *",
            "limit": 20,
            "test_limit": 2,
            "site_id": 1,
            "new_count": 8,
            "recent_count": 4,
            "classic_count": 4,
            "random_count": 4,
            "dedupe_days": 30,
            "min_score": 6.0,
            "min_votes": 100,
            "max_active_downloads": 20,
            "max_searches": 80,
        }

    def get_page(self) -> Optional[List[dict]]:
        pushed = self._load_recent_pushes()
        cache = self.get_data(self._scan_cache_key)
        cache_count = len(cache) if isinstance(cache, dict) else 0
        suppressed = self._load_suppressed()
        download_queue = self._load_download_queue()
        download_history = self._load_download_history()
        active_downloads = self._active_download_count()

        def stat_card(title: str, value: str, subtitle: str, color: str = "primary") -> dict:
            return {
                "component": "VCard",
                "props": {"variant": "tonal", "color": color, "class": "pa-4 h-100"},
                "content": [
                    {"component": "div", "props": {"class": "text-caption mb-1"}, "text": title},
                    {"component": "div", "props": {"class": "text-h6 font-weight-bold"}, "text": value},
                    {"component": "div", "props": {"class": "text-caption mt-1"}, "text": subtitle},
                ],
            }

        def action_button(text: str, path: str, color: str = "primary") -> dict:
            separator = "&" if "?" in path else "?"
            return {
                "component": "VBtn",
                "props": {"color": color, "variant": "tonal", "class": "mr-2 mb-2"},
                "text": text,
                "events": {"click": {
                    "api": f"plugin/{self.__class__.__name__}/{path}{separator}apikey={settings.API_TOKEN}",
                    "method": "get",
                }},
            }

        return [{
            "component": "VContainer",
            "props": {"fluid": True, "class": "pa-2"},
            "content": [
                {"component": "VAlert", "props": {
                    "type": "info", "variant": "tonal", "class": "mb-4",
                    "title": "60分钟推送电影_自用",
                    "text": "先完成整轮 TMDB、媒体库和 M-Team 筛选，再一次性集中推送；扫描结果保存在 MoviePilot 自带 SQLite 中。",
                }},
                {"component": "VRow", "props": {"dense": True, "class": "mb-4"}, "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        stat_card("插件状态", "已启用" if self._enabled else "已关闭",
                                  "按钮回调与定时服务", "success" if self._enabled else "error")]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        stat_card("定时推送", "每小时" if self._auto_push else "已暂停",
                                  self._cron, "success" if self._auto_push else "warning")]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        stat_card("下载模式", "自动下载" if self._auto_download else "手动确认",
                                  "自动提交 qB" if self._auto_download else "Telegram 按钮确认",
                                  "warning" if self._auto_download else "primary")]},
                    {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                        stat_card("缓存/不再推送", f"{cache_count} / {len(suppressed)}",
                                  "扫描缓存 / 永久排除") ]},
                ]},
                {"component": "VCard", "props": {"variant": "outlined", "class": "pa-4 mb-4"}, "content": [
                    {"component": "div", "props": {"class": "text-h6 mb-3"}, "text": "当前推送设置"},
                    {"component": "VRow", "props": {"dense": True}, "content": [
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "div", "text": f"新片热门：{self._new_count} 部"}]},
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "div", "text": f"近期口碑：{self._recent_count} 部"}]},
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "div", "text": f"经典热门：{self._classic_count} 部"}]},
                        {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [{"component": "div", "text": f"随机发现：{self._random_count} 部"}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "div", "text": f"每轮上限：{self._limit} 部"}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "div", "text": f"最低评分/投票：{self._min_score} / {self._min_votes}"}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "div", "text": f"M-Team 站点 ID：{self._site_id}"}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "div", "text": f"同时下载上限：{self._max_active_downloads} 部"}]},
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "div", "text": f"M-Team 查询上限：{self._max_searches} 次/轮"}]},
                    ]},
                ]},
                {"component": "VCard", "props": {"variant": "outlined", "class": "pa-4 mb-4"}, "content": [
                    {"component": "div", "props": {"class": "text-h6 mb-3"}, "text": "快捷控制"},
                    {"component": "div", "content": [
                        action_button("暂停定时推送" if self._auto_push else "开启定时推送", "toggle_auto_push",
                                      "warning" if self._auto_push else "success"),
                        action_button("改为手动下载" if self._auto_download else "改为自动下载", "toggle_download_mode",
                                      "warning" if not self._auto_download else "primary"),
                        action_button("立即试推送", "run_once", "success"),
                        action_button("清空扫描缓存", "clear_cache", "error"),
                    ]},
                    {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-2"},
                     "text": "点击操作后重新打开本页即可看到最新状态；详细数字仍可通过齿轮设置修改。"},
                ]},
                {"component": "VCard", "props": {"variant": "outlined", "class": "pa-4 mb-4"}, "content": [
                    {"component": "div", "props": {"class": "d-flex align-center justify-space-between mb-3"}, "content": [
                        {"component": "div", "props": {"class": "text-h6"},
                         "text": f"等候下载（{len(download_queue)}） · 正在下载 {active_downloads}/{self._max_active_downloads}"},
                        action_button("批量清空", "clear_queue", "error"),
                    ]},
                    *([{"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                        "text": "当前没有等候下载的电影；有空位后队列会按顺序自动提交。"}]
                      if not download_queue else [
                        {"component": "VCard", "props": {"variant": "tonal", "class": "pa-3 mb-2"}, "content": [
                            {"component": "div", "props": {"class": "d-flex align-center justify-space-between"}, "content": [
                                {"component": "div", "props": {"class": "font-weight-medium"},
                                 "text": f"{index}. {item.get('title') or ('TMDB ' + str(item.get('tmdb_id')))}"},
                                action_button("删除", f"remove_queue?key={item.get('key', '')}", "error"),
                            ]},
                        ]}
                        for index, item in enumerate(download_queue, 1)
                    ]),
                ]},
                {"component": "VCard", "props": {"variant": "outlined", "class": "pa-4 mb-4"}, "content": [
                    {"component": "div", "props": {"class": "d-flex align-center justify-space-between mb-3"}, "content": [
                        {"component": "div", "props": {"class": "text-h6"},
                         "text": f"插件下载记录（{len(download_history)}）"},
                        {"component": "div", "content": [
                            action_button("补录旧记录", "backfill_download_history", "primary"),
                            action_button("清空记录", "clear_download_history", "warning"),
                        ]},
                    ]},
                    *([{"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                        "text": "目前还没有下载记录。"}]
                      if not download_history else [
                        {"component": "div", "props": {"class": "py-1"},
                         "text": str(item.get("title") or f"TMDB {item.get('tmdb_id')}")}
                        for item in reversed(download_history[-100:])
                    ]),
                ]},
                {"component": "VCard", "props": {"variant": "outlined", "class": "pa-4"}, "content": [
                    {"component": "div", "props": {"class": "d-flex align-center justify-space-between mb-3"}, "content": [
                        {"component": "div", "props": {"class": "text-h6"},
                         "text": f"不再推送列表（{len(suppressed)}）"},
                        action_button("批量清空", "clear_suppressed", "error"),
                    ]},
                    *([
                        {"component": "VAlert", "props": {"type": "info", "variant": "tonal"},
                         "text": "列表为空。Telegram 中点击“不再推送”后，电影会出现在这里。"}
                    ] if not suppressed else [
                        {"component": "VRow", "props": {"dense": True}, "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VCard", "props": {"variant": "tonal", "class": "pa-3"}, "content": [
                                    {"component": "div", "props": {"class": "d-flex align-center justify-space-between"}, "content": [
                                        {"component": "div", "content": [
                                            {"component": "div", "props": {"class": "font-weight-medium"},
                                             "text": str(item.get("title") or f"TMDB {tmdb_id}")},
                                            {"component": "div", "props": {"class": "text-caption text-medium-emphasis"},
                                             "text": f"TMDB {tmdb_id} · {item.get('added_at', '')}"},
                                        ]},
                                        action_button("恢复推送", f"remove_suppressed?tmdb_id={tmdb_id}", "success"),
                                    ]},
                                ]},
                            ]},
                        ]}
                        for tmdb_id, item in sorted(
                            suppressed.items(), key=lambda row: str(row[1].get("added_at", "")), reverse=True
                        )
                    ]),
                ]},
            ],
        }]

    def _api_toggle_auto_push(self) -> dict:
        self._auto_push = not self._auto_push
        self.update_config(self._current_config())
        return {"success": True, "message": f"定时推送已{'开启' if self._auto_push else '暂停'}"}

    def _api_toggle_download_mode(self) -> dict:
        self._auto_download = not self._auto_download
        self.update_config(self._current_config())
        return {"success": True, "message": f"已切换为{'自动' if self._auto_download else '手动'}下载"}

    def _api_run_once(self) -> dict:
        if self._running_lock.locked():
            return {"success": False, "message": "任务正在运行中"}
        threading.Thread(target=self.run_once,
                         kwargs={"limit": self._test_limit, "test_mode": True},
                         daemon=True).start()
        return {"success": True, "message": f"已开始试推送 {self._test_limit} 部"}

    def _api_clear_cache(self) -> dict:
        self.save_data(self._scan_cache_key, {})
        return {"success": True, "message": "扫描缓存已清空"}

    def _api_remove_suppressed(self, tmdb_id: str = "") -> dict:
        suppressed = self._load_suppressed()
        item = suppressed.pop(str(tmdb_id), None)
        self.save_data(self._suppressed_key, suppressed)
        return {"success": bool(item), "message": "已恢复推送" if item else "电影不在排除列表中"}

    def _api_clear_suppressed(self) -> dict:
        count = len(self._load_suppressed())
        self.save_data(self._suppressed_key, {})
        return {"success": True, "message": f"已清空 {count} 部不再推送电影"}

    def _api_remove_queue(self, key: str = "") -> dict:
        queue = self._load_download_queue()
        retained = [item for item in queue if str(item.get("key")) != str(key)]
        removed = len(queue) - len(retained)
        self.save_data(self._download_queue_key, retained)
        return {"success": bool(removed), "message": "已删除等候任务" if removed else "任务已不存在"}

    def _api_clear_queue(self) -> dict:
        count = len(self._load_download_queue())
        self.save_data(self._download_queue_key, [])
        return {"success": True, "message": f"已清空 {count} 部等候下载电影"}

    def _api_clear_download_history(self) -> dict:
        count = len(self._load_download_history())
        self.save_data(self._download_history_key, [])
        return {"success": True, "message": f"已清空 {count} 条下载记录"}

    def _api_backfill_download_history(self) -> dict:
        result = self._backfill_download_history(force=True)
        return {
            "success": bool(result.get("success")),
            "message": (
                f"历史补录完成：新增 {result.get('added', 0)} 条，当前共 {result.get('total', 0)} 条"
                if result.get("success") else f"历史补录失败：{result.get('error', '未知错误')}"
            ),
        }

    def get_dashboard(self, key: str, **kwargs):
        return None

    def stop_service(self):
        if self._scheduler:
            try:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown(wait=False)
            except Exception as err:
                logger.warning(f"停止智能电影推送临时调度器失败：{err}")
            finally:
                self._scheduler = None

    @staticmethod
    def _media_from_dict(data: dict) -> MediaInfo:
        media = MediaInfo()
        media.from_dict(data)
        return media

    @staticmethod
    def _release_date(media: MediaInfo):
        value = getattr(media, "release_date", None)
        if value:
            try:
                return datetime.fromisoformat(str(value)[:10]).date()
            except (TypeError, ValueError):
                pass
        year = getattr(media, "year", None)
        try:
            return datetime(int(year), 1, 1).date()
        except (TypeError, ValueError):
            return None

    def _valid_region(self, media: MediaInfo) -> bool:
        return not media.original_language or media.original_language in self._allowed_languages

    @staticmethod
    def _vote_count(media: MediaInfo) -> int:
        """MediaInfo 不暴露 vote_count 字段，从保留的 TMDB 原始数据中读取。"""
        info = getattr(media, "tmdb_info", None) or {}
        try:
            return int(info.get("vote_count") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _popularity(media: MediaInfo) -> float:
        info = getattr(media, "tmdb_info", None) or {}
        try:
            return max(0.0, float(info.get("popularity") or 0))
        except (TypeError, ValueError):
            return 0.0

    def _rank_candidates(self, items: List[MediaInfo], recency_weight: float = 0.15) -> List[MediaInfo]:
        """综合 TMDB 评分可信度、热度、上映时间和少量随机性排序。"""
        if not items:
            return []
        max_popularity = max((self._popularity(item) for item in items), default=1.0) or 1.0
        today = datetime.now().date()

        def score(media: MediaInfo) -> float:
            votes = self._vote_count(media)
            rating = float(getattr(media, "vote_average", 0) or 0)
            # 贝叶斯修正，避免极少投票的虚高评分霸榜。
            bayesian = (votes / (votes + 250.0)) * rating + (250.0 / (votes + 250.0)) * 6.5
            popularity = math.log1p(self._popularity(media)) / math.log1p(max_popularity)
            released = self._release_date(media)
            if released:
                age_days = max(0, (today - released).days)
                recency = max(0.0, 1.0 - age_days / 3650.0)
            else:
                recency = 0.0
            return (bayesian / 10.0) * 0.55 + popularity * 0.25 + recency * recency_weight + random.random() * 0.05

        return sorted(items, key=score, reverse=True)

    def _candidate_buckets(self) -> Dict[str, List[MediaInfo]]:
        chain = TmdbChain()
        today = datetime.now().date()
        new_floor = today - timedelta(days=365)
        recent_floor = today - timedelta(days=365 * 5)
        cursor_value = self.get_data(self._candidate_cursor_key)
        try:
            cursor = int(cursor_value or 0)
        except (TypeError, ValueError):
            cursor = 0

        def discover(sort_by: str, score: float, votes: int, release: str, pages):
            result = []
            for page in pages:
                try:
                    result.extend(chain.tmdb_discover(
                        mtype=MediaType.MOVIE, sort_by=sort_by, with_genres="",
                        with_original_language="", with_keywords="", with_watch_providers="",
                        vote_average=score, vote_count=votes, release_date=release, page=page,
                    ) or [])
                except Exception as err:
                    logger.warning(f"TMDB 发现页读取失败：sort={sort_by}, page={page}, error={err}")
            return result

        # 每轮向后滚动热门页，同时为其他分组随机抽页；不再反复扫描固定前几页。
        rolling_pages = [((cursor + offset) % 20) + 1 for offset in range(5)]
        trending = []
        for page in rolling_pages:
            try:
                trending.extend(chain.tmdb_trending(page=page) or [])
            except Exception as err:
                logger.warning(f"TMDB 趋势页读取失败：page={page}, error={err}")
        new_source = trending + discover(
            "popularity.desc", 5.5, 30, new_floor.isoformat(), rolling_pages
        )
        recent_source = discover(
            "popularity.desc", 6.5, 200, recent_floor.isoformat(), random.sample(range(1, 41), 5)
        )
        classic_source = discover(
            "vote_count.desc", 7.0, 800, "", random.sample(range(1, 101), 6)
        )
        random_source = []
        for _ in range(5):
            floor_year = random.randint(1970, max(1970, today.year - 1))
            random_source.extend(discover(
                random.choice(["popularity.desc", "vote_count.desc", "vote_average.desc"]),
                self._min_score, self._min_votes, f"{floor_year}-01-01", [random.randint(1, 50)]
            ))
        self.save_data(self._candidate_cursor_key, (cursor + 5) % 20)

        def unique(items, predicate):
            output, seen = [], set()
            for media in items:
                if media.type != MediaType.MOVIE or not media.tmdb_id or not self._valid_region(media):
                    continue
                if media.tmdb_id in seen or not predicate(media):
                    continue
                seen.add(media.tmdb_id)
                output.append(media)
            return output

        new_movies = unique(new_source, lambda m: bool(
            self._release_date(m) and new_floor <= self._release_date(m) <= today))
        recent_movies = unique(recent_source, lambda m: bool(
            self._release_date(m) and recent_floor <= self._release_date(m) < new_floor
            and float(getattr(m, "vote_average", 0) or 0) >= 6.5
            and self._vote_count(m) >= 100))
        classic_movies = unique(classic_source, lambda m: bool(
            self._release_date(m) and self._release_date(m) < recent_floor
            and float(getattr(m, "vote_average", 0) or 0) >= 7.0
            and self._vote_count(m) >= 500))
        random_movies = unique(random_source, lambda m: bool(
            self._release_date(m) and self._release_date(m) <= today
            and float(getattr(m, "vote_average", 0) or 0) >= self._min_score
            and self._vote_count(m) >= self._min_votes))
        return {
            "new": self._rank_candidates(new_movies, recency_weight=0.20),
            "recent": self._rank_candidates(recent_movies, recency_weight=0.15),
            "classic": self._rank_candidates(classic_movies, recency_weight=0.02),
            "random": self._rank_candidates(random_movies, recency_weight=0.08),
        }

    def _load_recent_pushes(self) -> Dict[str, str]:
        value = self.get_data(self._pushed_key)
        now = datetime.now()
        cutoff = now - timedelta(days=self._dedupe_days)
        if isinstance(value, list):
            return {str(item): now.isoformat(timespec="seconds") for item in value}
        if not isinstance(value, dict):
            return {}
        result = {}
        for tmdb_id, pushed_at in value.items():
            try:
                if datetime.fromisoformat(str(pushed_at)) >= cutoff:
                    result[str(tmdb_id)] = str(pushed_at)
            except (TypeError, ValueError):
                continue
        return result

    def _load_scan_cache(self) -> Dict[str, dict]:
        value = self.get_data(self._scan_cache_key)
        if not isinstance(value, dict):
            return {}
        now = datetime.now()
        result = {}
        ttl_hours = {"library": 168, "no_resource": 4, "error": 0.5}
        for tmdb_id, item in value.items():
            if not isinstance(item, dict):
                continue
            try:
                checked_at = datetime.fromisoformat(str(item.get("checked_at")))
            except (TypeError, ValueError):
                continue
            ttl = ttl_hours.get(str(item.get("status")), 0)
            if ttl and now - checked_at < timedelta(hours=ttl):
                result[str(tmdb_id)] = item
        return result

    @staticmethod
    def _torrent_identity(context: Context) -> str:
        torrent = context.torrent_info
        raw = f"{torrent.site}|{torrent.enclosure}|{torrent.page_url}|{torrent.title}"
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def _already_in_library(self, media: MediaInfo) -> bool:
        meta = MetaInfo(title=media.title_year)
        exists, _ = DownloadChain().get_no_exists_info(meta=meta, mediainfo=media)
        return bool(exists)

    def _search_best(self, media: MediaInfo) -> Optional[Context]:
        results = SearchChain().search_by_id(
            tmdbid=media.tmdb_id,
            mtype=MediaType.MOVIE,
            sites=[self._site_id],
            cache_local=False,
        ) or []
        return results[0] if results else None

    def _load_pending(self) -> dict:
        value = self.get_data(self._pending_key)
        return value if isinstance(value, dict) else {}

    def _load_download_queue(self) -> List[dict]:
        value = self.get_data(self._download_queue_key)
        return value if isinstance(value, list) else []

    def _load_download_history(self) -> List[dict]:
        value = self.get_data(self._download_history_key)
        return value if isinstance(value, list) else []

    @staticmethod
    def _download_history_identity(item: dict) -> str:
        tmdb_id = item.get("tmdb_id")
        if tmdb_id not in (None, ""):
            return f"tmdb:{tmdb_id}"
        title = " ".join(str(item.get("title") or "").lower().split())
        return f"title:{title}"

    def _backfill_download_history(self, force: bool = False) -> dict:
        """从 MoviePilot 下载历史补回本插件旧版本提交的电影。"""
        if not force and self.get_data(self._history_backfill_key):
            return {"success": True, "added": 0, "total": len(self._load_download_history())}

        try:
            records = []
            oper = DownloadHistoryOper()
            # 下载历史按新到旧分页；设置安全上限，避免异常数据库无限扫描。
            for page in range(1, 101):
                batch = oper.list_by_page(page=page, count=200) or []
                if not batch:
                    break
                for item in batch:
                    note = getattr(item, "note", None)
                    # 只认 download_single() 写入数据库的插件专属来源；
                    # username 可能由界面或调用方传入，不能用于判断归属。
                    if isinstance(note, dict) and note.get("source") == self.__class__.__name__:
                        records.append(item)
                if len(batch) < 200:
                    break

            # 丢弃上一版按 username 补录的项目，再按专属 source 重新构建。
            # 插件运行期间直接记录的项目没有 backfilled 标记，会被保留。
            history = [item for item in self._load_download_history() if not item.get("backfilled")]
            identities = {self._download_history_identity(item) for item in history}
            added = 0
            # 数据库返回新到旧，倒序写入可保持页面上的时间顺序。
            for record in reversed(records):
                title = str(getattr(record, "title", "") or "").strip()
                year = str(getattr(record, "year", "") or "").strip()
                display_title = title
                if year and year not in title:
                    display_title = f"{title} ({year})"
                item = {
                    "tmdb_id": getattr(record, "tmdbid", None),
                    "title": display_title or f"TMDB {getattr(record, 'tmdbid', '')}",
                    "download_id": str(getattr(record, "download_hash", "") or ""),
                    "submitted_at": str(getattr(record, "date", "") or ""),
                    "backfilled": True,
                }
                identity = self._download_history_identity(item)
                if identity in identities:
                    continue
                identities.add(identity)
                history.append(item)
                added += 1

            history.sort(key=lambda item: str(item.get("submitted_at") or ""))
            self.save_data(self._download_history_key, history[-1000:])
            self.save_data(self._history_backfill_key, {
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "matched": len(records),
            })
            logger.info(f"智能电影推荐历史补录完成：匹配 {len(records)} 条，新增 {added} 条")
            return {"success": True, "added": added, "total": len(history[-1000:])}
        except Exception as err:
            logger.error(f"智能电影推荐历史补录失败：{err}")
            return {"success": False, "added": 0, "total": len(self._load_download_history()), "error": str(err)}

    def _active_download_count(self) -> int:
        """MoviePilot 仅返回带其内置标签且处于下载中的任务。"""
        try:
            return len(DownloadChain().downloading() or [])
        except Exception as err:
            # 读取失败时按已满处理，避免失联期间无限向下载器提交。
            logger.error(f"读取 MoviePilot 正在下载任务失败：{err}")
            return self._max_active_downloads

    def _enqueue_download(self, media: MediaInfo, context: Context,
                          channel: Any = None, userid: Any = None) -> bool:
        queue = self._load_download_queue()
        tmdb_id = str(media.tmdb_id)
        if any(str(item.get("tmdb_id")) == tmdb_id for item in queue):
            return False
        queue.append({
            "key": hashlib.sha1(f"{tmdb_id}|{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            "tmdb_id": media.tmdb_id,
            "title": media.title_year,
            "torrent_identity": self._torrent_identity(context),
            "channel": channel.value if hasattr(channel, "value") else channel,
            "userid": userid,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "attempts": 0,
        })
        self.save_data(self._download_queue_key, queue[-500:])
        logger.info(f"已加入顺序下载队列：{media.title_year}，当前等候 {len(queue)} 部")
        return True

    def _record_download(self, media: MediaInfo, download_id: Any) -> None:
        history = self._load_download_history()
        history.append({
            "tmdb_id": media.tmdb_id,
            "title": media.title_year,
            "download_id": str(download_id or ""),
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        })
        self.save_data(self._download_history_key, history[-1000:])

    def _submit_download(self, media: MediaInfo, context: Context,
                         channel: Any = None, userid: Any = None,
                         username: str = "60分钟推送电影_自用") -> Tuple[bool, Optional[str]]:
        download_id, error = DownloadChain().download_single(
            context=context,
            channel=channel,
            source=self.__class__.__name__,
            userid=userid,
            username=username,
            label="MOVIEPILOT",
            return_detail=True,
        )
        if not download_id:
            return False, error or "未知错误"
        self._record_download(media, download_id)
        return True, None

    def process_download_queue(self) -> None:
        """每分钟检查空位，严格按入队顺序提交，活动下载永不超过设置值。"""
        if not self._queue_lock.acquire(blocking=False):
            return
        try:
            queue = self._load_download_queue()
            if not queue:
                return
            active = self._active_download_count()
            slots = max(0, self._max_active_downloads - active)
            if slots <= 0:
                logger.info(f"下载队列等待中：正在下载 {active}/{self._max_active_downloads}，等候 {len(queue)}")
                return

            remaining = list(queue)
            submitted = 0
            # 只处理本次进入函数时已有的项目，失败项留到下一分钟，防止同轮反复重试。
            for item in queue[:]:
                if submitted >= slots:
                    break
                try:
                    results = SearchChain().search_by_id(
                        tmdbid=int(item["tmdb_id"]), mtype=MediaType.MOVIE,
                        sites=[self._site_id], cache_local=False,
                    ) or []
                    context = next(
                        (ctx for ctx in results if self._torrent_identity(ctx) == item.get("torrent_identity")),
                        results[0] if results else None,
                    )
                    if not context:
                        raise RuntimeError("M-Team 中已找不到可下载资源")
                    media = context.media_info
                    ok, error = self._submit_download(
                        media, context, channel=None, userid=item.get("userid"),
                        username="智能电影推荐队列",
                    )
                    if not ok:
                        raise RuntimeError(error or "提交失败")
                    remaining = [row for row in remaining if row.get("key") != item.get("key")]
                    submitted += 1
                    logger.info(f"顺序下载队列已提交：{item.get('title')}")
                except Exception as err:
                    for row in remaining:
                        if row.get("key") == item.get("key"):
                            row["attempts"] = int(row.get("attempts") or 0) + 1
                            row["last_error"] = str(err)[:300]
                            row["last_attempt"] = datetime.now().isoformat(timespec="seconds")
                            break
                    logger.error(f"顺序下载队列提交失败：{item.get('title')}：{err}")
                    # FIFO：队首失败时不越过它，避免后加入的电影抢先。
                    break
            self.save_data(self._download_queue_key, remaining)
            if submitted:
                logger.info(f"下载队列本轮提交 {submitted} 部，剩余 {len(remaining)} 部")
        finally:
            self._queue_lock.release()

    def _load_suppressed(self) -> Dict[str, dict]:
        value = self.get_data(self._suppressed_key)
        return value if isinstance(value, dict) else {}

    def _load_daily_messages(self) -> List[dict]:
        value = self.get_data(self._daily_messages_key)
        return value if isinstance(value, list) else []

    @staticmethod
    def _normalize_admin(value: Any) -> str:
        return str(value or "").strip().lstrip("@").lower()

    def _telegram_admins(self) -> set:
        admins = set()
        notifications = self.systemconfig.get(SystemConfigKey.Notifications) or []
        for notification in notifications:
            if not isinstance(notification, dict) or notification.get("type") != "telegram":
                continue
            config = notification.get("config") or {}
            raw = str(config.get("TELEGRAM_ADMINS") or "").replace(";", ",")
            admins.update(self._normalize_admin(item) for item in raw.split(",") if item.strip())
        return admins

    def _is_telegram_admin(self, userid: Any, username: Any = None) -> bool:
        admins = self._telegram_admins()
        candidates = {self._normalize_admin(userid), self._normalize_admin(username)} - {""}
        return bool(admins and candidates.intersection(admins))

    @staticmethod
    def _telegram_module():
        return ModuleManager().get_running_module("TelegramModule")

    def _send_telegram_direct(self, **kwargs) -> Tuple[Optional[str], Optional[dict]]:
        """直接调用现有 Telegram 实例，以便保存消息 ID 供午夜精确撤回。"""
        module = self._telegram_module()
        if not module:
            return None, None
        for source, conf in module.get_configs().items():
            client = module.get_instance(conf.name)
            if not client:
                continue
            result = client.send_msg(**kwargs)
            if result and result.get("success"):
                return source, result
        return None, None

    def _delete_telegram_message(self, source: Optional[str], message_id: Any, chat_id: Any) -> bool:
        module = self._telegram_module()
        if not module or not message_id:
            return False
        conf = module.get_config(source) if source else None
        client = module.get_instance(conf.name) if conf else None
        return bool(client and client.delete_msg(message_id=int(message_id), chat_id=chat_id))

    def _record_daily_message(self, key: Optional[str], media: MediaInfo,
                              source: Optional[str], result: Optional[dict], auto_downloaded: bool) -> None:
        if not result or not result.get("message_id"):
            return
        records = self._load_daily_messages()
        records.append({
            "key": key,
            "tmdb_id": str(media.tmdb_id),
            "title": media.title_year,
            "source": source,
            "message_id": result.get("message_id"),
            "chat_id": result.get("chat_id"),
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "auto_downloaded": bool(auto_downloaded),
        })
        self.save_data(self._daily_messages_key, records[-1000:])

    def _remove_daily_record(self, key: str) -> None:
        records = [item for item in self._load_daily_messages() if str(item.get("key")) != str(key)]
        self.save_data(self._daily_messages_key, records)

    def cleanup_daily_messages(self) -> None:
        """午夜撤回以前的推荐；未点击的电影同时解除推送去重，可在以后随机再次出现。"""
        today = datetime.now().date()
        records = self._load_daily_messages()
        pending = self._load_pending()
        pushed = self._load_recent_pushes()
        retained = []
        cleaned = 0
        returned = 0
        for item in records:
            try:
                sent_date = datetime.fromisoformat(str(item.get("sent_at"))).date()
            except (TypeError, ValueError):
                sent_date = today - timedelta(days=1)
            if sent_date >= today:
                retained.append(item)
                continue
            self._delete_telegram_message(
                source=item.get("source"), message_id=item.get("message_id"), chat_id=item.get("chat_id")
            )
            key = item.get("key")
            if key and key in pending:
                pending.pop(key, None)
                pushed.pop(str(item.get("tmdb_id")), None)
                returned += 1
            cleaned += 1
        self.save_data(self._daily_messages_key, retained)
        self.save_data(self._pending_key, pending)
        self.save_data(self._pushed_key, pushed)
        logger.info(f"午夜推荐清理完成：撤回 {cleaned} 条，{returned} 部未点击电影恢复随机推荐资格")

    def _telegram_target(self) -> Optional[str]:
        """读取现有 Telegram 通知配置，不在插件里复制或保存机器人凭据。"""
        notifications = self.systemconfig.get(SystemConfigKey.Notifications) or []
        for notification in notifications:
            if not isinstance(notification, dict):
                continue
            if notification.get("type") != "telegram" or not notification.get("enabled"):
                continue
            config = notification.get("config") or {}
            chat_id = config.get("TELEGRAM_CHAT_ID")
            if chat_id:
                return str(chat_id)
            admins = str(config.get("TELEGRAM_ADMINS") or "")
            if admins:
                return admins.replace(";", ",").split(",", 1)[0].strip()
        return None

    def _save_pending_context(self, media: MediaInfo, context: Context) -> str:
        torrent = context.torrent_info
        key = hashlib.sha1(
            f"{media.tmdb_id}|{self._torrent_identity(context)}".encode("utf-8")
        ).hexdigest()[:12]
        pending = self._load_pending()
        pending[key] = {
            "tmdb_id": media.tmdb_id,
            "title": media.title,
            "year": media.year,
            "torrent_identity": self._torrent_identity(context),
            "torrent_title": torrent.title,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if len(pending) > 300:
            pending = dict(list(pending.items())[-300:])
        self.save_data(self._pending_key, pending)
        return key

    def _push_movie(self, media: MediaInfo, context: Context,
                    auto_downloaded: bool = False, queued: bool = False) -> None:
        torrent = context.torrent_info
        key = None if auto_downloaded or queued else self._save_pending_context(media, context)
        if queued:
            status_text = "状态：⏳ 已加入等候下载队列"
        elif auto_downloaded:
            status_text = "状态：✅ 已提交下载"
        else:
            status_text = "状态：等待手动确认"
        lines = [
            f"<b>{html.escape(media.title_year)}</b>",
            status_text,
            f"评分：{media.vote_average or '暂无'}",
            f"资源：{html.escape(torrent.title or '未知')}",
            f"大小：{StringUtils.format_size(torrent.size) if torrent.size else '未知'}",
            f"做种：{torrent.seeders or 0}",
            "",
            html.escape(media.get_overview_string(max_len=360) or "暂无简介"),
        ]
        buttons = None
        if not auto_downloaded and not queued:
            buttons = [[{
                "text": f"下载 {StringUtils.format_size(torrent.size) if torrent.size else ''}".strip(),
                "callback_data": f"[PLUGIN]{self.__class__.__name__}|download|{key}",
            }, {
                "text": "不再推送此电影",
                "callback_data": f"[PLUGIN]{self.__class__.__name__}|suppress|{key}",
            }]]
        source, result = self._send_telegram_direct(
            title="🎬 60分钟推送电影_自用",
            text="\n".join(lines),
            image=media.get_poster_image(),
            link=media.detail_link,
            userid=self._telegram_target(),
            parse_mode="HTML",
            disable_web_page_preview=True,
            buttons=buttons,
        )
        if not result:
            raise RuntimeError("Telegram 推送失败或未配置可用实例")
        self._record_daily_message(key, media, source, result, auto_downloaded or queued)

    def _auto_download_movie(self, media: MediaInfo, context: Context,
                             force_queue: bool = False) -> Tuple[bool, bool]:
        if force_queue:
            self._enqueue_download(media, context)
            self._push_movie(media, context, queued=True)
            return True, False
        ok, error = self._submit_download(media, context)
        if not ok:
            logger.error(f"自动下载 {media.title_year} 暂时失败，转入队列：{error or '未知错误'}")
            self._enqueue_download(media, context)
            self._push_movie(media, context, queued=True)
            return True, False
        self._push_movie(media, context, auto_downloaded=True)
        return True, True

    def run_once(self, limit: Optional[int] = None, test_mode: bool = False):
        if not self._running_lock.acquire(blocking=False):
            logger.warning("智能电影推送已有任务运行，本轮跳过")
            return
        try:
            target = max(1, min(int(limit or self._limit), 50))
            pushed = self._load_recent_pushes()
            pushed_ids = set(pushed)
            suppressed_ids = set(self._load_suppressed())
            scan_cache = self._load_scan_cache()
            buckets = self._candidate_buckets()
            plans = [
                ("new", min(self._new_count, target)),
                ("recent", min(self._recent_count, target)),
                ("classic", min(self._classic_count, target)),
                ("random", min(self._random_count, target)),
            ]
            selected: List[Tuple[MediaInfo, Context]] = []
            attempted = set()
            stats = {
                "tmdb": len({str(media.tmdb_id) for values in buckets.values() for media in values}),
                "pushed": 0, "suppressed": 0, "cached": 0, "library": 0,
                "searched": 0, "no_resource": 0, "errors": 0,
            }

            def try_bucket(items: List[MediaInfo], wanted: int) -> int:
                bucket_sent = 0
                for media in items:
                    if len(selected) >= target or bucket_sent >= wanted:
                        break
                    tmdb_id = str(media.tmdb_id)
                    if tmdb_id in pushed_ids:
                        stats["pushed"] += 1
                        continue
                    if tmdb_id in suppressed_ids:
                        stats["suppressed"] += 1
                        continue
                    if tmdb_id in attempted:
                        continue
                    attempted.add(tmdb_id)
                    cached = scan_cache.get(tmdb_id)
                    if cached and cached.get("status") in {"library", "no_resource", "error"}:
                        stats["cached"] += 1
                        continue
                    if stats["searched"] >= self._max_searches:
                        break
                    try:
                        if self._already_in_library(media):
                            stats["library"] += 1
                            scan_cache[tmdb_id] = {
                                "status": "library", "checked_at": datetime.now().isoformat(timespec="seconds")}
                            continue
                        stats["searched"] += 1
                        best = self._search_best(media)
                        if not best:
                            stats["no_resource"] += 1
                            scan_cache[tmdb_id] = {
                                "status": "no_resource", "checked_at": datetime.now().isoformat(timespec="seconds")}
                            continue
                        selected.append((media, best))
                        bucket_sent += 1
                    except Exception as err:
                        stats["errors"] += 1
                        scan_cache[tmdb_id] = {
                            "status": "error", "checked_at": datetime.now().isoformat(timespec="seconds")}
                        logger.error(f"电影推送处理 {media.title_year} 失败：{err}", exc_info=True)
                return bucket_sent

            for bucket_name, wanted in plans:
                try_bucket(buckets[bucket_name], wanted)

            # 某一组资源不足时，按新片→近期→经典→随机的顺序继续补齐到总数。
            if len(selected) < target:
                fallback = []
                for bucket_name in ("new", "recent", "classic", "random"):
                    fallback.extend(buckets[bucket_name])
                try_bucket(fallback, target - len(selected))

            # 扫描阶段完成后才集中发送，避免用户在漫长搜索过程中零散收到消息。
            diagnostic = (
                f"TMDB候选 {stats['tmdb']}，已推送跳过 {stats['pushed']}，不再推送 {stats['suppressed']}，"
                f"缓存跳过 {stats['cached']}，媒体库已有 {stats['library']}，查询M-Team {stats['searched']}，"
                f"无资源/未命中过滤 {stats['no_resource']}，异常 {stats['errors']}，选中 {len(selected)}"
            )
            logger.info(f"电影扫描完成：{diagnostic}；开始集中推送")
            sent = 0

            def send_batch(auto_slots: int = 0) -> None:
                nonlocal sent
                auto_submitted = 0
                for media, best in selected:
                    tmdb_id = str(media.tmdb_id)
                    try:
                        if self._auto_download:
                            handled, submitted = self._auto_download_movie(
                                media, best, force_queue=auto_submitted >= auto_slots
                            )
                            if not handled:
                                continue
                            if submitted:
                                auto_submitted += 1
                        else:
                            self._push_movie(media, best)
                        pushed_ids.add(tmdb_id)
                        pushed[tmdb_id] = datetime.now().isoformat(timespec="seconds")
                        sent += 1
                    except Exception as err:
                        logger.error(f"集中推送 {media.title_year} 失败：{err}", exc_info=True)

            if self._auto_download:
                # 锁住“读活动数→批量提交”全过程，防止手动点击和队列补位同时越过 20 部上限。
                with self._queue_lock:
                    slots = max(0, self._max_active_downloads - self._active_download_count())
                    send_batch(slots)
            else:
                send_batch()

            self.save_data(self._scan_cache_key, scan_cache)
            self.save_data(self._pushed_key, pushed)
            logger.info(f"60分钟推送电影完成：目标 {target}，实际推送 {sent} 部，试运行={test_mode}")
            if sent == 0:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="智能电影推荐试运行完成",
                    text=f"本轮未选出电影。\n{diagnostic}",
                    userid=self._telegram_target(),
                )
        finally:
            self._running_lock.release()

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        data = event.event_data or {}
        if data.get("plugin_id") != self.__class__.__name__:
            return
        callback = str(data.get("text") or "")
        if "|" not in callback:
            return
        action, key = callback.split("|", 1)
        if action not in {"download", "suppress"}:
            return
        pending = self._load_pending()
        item = pending.get(key)
        channel = data.get("channel")
        source = data.get("source")
        userid = data.get("userid")
        username = data.get("username")
        message_id = data.get("original_message_id")
        chat_id = data.get("original_chat_id")

        if not self._is_telegram_admin(userid, username):
            logger.warning(f"拒绝非管理员操作电影推荐：userid={userid}, username={username}, action={action}")
            self.post_message(channel=channel, mtype=NotificationType.Manual,
                              title="无操作权限", text="只有 Telegram 管理员可以操作电影推荐。", userid=userid)
            return
        if not item:
            self.post_message(channel=channel, mtype=NotificationType.Manual,
                              title="操作失败", text="这条推荐已过期，请等待下一轮推荐。", userid=userid)
            return

        # 管理员点击即视为确认：先移除任务并立即撤回原消息，不等待后续下载反馈。
        pending.pop(key, None)
        self.save_data(self._pending_key, pending)
        self._remove_daily_record(key)
        if channel and source and message_id:
            deleted = self.chain.delete_message(
                channel=channel,
                source=source,
                message_id=message_id,
                chat_id=chat_id,
            )
            if not deleted:
                logger.warning(f"已接收电影推荐操作，但删除 Telegram 原消息失败：message_id={message_id}")

        if action == "suppress":
            tmdb_id = str(item.get("tmdb_id"))
            suppressed = self._load_suppressed()
            suppressed[tmdb_id] = {
                "title": " ".join(
                    value for value in [str(item.get("title") or "").strip(), str(item.get("year") or "").strip()]
                    if value
                ) or f"TMDB {tmdb_id}",
                "added_at": datetime.now().isoformat(timespec="seconds"),
            }
            self.save_data(self._suppressed_key, suppressed)
            logger.info(f"已加入不再推送列表：{suppressed[tmdb_id]['title']} (TMDB {tmdb_id})")
            return

        results = SearchChain().search_by_id(
            tmdbid=int(item["tmdb_id"]),
            mtype=MediaType.MOVIE,
            sites=[self._site_id],
            cache_local=False,
        ) or []
        context = next(
            (ctx for ctx in results if self._torrent_identity(ctx) == item.get("torrent_identity")),
            results[0] if results else None,
        )
        if not context:
            self.post_message(channel=channel, mtype=NotificationType.Manual,
                              title="下载失败", text="M-Team 中已找不到这条资源。", userid=userid)
            return

        media = context.media_info
        with self._queue_lock:
            active = self._active_download_count()
            if active >= self._max_active_downloads:
                self._enqueue_download(media, context, channel=channel, userid=userid)
                logger.info(f"管理员确认后进入等候下载：{media.title_year}，活动任务 {active}/{self._max_active_downloads}")
                return

            ok, error = self._submit_download(
                media, context, channel=channel, userid=userid,
                username="Telegram 智能电影推荐",
            )
        if not ok:
            self.post_message(channel=channel, mtype=NotificationType.Manual,
                              title="下载提交失败", text=error or "未知错误", userid=userid)
            return


