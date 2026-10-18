import hashlib
import html
import json
import math
import calendar
import random
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from types import SimpleNamespace
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import pytz
import requests
from telebot import TeleBot, types as telegram_types
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Body

from app.chain.download import DownloadChain
from app.chain.search import SearchChain
from app.chain.tmdb import TmdbChain
from app.core.config import settings
from app.core.context import Context, MediaInfo, TorrentInfo
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfo
from app.core.module import ModuleManager
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.site_oper import SiteOper
from app.db.transferhistory_oper import TransferHistoryOper
from app.helper.sites import SitesHelper
from app.log import logger
from app.modules.indexer.spider.mtorrent import MTorrentSpider
from app.modules.themoviedb.tmdbapi import TmdbApi
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType, MessageChannel, SystemConfigKey
from app.utils.string import StringUtils
from app.utils.http import RequestUtils


class PTSearchUnavailable(RuntimeError):
    """站点请求失败或限流；不能当作电影确实没有资源缓存。"""


class SmartMoviePush(_PluginBase):
    plugin_name = "智能下载影视资源_惹咪之北"
    plugin_desc = "从新片、近期口碑、经典热门和随机发现中筛选影视资源并推送或自动下载。"
    plugin_icon = "Telegram_A.png"
    plugin_version = "0.9.62"
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
    _push_interval_minutes = 60
    _limit = 20
    _test_limit = 2
    _site_id = 1
    _site_ids = [1]
    _new_count = 8
    _recent_count = 4
    _classic_count = 4
    _random_count = 4
    _dedupe_days = 30
    _min_score = 6.0
    _min_votes = 100
    _max_active_downloads = 20
    _max_searches = 80
    _telegram_source = ""
    _telegram_admins_override = ""
    _telegram_chat_id_override = ""
    _custom_telegram_bot = None
    _custom_telegram_token = ""
    _custom_telegram_thread = None
    _custom_telegram_lock = threading.RLock()
    _disk_guard_enabled = True
    _disk_guard_path = "/home"
    _disk_guard_threshold_gb = 300
    _disk_guard_recover_gb = 350
    _scheduler = None
    _running_lock = threading.Lock()
    _queue_lock = threading.Lock()
    _plugin_log_lock = threading.RLock()
    _history_archive_lock = threading.RLock()
    _library_snapshot_lock = threading.RLock()
    _library_snapshot = None
    _library_snapshot_time = 0.0
    _allowed_languages = {
        "zh", "cn", "yue", "en", "ja", "ko", "fr", "de", "es", "it", "pt",
        "nl", "sv", "no", "da", "fi", "pl", "cs", "hu", "tr", "ru",
        "ro", "el", "sr", "hr", "sk", "sl", "bg", "uk", "is", "et", "lv", "lt",
    }
    _pending_key = "pending_downloads"
    _pushed_key = "pushed_tmdb_ids"
    _scan_cache_key = "scan_cache"
    _suppressed_key = "suppressed_movies"
    _daily_messages_key = "daily_messages"
    _download_queue_key = "download_queue"
    _download_history_key = "download_history"
    _plugin_logs_key = "plugin_logs"
    _run_status_key = "run_status"
    _daily_summary_key = "daily_completion_summary"
    _access_auth_key = "access_auth"
    _access_sessions_key = "access_sessions"
    # 私人插件固定口令只以 PBKDF2 结果保存；源码和公开仓库不保存明文。
    _fixed_access_salt = "b8631d765f4de734e9325533e34d0901"
    _fixed_access_digest = "acc73ff2450a663885cfac29eac56483dcfe0dde476a23a89c15f51f5c791fd7"
    _history_backfill_key = "download_history_backfilled_v2"
    _candidate_cursor_key = "candidate_cursor"
    _disk_guard_state_key = "disk_guard_state"
    _disk_scan_key = "disk_usage_scan"
    _disk_guard_lock = threading.Lock()
    _monthly_tasks_key = "monthly_movie_tasks"
    _pt_request_lock = threading.RLock()
    _pt_request_log_key = "mteam_search_attempts_24h"
    _pt_next_request_at = 0.0
    _pt_cooldown_until = 0.0
    _monthly_tasks_lock = threading.RLock()
    _monthly_scan_lock = threading.Lock()
    _monthly_archive_lock = threading.RLock()
    _monthly_resource_lock = threading.Lock()
    _monthly_resource_job_lock = threading.RLock()
    _monthly_resource_job = {}
    _monthly_batch_lock = threading.Lock()
    _monthly_batch_job = {}

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled", True))
        self._auto_push = bool(config.get("auto_push", False))
        self._auto_download = bool(config.get("auto_download", False))
        self._annual_dispatch_enabled = bool(config.get("annual_dispatch_enabled", False))
        self._annual_dispatch_count = max(1, min(int(config.get("annual_dispatch_count") or 5), 50))
        self._annual_max_active_downloads = max(1, min(int(config.get("annual_max_active_downloads") or 5), 50))
        self._onlyonce = bool(config.get("onlyonce", False))
        self._push_interval_minutes = self._normalize_push_interval(
            config.get("push_interval_minutes") or self._interval_from_cron(config.get("cron"))
        )
        self._cron = self._cron_for_interval(self._push_interval_minutes)
        self._limit = max(1, min(int(config.get("limit") or 20), 50))
        self._test_limit = max(1, min(int(config.get("test_limit") or 2), 50))
        raw_site_ids = config.get("site_ids")
        if not isinstance(raw_site_ids, list):
            raw_site_ids = str(raw_site_ids or config.get("site_id") or 1).replace(";", ",").split(",")
        self._site_ids = []
        for value in raw_site_ids:
            try:
                site_id = int(value)
                if site_id > 0 and site_id not in self._site_ids:
                    self._site_ids.append(site_id)
            except (TypeError, ValueError):
                continue
        if not self._site_ids:
            self._site_ids = [1]
        self._site_id = self._site_ids[0]
        # 只在内存中暂存本次站点搜索返回的下载上下文，不把带私站凭据的链接写入 SQLite。
        self._monthly_resource_contexts = {}
        self._new_count = max(0, int(config.get("new_count", 8)))
        self._recent_count = max(0, int(config.get("recent_count", 4)))
        self._classic_count = max(0, int(config.get("classic_count", 4)))
        self._random_count = max(0, int(config.get("random_count", 4)))
        self._dedupe_days = max(1, int(config.get("dedupe_days", 30)))
        self._min_score = max(0.0, float(config.get("min_score", 6.0)))
        self._min_votes = max(0, int(config.get("min_votes", 100)))
        self._max_active_downloads = max(1, min(int(config.get("max_active_downloads") or 20), 100))
        self._max_searches = max(20, min(int(config.get("max_searches") or 80), 200))
        self._telegram_source = str(config.get("telegram_source") or "").strip()
        self._telegram_admins_override = str(config.get("telegram_admins_override") or "").strip()
        self._telegram_chat_id_override = str(config.get("telegram_chat_id_override") or "").strip()
        self._configure_custom_telegram_bot()
        self._disk_guard_enabled = bool(config.get("disk_guard_enabled", True))
        self._disk_guard_path = str(config.get("disk_guard_path") or "/home").strip()
        self._disk_guard_threshold_gb = max(1, int(config.get("disk_guard_threshold_gb") or 300))
        self._disk_guard_recover_gb = max(
            self._disk_guard_threshold_gb + 1,
            int(config.get("disk_guard_recover_gb") or 350),
        )

        self._ensure_access_password()

        # 旧版本只把下载写进 MoviePilot 下载历史，没有保存到插件页面。
        # 升级时自动补录一次；失败不会写完成标记，下次加载会继续尝试。
        self._backfill_download_history()
        self._migrate_legacy_organized_history()
        threading.Thread(target=self._archive_existing_monthly_scans, daemon=True).start()

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
            "annual_dispatch_enabled": self._annual_dispatch_enabled,
            "annual_dispatch_count": self._annual_dispatch_count,
            "annual_max_active_downloads": self._annual_max_active_downloads,
            "onlyonce": False,
            "cron": self._cron,
            "push_interval_minutes": self._push_interval_minutes,
            "limit": self._limit,
            "test_limit": self._test_limit,
            "site_id": self._site_id,
            "site_ids": self._site_ids,
            "new_count": self._new_count,
            "recent_count": self._recent_count,
            "classic_count": self._classic_count,
            "random_count": self._random_count,
            "dedupe_days": self._dedupe_days,
            "min_score": self._min_score,
            "min_votes": self._min_votes,
            "max_active_downloads": self._max_active_downloads,
            "max_searches": self._max_searches,
            "telegram_source": self._telegram_source,
            "telegram_admins_override": self._telegram_admins_override,
            "telegram_chat_id_override": self._telegram_chat_id_override,
            "disk_guard_enabled": self._disk_guard_enabled,
            "disk_guard_path": self._disk_guard_path,
            "disk_guard_threshold_gb": self._disk_guard_threshold_gb,
            "disk_guard_recover_gb": self._disk_guard_recover_gb,
        }

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/smartmovie",
            "event": EventType.PluginAction,
            "desc": "本插件下载统计与状态",
            "category": "",
            "data": {"action": "smartmovie_menu"},
        }]

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        return "vue", "dist/assets"

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/auth_check", "endpoint": self._api_auth_check,
             "methods": ["POST"], "auth": "bear", "summary": "检查插件访问密码会话"},
            {"path": "/auth_unlock", "endpoint": self._api_auth_unlock,
             "methods": ["POST"], "auth": "bear", "summary": "使用密码解锁插件"},
            {"path": "/auth_lock", "endpoint": self._api_auth_lock,
             "methods": ["POST"], "auth": "bear", "summary": "锁定当前浏览器会话"},
            {"path": "/secure_status", "endpoint": self._api_secure_status,
             "methods": ["POST"], "auth": "bear", "summary": "获取受密码保护的插件界面数据"},
            {"path": "/secure_history", "endpoint": self._api_secure_history,
             "methods": ["POST"], "auth": "bear", "summary": "按日期分页查看本插件下载记录"},
            {"path": "/secure_monthly", "endpoint": self._api_secure_monthly,
             "methods": ["POST"], "auth": "bear", "summary": "分页查看月份任务的完整候选名单"},
            {"path": "/ui_config", "endpoint": self._api_ui_config,
             "methods": ["POST"], "auth": "bear", "summary": "保存 Telegram 覆盖设置"},
            {"path": "/ui_action", "endpoint": self._api_ui_action,
             "methods": ["POST"], "auth": "bear", "summary": "执行插件界面操作"},
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        return [
            {
                "id": "SmartMoviePushService",
                "name": "智能下载影视资源_惹咪之北",
                # 固定每 30 分钟唤醒，再由 scheduled_run 按当前设置判断。
                # 这样在插件页面修改间隔后立即生效，无需重启 MoviePilot。
                "trigger": CronTrigger.from_crontab("*/30 * * * *", timezone=settings.TZ),
                "func": self.scheduled_run,
            },
            {
                "id": "SmartMoviePushMidnightCleanup",
                "name": "发送每日入库统计并清理推荐消息",
                "trigger": CronTrigger.from_crontab("0 0 * * *", timezone=settings.TZ),
                "func": self.midnight_maintenance,
            },
            {
                "id": "SmartMoviePushDailySummaryRetry",
                "name": "每日统计失败后补发",
                "trigger": CronTrigger.from_crontab("5 * * * *", timezone=settings.TZ),
                "func": self.send_daily_completion_summary,
            },
            {
                "id": "SmartMoviePushDownloadQueue",
                "name": "智能电影推荐顺序下载队列",
                "trigger": CronTrigger.from_crontab("* * * * *", timezone=settings.TZ),
                "func": self.process_download_queue,
            },
            {
                "id": "SmartMoviePushDiskGuard",
                "name": "JAV 与 MoviePilot 硬盘空间保护",
                "trigger": IntervalTrigger(seconds=15, timezone=settings.TZ),
                "func": self.disk_guard_tick,
            },
            {
                "id": "SmartMoviePushEmbyVerification",
                "name": "核验本插件电影是否真正进入 Emby",
                "trigger": CronTrigger.from_crontab("*/5 * * * *", timezone=settings.TZ),
                "func": self.verify_emby_ingestion,
            },
            {
                "id": "SmartMoviePushDownloadCompletion",
                "name": "核验本插件下载器任务是否真正完成",
                "trigger": CronTrigger.from_crontab("*/5 * * * *", timezone=settings.TZ),
                "func": self.reconcile_download_completions,
            },
            {
                "id": "SmartMoviePushTransferResult",
                "name": "核对本插件电影的 MoviePilot 整理结果",
                "trigger": CronTrigger.from_crontab("*/5 * * * *", timezone=settings.TZ),
                "func": self.reconcile_mp_transfer_results,
            },
        ]

    def scheduled_run(self):
        now = datetime.now(tz=pytz.timezone(settings.TZ))
        minutes_today = now.hour * 60 + now.minute
        if minutes_today % self._push_interval_minutes != 0:
            return
        if not self._enabled or not self._auto_push:
            self._append_plugin_log("定时任务", "到达计划时间；插件或定时推送已关闭，本轮跳过")
            return
        if self._disk_guard_blocks_new():
            self._append_plugin_log("定时任务", "到达计划时间；硬盘空间保护中，本轮跳过", "warning")
            return
        self._append_plugin_log("定时任务", f"到达计划时间，开始筛选；目标 {self._limit} 部")
        self.run_once(limit=self._limit, test_mode=False)

    @staticmethod
    def _normalize_push_interval(value: Any) -> int:
        try:
            interval = int(value or 60)
        except (TypeError, ValueError):
            interval = 60
        return interval if interval in {30, 60, 120, 180, 240, 300} else 60

    @staticmethod
    def _interval_from_cron(value: Any) -> int:
        cron = str(value or "").strip()
        return {
            "*/30 * * * *": 30,
            "0 * * * *": 60,
            "0 */2 * * *": 120,
            "0 */3 * * *": 180,
            "0 */4 * * *": 240,
            "0 */5 * * *": 300,
        }.get(cron, 60)

    @staticmethod
    def _cron_for_interval(interval: int) -> str:
        return {
            30: "*/30 * * * *",
            60: "0 * * * *",
            120: "0 */2 * * *",
            180: "0 */3 * * *",
            240: "0 */4 * * *",
            300: "0 */5 * * *",
        }.get(interval, "0 * * * *")

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
                                    "props": {"model": "onlyonce", "label": "立即运行一次"},
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
                                    "props": {"model": "test_limit", "label": "立即运行数量", "type": "number"},
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
            "annual_dispatch_enabled": False,
            "annual_dispatch_count": 5,
            "annual_max_active_downloads": 5,
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
            "telegram_source": "",
            "telegram_admins_override": "",
            "telegram_chat_id_override": "",
            "disk_guard_enabled": True,
            "disk_guard_path": "/home",
            "disk_guard_threshold_gb": 300,
            "disk_guard_recover_gb": 350,
        }

    def get_page(self) -> Optional[List[dict]]:
        pushed = self._load_recent_pushes()
        cache = self.get_data(self._scan_cache_key)
        cache_count = len(cache) if isinstance(cache, dict) else 0
        suppressed = self._load_suppressed()
        download_queue = self._load_download_queue()
        download_history = self._load_download_history()
        _, active_downloads = self._active_download_counts()

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
                    "title": "智能下载影视资源_惹咪之北",
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
                        {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": [{"component": "div", "text": f"随机/其他上限：{self._max_active_downloads} 部；年度上限：{self._annual_max_active_downloads} 部"}]},
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
                        action_button("立即运行", "run_once", "success"),
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
        self._append_plugin_log("手动操作", f"点击立即运行；目标 {self._test_limit} 部，模式：{'自动下载' if self._auto_download else '手动推送'}")
        if self._running_lock.locked():
            self._append_plugin_log("手动操作", "已有扫描任务正在运行，本次点击没有启动第二轮", "warning")
            return {"success": False, "message": "任务正在运行中"}
        if self._disk_guard_blocks_new():
            self._append_plugin_log("手动操作", "硬盘空间保护中，本次点击未执行", "warning")
            return {"success": False, "message": "硬盘空间保护中：立即运行、推荐推送和新增下载均已暂停；旧下载继续"}
        if self._auto_download:
            blocked_message = ""
            _, active = self._active_download_counts()
            if active >= self._max_active_downloads:
                blocked_message = (
                    f"正在下载任务已满：{active}/{self._max_active_downloads}。"
                )
            if blocked_message:
                self._append_plugin_log("手动操作", f"前置拦截：{blocked_message}；未扫描、未下载", "warning")
                text = (
                    f"{blocked_message}\n"
                    "本次立即运行已取消：没有扫描、没有推送，也没有加入等候下载。\n"
                    "请等待下载出现空位或硬盘空间恢复后再运行。"
                )
                source, result = self._send_telegram_direct(
                    title="❌ 电影推荐立即运行失败",
                    text=text,
                    userid=self._telegram_target(),
                    disable_web_page_preview=True,
                )
                if not source or not result:
                    logger.error("电影推荐立即运行失败通知未送达 Telegram，请检查机器人和目标频道权限")
                logger.warning(f"立即运行前置保护拦截：{blocked_message}")
                return {"success": False, "message": blocked_message}
        threading.Thread(target=self.run_once,
                         kwargs={"limit": self._test_limit, "test_mode": True},
                         daemon=True).start()
        self._append_plugin_log("手动操作", "扫描线程已启动；先完成筛选，再批量提交及推送")
        return {
            "success": True,
            "message": f"已开始独立运行 {self._test_limit} 部，将按当前下载模式真实执行",
        }

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

    def _api_clear_queue(self, source: str = "all") -> dict:
        if source not in {"all", "annual", "non_annual"}:
            return {"success": False, "message": "未知的等候队列来源"}
        with self._queue_lock:
            queue = self._load_download_queue()
            retained = ([item for item in queue if item.get("source") != "annual"]
                        if source == "annual" else
                        [item for item in queue if item.get("source") == "annual"]
                        if source == "non_annual" else [])
            count = len(queue) - len(retained)
            self.save_data(self._download_queue_key, retained)
        return {"success": True, "message": f"已清空 {count} 部等候下载电影"}

    def _api_clear_download_history(self) -> dict:
        count = len(self._load_stats_history())
        try:
            with self._history_archive_lock:
                with closing(self._history_archive()) as db:
                    with db:
                        db.execute("DELETE FROM history_archive")
        except Exception as err:
            logger.error(f"清理本插件历史归档失败：{err}")
            return {"success": False, "message": "清理历史归档失败，近期记录未清空；请检查插件日志"}
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

    def _telegram_sources(self) -> List[dict]:
        options = [{"title": "跟随 MoviePilot 默认 Telegram", "value": ""}]
        module = self._telegram_module()
        if not module:
            return options
        try:
            for source, conf in module.get_configs().items():
                name = str(getattr(conf, "name", "") or source)
                options.append({"title": name, "value": str(source)})
        except Exception as err:
            logger.warning(f"读取 Telegram 实例列表失败：{err}")
        return options

    @staticmethod
    def _bytes_to_gb(value: Any) -> float:
        return round(float(value or 0) / (1024 ** 3), 1)

    def _disk_free_bytes(self) -> int:
        return int(shutil.disk_usage(self._disk_guard_path).free)

    def _load_disk_guard_state(self) -> dict:
        value = self.get_data(self._disk_guard_state_key)
        if not isinstance(value, dict):
            value = {}
        return {
            "active": bool(value.get("active")),
            "incident_id": str(value.get("incident_id") or ""),
            "acked": bool(value.get("acked")),
            "activated_at": value.get("activated_at"),
            "last_alert_at": value.get("last_alert_at"),
            "last_checked_at": value.get("last_checked_at"),
            "free_bytes": int(value.get("free_bytes") or 0),
            "recovered": bool(value.get("recovered")),
            "baseline_hashes": list(value.get("baseline_hashes") or []),
            "waiting": list(value.get("waiting") or []),
            "last_error": str(value.get("last_error") or ""),
        }

    def _disk_guard_status(self) -> dict:
        state = self._load_disk_guard_state()
        try:
            free_bytes = self._disk_free_bytes()
            state["free_bytes"] = free_bytes
            state["last_error"] = ""
        except Exception as err:
            state["last_error"] = str(err)
        return {
            **state,
            "enabled": self._disk_guard_enabled,
            "path": self._disk_guard_path,
            "threshold_gb": self._disk_guard_threshold_gb,
            "recover_gb": self._disk_guard_recover_gb,
            "free_gb": self._bytes_to_gb(state.get("free_bytes")),
            "waiting_count": len(state.get("waiting") or []),
        }

    def _scan_disk_usage(self) -> dict:
        """使用 du 统计同一文件系统内的顶层目录，避免把云盘挂载算进本地硬盘。"""
        started = datetime.now()
        try:
            result = subprocess.run(
                ["du", "-x", "-B1", "-d1", self._disk_guard_path],
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
            if result.returncode not in {0, 1}:
                raise RuntimeError((result.stderr or result.stdout or "du 执行失败").strip())
            rows = []
            for line in result.stdout.splitlines():
                size_text, separator, path = line.partition("\t")
                if not separator:
                    continue
                try:
                    size = int(size_text.strip())
                except ValueError:
                    continue
                if path.rstrip("/") == self._disk_guard_path.rstrip("/"):
                    continue
                rows.append({"path": path, "bytes": size, "gb": self._bytes_to_gb(size)})
            rows.sort(key=lambda item: item["bytes"], reverse=True)
            usage = shutil.disk_usage(self._disk_guard_path)
            scan = {
                "success": True,
                "scanned_at": datetime.now().isoformat(timespec="seconds"),
                "duration_seconds": round((datetime.now() - started).total_seconds(), 1),
                "path": self._disk_guard_path,
                "total_gb": self._bytes_to_gb(usage.total),
                "used_gb": self._bytes_to_gb(usage.used),
                "free_gb": self._bytes_to_gb(usage.free),
                "directories": rows,
                "warning": (result.stderr or "").strip()[:1000],
            }
        except Exception as err:
            scan = {
                "success": False,
                "scanned_at": datetime.now().isoformat(timespec="seconds"),
                "path": self._disk_guard_path,
                "error": str(err),
                "directories": [],
            }
        self.save_data(self._disk_scan_key, scan)
        return scan

    def _disk_guard_blocks_new(self) -> bool:
        if not self._disk_guard_enabled:
            return False
        state = self._load_disk_guard_state()
        if state.get("active"):
            return True
        try:
            return self._disk_free_bytes() <= self._disk_guard_threshold_gb * (1024 ** 3)
        except Exception as err:
            # 无法读磁盘时宁可等候，也不能继续把未知状态的磁盘写满。
            logger.error(f"硬盘保护无法读取 {self._disk_guard_path}：{err}")
            return True

    @staticmethod
    def _is_guard_target(torrent: Any) -> bool:
        category = str(getattr(torrent, "category", "") or "").upper()
        tags = str(getattr(torrent, "tags", "") or "").upper()
        marker = f"{category},{tags}"
        return "DBONLINE" in marker or "DB_ONLINE" in marker or "MOVIEPILOT" in marker

    def _send_disk_guard_alert(self, state: dict) -> bool:
        free_gb = self._bytes_to_gb(state.get("free_bytes"))
        waiting_count = len(state.get("waiting") or [])
        recovered = bool(state.get("recovered"))
        if recovered:
            headline = "✅ 磁盘空间已恢复，等待后台手动恢复"
            detail = f"剩余 {free_gb}G，已达到恢复线 {self._disk_guard_recover_gb}G。"
        else:
            headline = "⛔ 硬盘空间保护已启动"
            detail = f"剩余 {free_gb}G，低于保护线 {self._disk_guard_threshold_gb}G。"
        text = (
            f"<b>{headline}</b>\n"
            f"{detail}\n"
            f"现有下载继续；新的 JAV / MoviePilot 种子只暂停等候，不删除。\n"
            f"当前保护等候：{waiting_count} 个。\n"
            f"点击“收到”只停止本次每 30 分钟提醒，不会解除保护。"
        )
        try:
            _, result = self._send_telegram_direct(
                title="💽 MoviePilot 硬盘保护",
                text=text,
                userid=self._telegram_target(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                buttons=[[{
                    "text": "收到",
                    "callback_data": (
                        f"[PLUGIN]{self.__class__.__name__}|disk_ack|{state.get('incident_id')}"
                    ),
                }]],
            )
            return bool(result)
        except Exception as err:
            logger.error(f"发送硬盘保护 Telegram 告警失败：{err}")
            return False

    def disk_guard_tick(self, force_alert: bool = False) -> None:
        """低空间时保留旧下载，暂停之后新增的 JAV/MP qB 任务。"""
        if not self._enabled:
            return
        if not self._disk_guard_enabled or not self._disk_guard_lock.acquire(blocking=False):
            return
        try:
            now = datetime.now()
            state = self._load_disk_guard_state()
            try:
                free_bytes = self._disk_free_bytes()
                torrents = DownloadChain().list_torrents(include_all_tags=True) or []
            except Exception as err:
                state["last_checked_at"] = now.isoformat(timespec="seconds")
                state["last_error"] = str(err)
                self.save_data(self._disk_guard_state_key, state)
                logger.error(f"硬盘保护检查失败：{err}")
                return

            threshold = self._disk_guard_threshold_gb * (1024 ** 3)
            recovery = self._disk_guard_recover_gb * (1024 ** 3)
            targets = {
                str(getattr(item, "hash", "") or ""): item
                for item in torrents
                if getattr(item, "hash", None) and self._is_guard_target(item)
            }

            if free_bytes <= threshold and not state.get("active"):
                state = {
                    "active": True,
                    "incident_id": now.strftime("%Y%m%d%H%M%S"),
                    "acked": False,
                    "activated_at": now.isoformat(timespec="seconds"),
                    "last_alert_at": None,
                    "last_checked_at": now.isoformat(timespec="seconds"),
                    "free_bytes": free_bytes,
                    "recovered": False,
                    # 触发瞬间已经存在的任务属于旧任务，允许继续下载。
                    "baseline_hashes": list(targets.keys()),
                    "waiting": [],
                    "last_error": "",
                }
                logger.warning(
                    f"硬盘保护启动：{self._disk_guard_path} 剩余 {self._bytes_to_gb(free_bytes)}G，"
                    f"保留现有 JAV/MP 下载 {len(targets)} 个"
                )

            if not state.get("active"):
                state.update({
                    "last_checked_at": now.isoformat(timespec="seconds"),
                    "free_bytes": free_bytes,
                    "last_error": "",
                })
                self.save_data(self._disk_guard_state_key, state)
                return

            baseline = set(state.get("baseline_hashes") or [])
            waiting = {
                str(item.get("hash") or ""): item
                for item in state.get("waiting") or []
                if item.get("hash")
            }
            for torrent_hash, torrent in targets.items():
                if torrent_hash in baseline:
                    continue
                if torrent_hash not in waiting:
                    waiting[torrent_hash] = {
                        "hash": torrent_hash,
                        "title": str(getattr(torrent, "title", "") or getattr(torrent, "name", "") or torrent_hash),
                        "category": str(getattr(torrent, "category", "") or ""),
                        "tags": str(getattr(torrent, "tags", "") or ""),
                        "downloader": str(getattr(torrent, "downloader", "") or ""),
                        "added_at": now.isoformat(timespec="seconds"),
                    }
                    logger.warning(f"硬盘保护捕获新增种子并暂停：{waiting[torrent_hash]['title']}")
                torrent_state = str(getattr(torrent, "state", "") or "").lower()
                if torrent_state not in {"paused", "stopped"}:
                    try:
                        stopped = DownloadChain().stop_torrents(
                            hashs=[torrent_hash],
                            downloader=getattr(torrent, "downloader", None),
                        )
                    except Exception as err:
                        stopped = False
                        logger.error(f"硬盘保护暂停种子异常：{waiting[torrent_hash]['title']}：{err}")
                    if not stopped:
                        logger.error(f"硬盘保护暂停种子失败：{waiting[torrent_hash]['title']} ({torrent_hash})")

            state.update({
                "waiting": list(waiting.values()),
                "free_bytes": free_bytes,
                "last_checked_at": now.isoformat(timespec="seconds"),
                "recovered": free_bytes >= recovery,
                "last_error": "",
            })
            # 先保存保护状态，Telegram 临时失联也绝不能丢失等待清单。
            self.save_data(self._disk_guard_state_key, state)

            should_alert = force_alert or not state.get("acked")
            last_alert = state.get("last_alert_at")
            if should_alert and last_alert and not force_alert:
                try:
                    should_alert = now - datetime.fromisoformat(str(last_alert)) >= timedelta(minutes=30)
                except (TypeError, ValueError):
                    should_alert = True
            if should_alert and self._send_disk_guard_alert(state):
                state["last_alert_at"] = now.isoformat(timespec="seconds")
            self.save_data(self._disk_guard_state_key, state)
        finally:
            self._disk_guard_lock.release()

    def _ack_disk_guard(self, incident_id: str = "") -> dict:
        state = self._load_disk_guard_state()
        if not state.get("active"):
            return {"success": True, "message": "当前没有硬盘保护告警"}
        if incident_id and incident_id != state.get("incident_id"):
            return {"success": False, "message": "这条告警已经过期"}
        state["acked"] = True
        self.save_data(self._disk_guard_state_key, state)
        return {"success": True, "message": "已收到，本次低空间告警不再重复提醒"}

    def _resume_disk_guard_waiting(self) -> dict:
        """空间清理后由用户在插件后台手动恢复，绝不删除种子。"""
        if not self._disk_guard_lock.acquire(blocking=False):
            return {"success": False, "message": "硬盘保护正在检查，请稍后重试"}
        try:
            state = self._load_disk_guard_state()
            if not state.get("active"):
                return {"success": True, "message": "硬盘保护未启动，无需恢复"}
            try:
                free_bytes = self._disk_free_bytes()
            except Exception as err:
                return {"success": False, "message": f"读取磁盘空间失败：{err}"}
            if free_bytes < self._disk_guard_recover_gb * (1024 ** 3):
                return {
                    "success": False,
                    "message": (
                        f"当前仅剩 {self._bytes_to_gb(free_bytes)}G，需达到 "
                        f"{self._disk_guard_recover_gb}G 才能恢复"
                    ),
                }

            torrents = DownloadChain().list_torrents(include_all_tags=True) or []
            current = {
                str(getattr(item, "hash", "") or ""): item
                for item in torrents if getattr(item, "hash", None)
            }
            failed = []
            resumed = 0
            for item in state.get("waiting") or []:
                torrent_hash = str(item.get("hash") or "")
                torrent = current.get(torrent_hash)
                if not torrent:
                    continue
                ok = DownloadChain().start_torrents(
                    hashs=[torrent_hash],
                    downloader=getattr(torrent, "downloader", None) or item.get("downloader"),
                )
                if ok:
                    resumed += 1
                else:
                    failed.append(item)
            if failed:
                state["waiting"] = failed
                state["free_bytes"] = free_bytes
                state["last_error"] = f"有 {len(failed)} 个种子恢复失败"
                self.save_data(self._disk_guard_state_key, state)
                return {
                    "success": False,
                    "message": f"已恢复 {resumed} 个，仍有 {len(failed)} 个失败并继续保留等候",
                }

            self.save_data(self._disk_guard_state_key, {
                "active": False,
                "incident_id": "",
                "acked": False,
                "activated_at": None,
                "last_alert_at": None,
                "last_checked_at": datetime.now().isoformat(timespec="seconds"),
                "free_bytes": free_bytes,
                "recovered": True,
                "baseline_hashes": [],
                "waiting": [],
                "last_error": "",
            })
            logger.info(f"硬盘保护已手动解除：恢复 qB 等候种子 {resumed} 个，MP 队列将继续自动提交")
            return {"success": True, "message": f"保护已解除，恢复 {resumed} 个种子；MP 等候队列将继续"}
        finally:
            self._disk_guard_lock.release()

    @staticmethod
    def _site_options() -> List[dict]:
        """读取 MoviePilot 已配置站点，供插件页面多选。"""
        try:
            options = []
            for site in SiteOper().list_order_by_pri() or []:
                site_id = getattr(site, "id", None)
                if not site_id:
                    continue
                name = str(getattr(site, "name", "") or getattr(site, "domain", "") or f"站点 {site_id}")
                domain = str(getattr(site, "domain", "") or "")
                options.append({
                    "title": f"{name} · {domain}" if domain and domain not in name else name,
                    "value": int(site_id),
                })
            return options
        except Exception as err:
            logger.warning(f"读取 MoviePilot 站点列表失败：{err}")
            return []

    def _ui_status_data(self) -> dict:
        suppressed = self._load_suppressed()
        cache = self.get_data(self._scan_cache_key)
        queue = self._load_download_queue()
        history = self._load_download_history()
        active_count, active_items = self._active_download_snapshot()
        annual_occupied, non_annual_occupied = self._active_download_counts()
        stats_history = self._load_stats_history()
        annual_history_count = sum(item.get("source") == "annual" for item in stats_history)
        return {
            "summary": {
                "plugin_version": self.plugin_version,
                "enabled": self._enabled,
                "auto_push": self._auto_push,
                "auto_download": self._auto_download,
                "annual_dispatch_enabled": self._annual_dispatch_enabled,
                "annual_dispatch_count": self._annual_dispatch_count,
                "annual_max_active_downloads": self._annual_max_active_downloads,
                "cron": self._cron,
                "push_interval_minutes": self._push_interval_minutes,
                "cache_count": len(cache) if isinstance(cache, dict) else 0,
                "queue_count": len(queue),
                "non_annual_queue_count": sum(item.get("source") != "annual" for item in queue),
                "history_count": self._history_total_count(history),
                "non_annual_history_count": len(stats_history) - annual_history_count,
                "suppressed_count": len(suppressed),
                "active_downloads": active_count,
                "occupied_download_slots": annual_occupied + non_annual_occupied,
                "annual_occupied_download_slots": annual_occupied,
                "non_annual_occupied_download_slots": non_annual_occupied,
                "non_annual_active_downloads": sum(item.get("source") != "annual" for item in active_items),
                "active_download_items": active_items,
                "annual_history_count": annual_history_count,
                "max_active_downloads": self._max_active_downloads,
                "limit": self._limit,
                "test_limit": self._test_limit,
                "site_ids": self._site_ids,
                "site_options": self._site_options(),
                "min_score": self._min_score,
                "max_searches": self._max_searches,
            },
            "queue": list(queue),
            "history": list(reversed(history)),
            "logs": list(reversed(self._load_plugin_logs())),
            "run_status": self.get_data(self._run_status_key) or {},
            "suppressed": [
                {"tmdb_id": tmdb_id, **item}
                for tmdb_id, item in sorted(
                    suppressed.items(),
                    key=lambda row: str(row[1].get("added_at", "")),
                    reverse=True,
                )
            ],
            "telegram": {
                "source": self._telegram_source,
                "admins_override": self._telegram_admins_override,
                "chat_id_override": self._telegram_chat_id_override,
                "effective_admins": ", ".join(sorted(self._telegram_admins())),
                "effective_chat_id": self._telegram_target() or "",
                "sources": self._telegram_sources(),
            },
            "disk_guard": self._disk_guard_status(),
            "disk_scan": self.get_data(self._disk_scan_key) or {},
            "monthly_tasks": self._monthly_task_summaries(),
            "monthly_archives": self._monthly_archive_summaries(),
        }

    @staticmethod
    def _password_digest(password: str, salt_hex: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            bytes.fromhex(salt_hex),
            260_000,
        ).hex()

    def _ensure_access_password(self) -> None:
        auth = self.get_data(self._access_auth_key)
        if (
            isinstance(auth, dict)
            and secrets.compare_digest(str(auth.get("salt") or ""), self._fixed_access_salt)
            and secrets.compare_digest(str(auth.get("digest") or ""), self._fixed_access_digest)
        ):
            return
        self.save_data(self._access_auth_key, {
            "salt": self._fixed_access_salt,
            "digest": self._fixed_access_digest,
            "created_at": datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds"),
            "mode": "private_fixed",
        })
        # 从旧版随机密码迁移时，让所有浏览器重新输入私人固定密码。
        self.save_data(self._access_sessions_key, [])
        logger.info("智能下载影视资源_惹咪之北已启用私人固定密码保护")

    def _valid_access_token(self, token: Any) -> bool:
        raw_token = str(token or "").strip()
        if not raw_token:
            return False
        now = datetime.now(tz=pytz.timezone(settings.TZ))
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        valid = False
        retained = []
        for session in self.get_data(self._access_sessions_key) or []:
            if not isinstance(session, dict):
                continue
            expires_at = self._parse_history_time(session.get("expires_at"), pytz.timezone(settings.TZ))
            if not expires_at or expires_at <= now:
                continue
            retained.append(session)
            if secrets.compare_digest(str(session.get("token_hash") or ""), token_hash):
                valid = True
        self.save_data(self._access_sessions_key, retained[-20:])
        return valid

    def _api_auth_check(self, payload: dict = Body(default={})) -> dict:
        valid = self._valid_access_token((payload or {}).get("access_token"))
        return {
            "success": valid,
            "unlocked": valid,
            "message": "已解锁" if valid else "首次使用请联系 @SDFSDFSF12321 获取密码",
        }

    def _api_auth_unlock(self, payload: dict = Body(default={})) -> dict:
        password = str((payload or {}).get("password") or "")
        auth = self.get_data(self._access_auth_key) or {}
        salt = str(auth.get("salt") or "")
        expected = str(auth.get("digest") or "")
        if not salt or not expected:
            return {"success": False, "message": "插件密码尚未初始化，请重启 MoviePilot"}
        actual = self._password_digest(password, salt)
        if not secrets.compare_digest(actual, expected):
            self._append_plugin_log("访问验证", "插件访问密码输入错误", "warning")
            return {"success": False, "message": "密码错误，请联系 @SDFSDFSF12321 获取密码"}
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(days=365)
        sessions = self.get_data(self._access_sessions_key) or []
        sessions.append({
            "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "created_at": datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds"),
            "expires_at": expires_at.isoformat(timespec="seconds"),
        })
        self.save_data(self._access_sessions_key, sessions[-20:])
        self._append_plugin_log("访问验证", "当前浏览器已成功解锁插件")
        return {
            "success": True,
            "unlocked": True,
            "access_token": token,
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "message": "插件已解锁",
        }

    def _api_auth_lock(self, payload: dict = Body(default={})) -> dict:
        raw_token = str((payload or {}).get("access_token") or "")
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest() if raw_token else ""
        sessions = [
            session for session in (self.get_data(self._access_sessions_key) or [])
            if not secrets.compare_digest(str(session.get("token_hash") or ""), token_hash)
        ]
        self.save_data(self._access_sessions_key, sessions)
        return {"success": True, "message": "插件已锁定"}

    def _api_secure_status(self, payload: dict = Body(default={})) -> dict:
        if not self._valid_access_token((payload or {}).get("access_token")):
            return {"success": False, "locked": True, "message": "插件未解锁"}
        return {"success": True, "data": self._ui_status_data()}

    def _api_secure_history(self, payload: dict = Body(default={})) -> dict:
        payload = payload or {}
        if not self._valid_access_token(payload.get("access_token")):
            return {"success": False, "locked": True, "message": "插件未解锁"}
        try:
            page = max(1, int(payload.get("page") or 1))
            page_size = int(payload.get("page_size") or 100)
        except (TypeError, ValueError):
            return {"success": False, "message": "页码或每页数量不正确"}
        if page_size not in {20, 50, 100}:
            return {"success": False, "message": "每页只能选择 20、50 或 100 条"}
        timezone = pytz.timezone(settings.TZ)
        now = datetime.now(tz=timezone)
        source = str(payload.get("source") or "all")
        if source not in {"all", "annual", "non_annual"}:
            return {"success": False, "message": "未知的下载记录来源"}
        history = [item for item in self._load_stats_history()
                   if source == "all" or (item.get("source") == "annual") == (source == "annual")]
        dated = []
        for item in history:
            submitted_at = self._parse_history_time(item.get("submitted_at"), timezone)
            if submitted_at:
                dated.append((submitted_at, item))
        dates = sorted({submitted_at.date().isoformat() for submitted_at, _ in dated}, reverse=True)
        period = str(payload.get("period") or "all").strip()
        if period not in {"all", "date", "today", "yesterday", "week", "month", "last_month", "year"}:
            return {"success": False, "message": "未知的时间范围"}
        selected_date = str(payload.get("date") or "").strip()
        if period == "date" and selected_date not in dates:
            return {"success": False, "message": "所选日期没有本插件提交的记录"}
        time_range = self._stats_range(period, now) if period not in {"all", "date"} else None
        status = str(payload.get("status") or "all").strip()
        statuses = {"all", "emby_ingested", "awaiting_library", "unfinished",
                    "organized", "organized_not_ingested", "organize_failed"}
        if status not in statuses:
            return {"success": False, "message": "未知的下载状态"}
        search = str(payload.get("search") or "").strip().casefold()[:100]
        matching = [item for submitted_at, item in dated
                    if (period != "date" or submitted_at.date().isoformat() == selected_date)
                    and (not time_range or time_range[0] <= submitted_at < time_range[1])
                    and (not search or search in str(item.get("title") or "").casefold()
                         or search in str(item.get("media_title") or "").casefold()
                         or search in str(item.get("tmdb_id") or "").casefold())]
        matching = [{**item, "view_status": self._history_view_status(item, now, timezone)}
                    for item in matching]
        status_counts = {key: 0 for key in statuses}
        status_counts["all"] = len(matching)
        for item in matching:
            status_counts[item["view_status"]] += 1
        if status != "all":
            matching = [item for item in matching if item["view_status"] == status]
        matching.sort(key=lambda item: str(item.get("submitted_at") or ""), reverse=True)
        total = len(matching)
        page = min(page, max(1, (total + page_size - 1) // page_size))
        start = (page - 1) * page_size
        return {"success": True, "data": {
            "dates": dates, "date": selected_date, "period": period, "source": source,
            "status": status, "status_counts": status_counts,
            "items": matching[start:start + page_size],
            "total": total, "page": page, "page_size": page_size,
        }}

    def _api_secure_monthly(self, payload: dict = Body(default={})) -> dict:
        payload = payload or {}
        if not self._valid_access_token(payload.get("access_token")):
            return {"success": False, "locked": True, "message": "插件未解锁"}
        archive_key = str(payload.get("archive_key") or "")
        if payload.get("archive_year") and payload.get("archive_month") is not None:
            try:
                task = self._load_monthly_archive_month(int(payload["archive_year"]),
                                                        int(payload["archive_month"]))
            except (TypeError, ValueError):
                return {"success": False, "message": "年份或月份无效"}
        else:
            task = (self._load_monthly_archive(archive_key) if archive_key else
                    self._monthly_task(str(payload.get("task_id") or "")))
        if not task:
            return {"success": False, "message": "已扫描月份不存在"}
        try:
            page = max(1, int(payload.get("page") or 1))
            page_size = min(1000, max(10, int(payload.get("page_size") or 30)))
            minimum = float(payload.get("min_score") if payload.get("min_score") is not None
                            else task.get("min_score") or 0)
            selected_month = int(payload.get("release_month") or 0)
        except (TypeError, ValueError):
            return {"success": False, "message": "页码、每页条数或评分无效"}
        if not 0 <= minimum <= 10 or not 0 <= selected_month <= 12:
            return {"success": False, "message": "评分应为 0–10 分"}
        history = {}
        for item in self._load_stats_history():
            movie_id = str(item.get("tmdb_id") or "")
            if movie_id and (movie_id not in history or str(item.get("submitted_at") or "") > str(history[movie_id].get("submitted_at") or "")):
                history[movie_id] = item
        try:
            active_rows = DownloadChain().downloading() or []
            active_ids = self._mp_active_movie_ids(active_rows)
            active_hashes = {str(self._download_value(
                row, "download_hash", "hash", "torrent_hash", "infohash", "info_hash") or "").strip().lower()
                for row in active_rows}
            active_hashes.discard("")
        except Exception as err:
            logger.warning(f"年度名单暂不能核对正在下载任务：{type(err).__name__}")
            active_ids, active_hashes = set(), set()
        active_sources = {}
        for movie_id, record in history.items():
            if record.get("download_id") and str(record["download_id"]).strip().lower() in active_hashes:
                active_ids.add(movie_id)
                active_sources[movie_id] = str(record.get("source") or "legacy")
        queue_by_id = {str(item.get("tmdb_id")): item for item in self._load_download_queue()}
        queue_ids = set(queue_by_id)
        pushed_ids = set(self._load_recent_pushes())
        suppressed_ids = set(self._load_suppressed())
        cache = self._load_scan_cache(include_expired=True)
        library_snapshot = self._library_snapshot_for_scan(force=bool(payload.get("refresh_library")))
        now = datetime.now(tz=pytz.timezone(settings.TZ))
        selected_date = str(payload.get("date") or "").strip()
        selected_category = str(payload.get("category") or "all")
        if selected_category not in {"all", "mainstream", "high_quality"}:
            return {"success": False, "message": "电影分类无效"}
        rows = []
        counts = {}
        for item in task.get("candidates") or []:
            categories = item.get("categories") or []
            if float(item.get("score") or 0) < minimum and not (task["month"] == 0 and "mainstream" in categories):
                continue
            if selected_category != "all" and selected_category not in categories:
                continue
            if selected_month and str(item.get("release_date") or "")[5:7] != f"{selected_month:02d}":
                continue
            if selected_date and str(item.get("release_date") or "") != selected_date:
                continue
            movie_id = str(item.get("tmdb_id"))
            # 名单只来自 TMDB；打开名单不预查 PT，避免数百部影片耗尽站点额度。
            record = history.get(movie_id)
            in_emby = bool(library_snapshot and movie_id in library_snapshot["tmdb_ids"])
            if record:
                status = self._history_view_status(record, now, pytz.timezone(settings.TZ))
                if in_emby:
                    # 外部方式先入库时，只更新候选名单状态；不伪造本插件下载完成记录。
                    status = "emby_ingested" if record.get("download_completed_at") else "library"
                elif library_snapshot and status == "emby_ingested":
                    stale = {key: value for key, value in record.items()
                             if key not in {"emby_ingested_at", "emby_server", "emby_item_id"}}
                    stale["status"] = "organized" if stale.get("organized_at") else "download_completed"
                    status = self._history_view_status(stale, now, pytz.timezone(settings.TZ))
            elif in_emby:
                status = "library"
            elif movie_id in queue_ids:
                status = "queued"
            elif movie_id in pushed_ids:
                status = "pushed"
            elif movie_id in suppressed_ids:
                status = "suppressed"
            else:
                status = "library" if (cache.get(movie_id) or {}).get("status") == "library" else "candidate"
            if not in_emby and movie_id in active_ids:
                status = "downloading"
            counts[status] = counts.get(status, 0) + 1
            rows.append({key: value for key, value in item.items() if key != "info"} |
                        {"status": status,
                         "download_source": active_sources.get(movie_id, "external") if status == "downloading" else "",
                         "queue_source": (queue_by_id.get(movie_id) or {}).get("source") or "random"
                         if status == "queued" else ""})
        rows.sort(key=lambda item: (-int(item.get("vote_count") or 0),
                                    -float(item.get("score") or 0), str(item.get("tmdb_id"))))
        counts["all"] = len(rows)
        counts["not_downloaded"] = sum(row["status"] in {"candidate", "pushed", "queued"} for row in rows)
        counts["emby_all"] = counts.get("emby_ingested", 0) + counts.get("library", 0)
        search = str(payload.get("search") or "").strip().casefold()[:100]
        if search:
            rows = [item for item in rows if search in str(item.get("display_title") or item.get("title") or "").casefold()
                    or search in str(item.get("title") or "").casefold()
                    or search in str(item.get("tmdb_id") or "")]
        status_filter = str(payload.get("status") or "all")
        if status_filter == "not_downloaded":
            rows = [item for item in rows if item["status"] in {"candidate", "pushed", "queued"}]
        elif status_filter == "emby_all":
            rows = [item for item in rows if item["status"] in {"emby_ingested", "library"}]
        elif status_filter != "all":
            rows = [item for item in rows if item["status"] == status_filter]
        total = len(rows)
        page = min(page, max(1, (total + page_size - 1) // page_size))
        return {"success": True, "data": {
            "task": {key: value for key, value in task.items() if key != "candidates"} | {
                "candidate_count": counts["all"]},
            "items": rows[(page - 1) * page_size:page * page_size], "counts": counts,
            "total": total, "page": page, "page_size": page_size, "date": selected_date,
            "emby_fresh": bool(library_snapshot),
            "batch_progress": dict(self._monthly_batch_job)
                if self._monthly_batch_job.get("year") == task["year"]
                and self._monthly_batch_job.get("month") == task["month"] else {},
        }}

    def _api_monthly_action(self, action: str, payload: dict) -> dict:
        task_id = str(payload.get("task_id") or "")
        task = self._monthly_task(task_id) if task_id else None
        if action == "monthly_save":
            try:
                year = int(payload.get("year"))
                month = int(payload.get("month"))
                minimum = float(payload.get("min_score"))
                min_votes = int(payload.get("min_votes") if payload.get("min_votes") is not None else 50)
            except (TypeError, ValueError):
                return {"success": False, "message": "年份、月份和最低评分必须是数字"}
            now = datetime.now(tz=pytz.timezone(settings.TZ))
            if not (1900 <= year <= now.year and 0 <= month <= 12 and 0 <= minimum <= 10
                    and 0 <= min_votes <= 10000):
                return {"success": False, "message": "请选择有效年份、0–10 分和 0–10000 人评价"}
            if month and (year, month) > (now.year, now.month):
                return {"success": False, "message": "不能扫描未来月份"}
            with self._monthly_tasks_lock:
                tasks = self._load_monthly_tasks()
                if not task and len(tasks) >= 5:
                    return {"success": False, "message": "最多只能设置 5 个独立任务"}
                if task and task.get("scan_state") == "running":
                    return {"success": False, "message": "该月份正在扫描，完成后再修改"}
                task_id = task_id if task else secrets.token_hex(6)
                updated = {
                    "id": task_id, "year": year, "month": month, "min_score": minimum,
                    "min_votes": min_votes,
                    "active": False, "scan_state": "pending", "scan_error": "",
                    "scan_progress": "等待扫描", "candidates": [], "scanned_at": "",
                    "created_at": (task or {}).get("created_at") or now.isoformat(timespec="seconds"),
                }
                tasks = [item for item in tasks if item.get("id") != task_id] + [updated]
                self.save_data(self._monthly_tasks_key, tasks)
            threading.Thread(target=self._scan_monthly_task, args=(task_id,), daemon=True).start()
            return {"success": True, "message": f"{year} 年{'全年' if month == 0 else str(month) + ' 月'}任务已保存，正在扫描完整候选名单"}
        if not task:
            return {"success": False, "message": "月份任务不存在"}
        if action == "monthly_rescan":
            if task.get("scan_state") == "running":
                return {"success": False, "message": "扫描已经在运行"}
            self._update_monthly_task(task_id, scan_state="running", scan_error="", scan_progress="准备重新扫描")
            threading.Thread(target=self._scan_monthly_task, args=(task_id,), daemon=True).start()
            return {"success": True, "message": "已开始重新扫描；旧名单会在新名单完整获取后替换"}
        if action in {"monthly_start", "monthly_pause"}:
            return {"success": False, "message": "旧年度自动任务已停用；请先勾选影片加入年度候选，再到首页控制推送"}
        if action == "monthly_delete":
            with self._monthly_tasks_lock:
                self.save_data(self._monthly_tasks_key,
                               [item for item in self._load_monthly_tasks() if item.get("id") != task_id])
            return {"success": True, "message": "月份任务及候选名单已删除；已有下载记录和已提交任务不受影响"}
        return {"success": False, "message": "未知的月份任务操作"}

    def _history_view_status(self, item: dict, now: datetime, timezone) -> str:
        """整理后留出 24 小时上传/扫描窗口，超时未入库单独列为待排查。"""
        if item.get("emby_ingested_at"):
            return "emby_ingested"
        if item.get("organized_at"):
            organized_at = self._parse_history_time(item.get("organized_at"), timezone)
            if organized_at and now - organized_at >= timedelta(hours=24):
                return "organized_not_ingested"
            return "organized"
        if item.get("organize_failed_at"):
            return "organize_failed"
        if item.get("download_completed_at"):
            return "awaiting_library"
        return "unfinished"

    def _api_ui_config(self, payload: dict = Body(default={})) -> dict:
        payload = dict(payload or {})
        if not self._valid_access_token(payload.pop("access_token", "")):
            return {"success": False, "locked": True, "message": "插件未解锁"}
        numeric_rules = {
            "limit": (1, 50, "每轮数量"),
            "test_limit": (1, 50, "立即运行数量"),
            "max_active_downloads": (1, 100, "随机/其他同时下载上限"),
            "max_searches": (20, 200, "每轮搜索候选数"),
            "annual_dispatch_count": (1, 50, "年度每分钟最多新增数量"),
            "annual_max_active_downloads": (1, 50, "年度同时下载上限"),
            "disk_guard_threshold_gb": (1, None, "停止新增阈值"),
            "disk_guard_recover_gb": (1, None, "允许恢复阈值"),
        }
        parsed_numbers = {}
        for key, (minimum, maximum, label) in numeric_rules.items():
            if key not in payload:
                continue
            try:
                raw = payload[key]
                value = int(raw)
                if isinstance(raw, bool) or str(raw).strip() != str(value):
                    raise ValueError()
            except (TypeError, ValueError):
                return {"success": False, "message": f"{label}必须是整数"}
            if value < minimum or (maximum is not None and value > maximum):
                scope = f"{minimum}–{maximum}" if maximum is not None else f"至少 {minimum}"
                return {"success": False, "message": f"{label}须在 {scope} 范围内"}
            parsed_numbers[key] = value
        if "min_score" in payload:
            try:
                score = float(payload["min_score"])
            except (TypeError, ValueError):
                return {"success": False, "message": "TMDB 最低评分必须是数字"}
            if not 0 <= score <= 10:
                return {"success": False, "message": "TMDB 最低评分须在 0–10 范围内"}
        if "site_ids" in payload:
            if not isinstance(payload["site_ids"], list):
                return {"success": False, "message": "资源搜索站点格式错误"}
            selected = []
            for raw in payload["site_ids"]:
                try:
                    site_id = int(raw)
                except (TypeError, ValueError):
                    return {"success": False, "message": "资源搜索站点包含无效 ID"}
                if site_id > 0 and site_id not in selected:
                    selected.append(site_id)
            if not selected:
                return {"success": False, "message": "请至少选择一个资源搜索站点"}
        threshold = parsed_numbers.get("disk_guard_threshold_gb", self._disk_guard_threshold_gb)
        recover = parsed_numbers.get("disk_guard_recover_gb", self._disk_guard_recover_gb)
        if recover <= threshold:
            return {"success": False, "message": "允许恢复阈值须大于停止新增阈值"}
        if "enabled" in payload:
            self._enabled = bool(payload.get("enabled"))
        if "auto_push" in payload:
            self._auto_push = bool(payload.get("auto_push"))
        if "auto_download" in payload:
            self._auto_download = bool(payload.get("auto_download"))
        if "push_interval_minutes" in payload:
            self._push_interval_minutes = self._normalize_push_interval(
                payload.get("push_interval_minutes")
            )
            self._cron = self._cron_for_interval(self._push_interval_minutes)
        if "source" in payload:
            self._telegram_source = str(payload.get("source") or "").strip()
        if "admins_override" in payload:
            self._telegram_admins_override = str(payload.get("admins_override") or "").strip()
        if "chat_id_override" in payload:
            self._telegram_chat_id_override = str(payload.get("chat_id_override") or "").strip()
        if any(key in payload for key in ("source", "admins_override", "chat_id_override")):
            self._configure_custom_telegram_bot()
        if "disk_guard_enabled" in payload:
            self._disk_guard_enabled = bool(payload.get("disk_guard_enabled"))
        if "disk_guard_path" in payload:
            self._disk_guard_path = str(payload.get("disk_guard_path") or "/home").strip()
        if "disk_guard_threshold_gb" in payload:
            self._disk_guard_threshold_gb = max(1, int(payload.get("disk_guard_threshold_gb") or 300))
        if "disk_guard_recover_gb" in payload:
            self._disk_guard_recover_gb = max(
                self._disk_guard_threshold_gb + 1,
                int(payload.get("disk_guard_recover_gb") or 350),
            )
        if "limit" in payload:
            self._limit = parsed_numbers["limit"]
        if "test_limit" in payload:
            self._test_limit = parsed_numbers["test_limit"]
        if "site_ids" in payload:
            selected = []
            for value in payload.get("site_ids") or []:
                try:
                    site_id = int(value)
                    if site_id > 0 and site_id not in selected:
                        selected.append(site_id)
                except (TypeError, ValueError):
                    continue
            if selected:
                self._site_ids = selected
                self._site_id = selected[0]
        if "min_score" in payload:
            self._min_score = max(0.0, min(float(payload.get("min_score") or 0), 10.0))
        if "max_active_downloads" in payload:
            self._max_active_downloads = parsed_numbers["max_active_downloads"]
        if "max_searches" in payload:
            self._max_searches = parsed_numbers["max_searches"]
        if "annual_dispatch_count" in payload:
            self._annual_dispatch_count = parsed_numbers["annual_dispatch_count"]
        if "annual_max_active_downloads" in payload:
            self._annual_max_active_downloads = parsed_numbers["annual_max_active_downloads"]
        self.update_config(self._current_config())
        delivery_warning = self._telegram_delivery_warning() if any(
            key in payload for key in ("source", "admins_override", "chat_id_override")
        ) else ""
        message = "插件设置已保存"
        if delivery_warning:
            message += f"；Telegram 暂不可用：{delivery_warning}"
        return {"success": True, "message": message, "warning": delivery_warning,
                "data": self._ui_status_data()}

    def _api_ui_action(self, payload: dict = Body(default={})) -> dict:
        payload = dict(payload or {})
        if not self._valid_access_token(payload.pop("access_token", "")):
            return {"success": False, "locked": True, "message": "插件未解锁"}
        action = str(payload.get("action") or "")
        if action == "remove_queue":
            result = self._api_remove_queue(str(payload.get("key") or ""))
        elif action == "clear_queue":
            result = self._api_clear_queue(str(payload.get("source") or "all"))
        elif action == "remove_suppressed":
            result = self._api_remove_suppressed(str(payload.get("tmdb_id") or ""))
        elif action == "clear_suppressed":
            result = self._api_clear_suppressed()
        elif action == "toggle_auto_push":
            result = self._api_toggle_auto_push()
        elif action == "toggle_download_mode":
            result = self._api_toggle_download_mode()
        elif action in {"annual_dispatch_start", "annual_dispatch_pause", "annual_dispatch_now"}:
            if action == "annual_dispatch_pause":
                self._annual_dispatch_enabled = False
                self.update_config(self._current_config())
                self._append_plugin_log("年度下载", "手动暂停年度推送；候选名单保留")
                result = {"success": True, "message": "年度推送已暂停；候选仍保留在年度等候队列"}
            elif not self._enabled or self._disk_guard_blocks_new():
                self._append_plugin_log("年度下载", "启动或立即推送被拦截：插件已关闭或硬盘保护中", "warning")
                result = {"success": False, "message": "插件已关闭或硬盘保护中，无法推送新下载"}
            else:
                if action == "annual_dispatch_start":
                    self._annual_dispatch_enabled = True
                    self.update_config(self._current_config())
                if not self._annual_dispatch_enabled:
                    result = {"success": False, "message": "请先启动年度推送"}
                else:
                    threading.Thread(target=self.process_download_queue, daemon=True).start()
                    annual_active, _ = self._active_download_counts()
                    waiting = sum(item.get("source") == "annual" for item in self._load_download_queue())
                    self._append_plugin_log("年度下载", f"{'启动' if action == 'annual_dispatch_start' else '手动触发'}年度补位：候选 {waiting} 部，年度占用 {annual_active}/{self._annual_max_active_downloads}，每次最多新增 {self._annual_dispatch_count} 部")
                    result = {"success": True, "message":
                              f"已启动年度推送并立即尝试补位，最多新增 {self._annual_dispatch_count} 部；"
                              + ("当前无年度候选，后续入队时每分钟自动检查补位" if not waiting else
                                 f"年度下载已满 {annual_active}/{self._annual_max_active_downloads}，空位出现后继续"
                                 if annual_active >= self._annual_max_active_downloads
                                 else "后台逐部搜索 PT 资源并提交")}
        elif action == "telegram_test":
            warning = self._telegram_delivery_warning()
            if warning:
                result = {"success": False, "message": warning}
            else:
                _, sent = self._send_telegram_direct(
                    title="✅ 电影插件 Telegram 测试",
                    text="机器人、通知频道与发送权限已验证。",
                    userid=self._telegram_target(),
                )
                result = {"success": bool(sent), "message":
                          "测试消息已发送到设置的频道" if sent else "发送失败，请检查机器人频道权限"}
        elif action == "run_once":
            result = self._api_run_once()
        elif action == "clear_cache":
            result = self._api_clear_cache()
        elif action == "clear_logs":
            source = str(payload.get("source") or "all")
            logs = self._load_plugin_logs()
            if source == "annual":
                retained = [item for item in logs if item.get("category") != "年度下载"]
            elif source == "random":
                retained = [item for item in logs if item.get("category") == "年度下载"]
            else:
                retained = []
            self.save_data(self._plugin_logs_key, retained)
            result = {"success": True, "message": f"已清空 {len(logs) - len(retained)} 条{'年度' if source == 'annual' else '随机/插件' if source == 'random' else '插件'}日志"}
        elif action == "backfill_history":
            result = self._api_backfill_download_history()
        elif action == "disk_guard_check":
            self.disk_guard_tick(force_alert=False)
            result = {"success": True, "message": "硬盘保护检查完成"}
        elif action == "disk_guard_ack":
            result = self._ack_disk_guard(str(payload.get("incident_id") or ""))
        elif action == "disk_guard_resume":
            result = self._resume_disk_guard_waiting()
        elif action == "disk_usage_scan":
            scan = self._scan_disk_usage()
            result = {
                "success": bool(scan.get("success")),
                "message": (
                    f"扫描完成：已用 {scan.get('used_gb')}G，剩余 {scan.get('free_gb')}G"
                    if scan.get("success") else f"扫描失败：{scan.get('error')}"
                ),
            }
        elif action in {"monthly_save", "monthly_rescan", "monthly_start", "monthly_pause", "monthly_delete"}:
            result = self._api_monthly_action(action, payload)
        elif action in {"monthly_resource_scan", "monthly_batch_download"}:
            try:
                year, month = int(payload.get("year")), int(payload.get("month"))
                if not 1900 <= year <= datetime.now().year or not 0 <= month <= 12:
                    raise ValueError("invalid month")
                if action == "monthly_resource_scan":
                    result = {"success": False, "message": "已取消名单预查资源；请选择电影后点击下载，提交时才会搜索 PT 站"}
                else:
                    result = self._start_monthly_batch_download(
                        year, month, payload.get("selections"))
            except (TypeError, ValueError):
                result = {"success": False, "message": "年份、月份、评分或选择的资源无效"}
        else:
            result = {"success": False, "message": "未知操作"}
        result["data"] = self._ui_status_data()
        return result

    def get_dashboard(self, key: str, **kwargs):
        return None

    def stop_service(self):
        self._stop_custom_telegram_bot()
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

    def _load_monthly_tasks(self) -> list:
        value = self.get_data(self._monthly_tasks_key)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _monthly_task(self, task_id: str) -> Optional[dict]:
        return next((item for item in self._load_monthly_tasks() if item.get("id") == task_id), None)

    def _update_monthly_task(self, task_id: str, **changes) -> Optional[dict]:
        with self._monthly_tasks_lock:
            tasks = self._load_monthly_tasks()
            for item in tasks:
                if item.get("id") == task_id:
                    item.update(changes)
                    self.save_data(self._monthly_tasks_key, tasks)
                    return item
        return None

    def _monthly_task_summaries(self) -> list:
        return [{key: value for key, value in task.items() if key != "candidates"} | {
            "candidate_count": len(task.get("candidates") or []),
            "scan_key": task.get("scan_key") or self._monthly_scan_key(task),
        } for task in self._load_monthly_tasks()]

    @staticmethod
    def _monthly_scan_key(task: dict) -> str:
        key = f"{int(task['year']):04d}-{int(task['month']):02d}-{float(task['min_score']):g}"
        return f"{key}-v{int(task.get('min_votes') or 0)}" if int(task['month']) == 0 else key

    @staticmethod
    def _chinese_movie_title(detail: dict) -> str:
        """优先使用 TMDB 中文译名；没有译名就保留原名，不机器臆译。"""
        title = str(detail.get("title") or "").strip()
        if re.search(r"[\u4e00-\u9fff]", title):
            return title
        translations = (detail.get("translations") or {}).get("translations") or []
        for country in ("CN", "TW", "HK"):
            for translation in translations:
                if (translation.get("iso_639_1") == "zh"
                        and translation.get("iso_3166_1") == country):
                    translated = str((translation.get("data") or {}).get("title") or "").strip()
                    if re.search(r"[\u4e00-\u9fff]", translated):
                        return translated
        alternatives = (detail.get("alternative_titles") or {}).get("titles") or []
        for country in ("CN", "TW", "HK"):
            for alternative in alternatives:
                translated = str(alternative.get("title") or "").strip()
                if (alternative.get("iso_3166_1") == country
                        and re.search(r"[\u4e00-\u9fff]", translated)):
                    return translated
        return title or str(detail.get("original_title") or "")

    def _monthly_archive(self):
        connection = sqlite3.connect(str(self.get_data_path() / "monthly_scans.sqlite"), timeout=20)
        connection.execute("CREATE TABLE IF NOT EXISTS monthly_scans "
                           "(scan_key TEXT PRIMARY KEY, year INTEGER, month INTEGER, "
                           "min_score REAL, scanned_at TEXT, candidate_count INTEGER, "
                           "scan_count INTEGER NOT NULL DEFAULT 1)")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(monthly_scans)")}
        if "scan_count" not in columns:
            connection.execute("ALTER TABLE monthly_scans ADD COLUMN scan_count INTEGER NOT NULL DEFAULT 1")
            connection.commit()
        connection.execute("CREATE TABLE IF NOT EXISTS monthly_scan_movies "
                           "(scan_key TEXT NOT NULL, tmdb_id TEXT NOT NULL, release_date TEXT, "
                           "payload TEXT NOT NULL, PRIMARY KEY(scan_key, tmdb_id))")
        connection.execute("CREATE INDEX IF NOT EXISTS monthly_scan_movies_date "
                           "ON monthly_scan_movies(scan_key, release_date)")
        connection.execute("CREATE TABLE IF NOT EXISTS monthly_resource_cache "
                           "(month_key TEXT NOT NULL, tmdb_id TEXT NOT NULL, scope TEXT NOT NULL, "
                           "checked_at REAL NOT NULL, payload TEXT NOT NULL, "
                           "PRIMARY KEY(month_key, tmdb_id, scope))")
        return connection

    def _save_monthly_archive(self, task: dict, candidates: list, count_scan: bool = False) -> str:
        key = self._monthly_scan_key(task)
        with self._monthly_archive_lock:
            with closing(self._monthly_archive()) as db:
                with db:
                    previous = db.execute("SELECT scan_count FROM monthly_scans WHERE scan_key=?", (key,)).fetchone()
                    scan_count = (int(previous[0]) + int(count_scan)) if previous else 1
                    db.execute("INSERT OR REPLACE INTO monthly_scans "
                               "(scan_key, year, month, min_score, scanned_at, candidate_count, scan_count) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (key, int(task["year"]), int(task["month"]), float(task["min_score"]),
                                str(task.get("scanned_at") or ""), len(candidates), scan_count))
                    db.execute("DELETE FROM monthly_scan_movies WHERE scan_key=?", (key,))
                    db.executemany("INSERT INTO monthly_scan_movies VALUES (?, ?, ?, ?)", [
                        (key, str(item["tmdb_id"]), str(item.get("release_date") or ""),
                         json.dumps(item, ensure_ascii=False, default=str)) for item in candidates
                    ])
        return key

    def _load_monthly_archive(self, key: str) -> Optional[dict]:
        with self._monthly_archive_lock:
            with closing(self._monthly_archive()) as db:
                row = db.execute("SELECT year, month, min_score, scanned_at, candidate_count, scan_count "
                                 "FROM monthly_scans WHERE scan_key=?", (key,)).fetchone()
                if not row:
                    return None
                candidates = [json.loads(item[0]) for item in db.execute(
                    "SELECT payload FROM monthly_scan_movies WHERE scan_key=? "
                    "ORDER BY release_date, tmdb_id", (key,))]
        candidates.sort(key=lambda item: (
            -float(item.get("popularity") or (item.get("info") or {}).get("popularity") or 0),
            -int(item.get("vote_count") or (item.get("info") or {}).get("vote_count") or 0),
            -float(item.get("score") or 0), str(item.get("release_date") or "")))
        return {"scan_key": key, "year": row[0], "month": row[1], "min_score": row[2],
                "scanned_at": row[3], "candidate_count": row[4], "scan_count": row[5], "candidates": candidates,
                "scan_state": "complete"}

    def _load_monthly_archive_month(self, year: int, month: int) -> Optional[dict]:
        """同月不同评分的归档合并去重，最新一次扫描的资料优先。"""
        if not (1900 <= year <= datetime.now().year and 0 <= month <= 12):
            return None
        with self._monthly_archive_lock:
            with closing(self._monthly_archive()) as db:
                keys = [row[0] for row in db.execute(
                    "SELECT scan_key FROM monthly_scans WHERE year=? AND month=? "
                    "ORDER BY scanned_at DESC, min_score ASC", (year, month))]
        if not keys:
            return None
        archives = [self._load_monthly_archive(key) for key in keys]
        archives = [archive for archive in archives if archive]
        movies = {}
        for archive in archives:
            for movie in archive["candidates"]:
                movies.setdefault(str(movie["tmdb_id"]), movie)
        candidates = sorted(movies.values(), key=lambda item: (
            -float(item.get("popularity") or (item.get("info") or {}).get("popularity") or 0),
            -int(item.get("vote_count") or (item.get("info") or {}).get("vote_count") or 0),
            -float(item.get("score") or 0), str(item.get("release_date") or "")))
        return {"year": year, "month": month, "scan_key": f"{year:04d}-{month:02d}",
                "min_score": min(archive["min_score"] for archive in archives),
                "scanned_at": archives[0]["scanned_at"],
                "scan_count": sum(archive["scan_count"] for archive in archives),
                "candidate_count": len(candidates), "candidates": candidates,
                "scan_state": "complete"}

    def _monthly_archive_summaries(self) -> list:
        with self._monthly_archive_lock:
            with closing(self._monthly_archive()) as db:
                scans = db.execute("SELECT scan_key, year, month, min_score, scanned_at, "
                                   "candidate_count, scan_count FROM monthly_scans "
                                   "ORDER BY year DESC, month DESC, scanned_at DESC, min_score DESC").fetchall()
                days = db.execute("SELECT scan_key, release_date, COUNT(*) FROM monthly_scan_movies "
                                  "GROUP BY scan_key, release_date").fetchall()
                month_counts = db.execute(
                    "SELECT s.year, s.month, COUNT(DISTINCT m.tmdb_id) "
                    "FROM monthly_scans s JOIN monthly_scan_movies m ON m.scan_key=s.scan_key "
                    "GROUP BY s.year, s.month").fetchall()
        day_counts = {}
        for key, date, count in days:
            if date:
                day_counts.setdefault(key, {})[date] = count
        monthly_totals = {(year, month): count for year, month, count in month_counts}
        return [{"scan_key": key, "year": year, "month": month, "min_score": score,
                 "scanned_at": scanned_at, "candidate_count": count, "scan_count": scan_count,
                 "month_candidate_count": monthly_totals.get((year, month), count),
                 "days": day_counts.get(key, {})}
                for key, year, month, score, scanned_at, count, scan_count in scans]

    def _monthly_resource_scope(self) -> str:
        """站点选择变动时不复用旧的资源搜索结果。"""
        ids = sorted(int(site) for site in self._site_ids)
        # v2 不复用旧版本把馒头限流误判为“无资源”的缓存。
        return hashlib.sha256(json.dumps(["pt-api-v2", ids]).encode()).hexdigest()[:16]

    @staticmethod
    def _monthly_resource_rank(context: Context) -> int:
        text = f"{getattr(context.meta_info, 'resource_pix', '')} {context.torrent_info.title or ''}".lower()
        if re.search(r"\b(4320p|8k)\b", text):
            return 4320
        if re.search(r"\b(2160p|4k|uhd)\b", text):
            return 2160
        if re.search(r"\b(1080p|fullhd|fhd)\b", text):
            return 1080
        if re.search(r"\b720p\b", text):
            return 720
        if re.search(r"\b480p\b", text):
            return 480
        return 0

    def _monthly_resource_options(self, contexts: list) -> list:
        """SearchChain 已按 MoviePilot 规则过滤；同片只展示最高清的两个候选。"""
        ranked = sorted((ctx for ctx in contexts if getattr(ctx, 'torrent_info', None)), key=lambda ctx: (
            -self._monthly_resource_rank(ctx),
            -int(ctx.torrent_info.seeders or 0),
            -float(ctx.torrent_info.size or 0)))
        options, identities = [], set()
        for context in ranked:
            identity = self._torrent_identity(context)
            if identity in identities:
                continue
            identities.add(identity)
            torrent = context.torrent_info
            resolution = self._monthly_resource_rank(context)
            options.append({
                "id": identity, "title": str(torrent.title or "未知资源")[:250],
                "site": str(torrent.site_name or torrent.site or "未知站点"),
                "size_gb": round(float(torrent.size or 0) / (1024 ** 3), 2),
                "seeders": int(torrent.seeders or 0),
                "resolution": f"{resolution}P" if resolution else "未知",
            })
            if len(options) == 2:
                break
        return options

    def _remember_monthly_resource_contexts(self, year: int, month: int, movie_id: str,
                                            contexts: list, options: list) -> None:
        """短时保留已通过 MoviePilot 规则的上下文，批量提交可直接复用资源链接。"""
        selected = {option["id"] for option in options}
        now = time.time()
        scope = self._monthly_resource_scope()
        with self._monthly_resource_job_lock:
            cache = getattr(self, "_monthly_resource_contexts", {})
            cache = {key: value for key, value in cache.items()
                     if now - value[0] < 30 * 60 and value[1] == scope}
            for context in contexts:
                identity = self._torrent_identity(context)
                if identity in selected:
                    cache[(year, month, movie_id, identity)] = (now, scope, context)
            self._monthly_resource_contexts = cache

    def _cached_monthly_resource_context(self, year: int, month: int, movie_id: str,
                                         resource_id: str) -> Optional[Context]:
        with self._monthly_resource_job_lock:
            entry = getattr(self, "_monthly_resource_contexts", {}).get(
                (year, month, movie_id, resource_id))
        if not entry or time.time() - entry[0] >= 30 * 60 or entry[1] != self._monthly_resource_scope():
            return None
        return entry[2]

    def _load_monthly_resource_cache(self, year: int, month: int) -> dict:
        month_key = f"{year:04d}-{month:02d}"
        scope = self._monthly_resource_scope()
        fresh_after = time.time() - 24 * 3600
        with self._monthly_archive_lock:
            with closing(self._monthly_archive()) as db:
                rows = db.execute(
                    "SELECT tmdb_id, checked_at, payload FROM monthly_resource_cache "
                    "WHERE month_key=? AND scope=?", (month_key, scope)).fetchall()
        # 空结果可能是站点临时不可用或识别延迟，不能像有效资源一样缓存一整天。
        empty_fresh_after = time.time() - 5 * 60
        result = {}
        for tmdb_id, checked_at, payload in rows:
            if checked_at < fresh_after:
                continue
            options = json.loads(payload)
            if options or checked_at >= empty_fresh_after:
                result[tmdb_id] = options
        return result

    def _save_monthly_resource_cache(self, year: int, month: int, tmdb_id: str, options: list) -> None:
        with self._monthly_archive_lock:
            with closing(self._monthly_archive()) as db:
                with db:
                    db.execute("INSERT OR REPLACE INTO monthly_resource_cache VALUES (?, ?, ?, ?, ?)", (
                        f"{year:04d}-{month:02d}", tmdb_id, self._monthly_resource_scope(),
                        time.time(), json.dumps(options, ensure_ascii=False)))

    def _start_monthly_resource_scan(self, year: int, month: int, minimum: float,
                                     force: bool = False, target_tmdb_id: str = "",
                                     target_tmdb_ids: list = None) -> dict:
        archive = self._load_monthly_archive_month(year, month)
        if not archive:
            return {"success": False, "message": "这个月尚无扫描名单"}
        if minimum < float(archive["min_score"]):
            return {"success": False, "message": f"保存名单最低为 {archive['min_score']} 分；降低评分需先重新扫描月份"}
        if target_tmdb_ids is not None and (not isinstance(target_tmdb_ids, list)
                                            or not 1 <= len(target_tmdb_ids) <= 1000):
            return {"success": False, "message": "每次请选择 1–1000 部电影重新匹配 PT 站"}
        target_ids = list(dict.fromkeys(
            [target_tmdb_id] if target_tmdb_id else [str(value) for value in (target_tmdb_ids or [])]))
        eligible_ids = {str(item.get("tmdb_id")) for item in archive["candidates"]
                        if float(item.get("score") or 0) >= minimum
                        or (month == 0 and "mainstream" in (item.get("categories") or []))}
        if target_ids and (not all(value.isdigit() for value in target_ids)
                           or any(value not in eligible_ids for value in target_ids)):
            return {"success": False, "message": "所选电影不在当前名单或评分范围内"}
        cached = self._load_monthly_resource_cache(year, month)
        if not self._monthly_resource_lock.acquire(blocking=False):
            with self._monthly_resource_job_lock:
                job = self._monthly_resource_job
                if (job.get("running") and job.get("year") == year and job.get("month") == month
                        and job.get("min_score") == minimum and job.get("scope") == self._monthly_resource_scope()):
                    if target_ids:
                        priority = job.setdefault("priority_ids", [])
                        for movie_id in target_ids:
                            if movie_id not in priority:
                                priority.append(movie_id)
                        job["target_tmdb_id"] = target_ids[0] if len(target_ids) == 1 else ""
                        job["message"] = f"已将 {len(target_ids)} 部电影加入优先重查，当前搜索结束后依次查询"
                        return {"success": True, "message": job["message"]}
                    return {"success": True, "message": "这个月份的资源查询正在继续"}
            return {"success": False, "message": "已有月份资源搜索在运行，请等完成后再启动另一轮"}
        candidates = [item for item in archive["candidates"] if float(item.get("score") or 0) >= minimum
                      or (month == 0 and "mainstream" in (item.get("categories") or []))]
        if target_ids:
            selected = set(target_ids)
            candidates = [item for item in candidates if str(item.get("tmdb_id")) in selected]
            if len(candidates) != len(selected):
                self._monthly_resource_lock.release()
                return {"success": False, "message": "所选电影不在当前年度名单或评分范围内"}
        candidates.sort(key=lambda item: (-int(item.get("vote_count") or 0),
                                          -float(item.get("score") or 0), str(item.get("tmdb_id"))))
        queued_ids = {str(item.get("tmdb_id")) for item in self._load_download_queue()}
        pending = candidates if force else [item for item in candidates
                   if str(item["tmdb_id"]) not in cached
                   or (str(item["tmdb_id"]) in queued_ids and not cached[str(item["tmdb_id"])])]
        batch = pending if month == 0 or target_ids else pending[:60]
        if not batch:
            self._monthly_resource_lock.release()
            return {"success": True, "message": "这个月份的资源已全部核对；如需重新搜索请点击重新查站点"}
        job = {"year": year, "month": month, "min_score": minimum, "scope": self._monthly_resource_scope(),
               "running": True, "done": 0, "total": len(batch), "found": 0, "errors": 0,
               "target_tmdb_id": target_ids[0] if len(target_ids) == 1 else "",
               "priority_ids": [], "message": "",
               "checked": len(candidates) - len(pending), "candidates": len(candidates),
               "started_at": datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds")}
        with self._monthly_resource_job_lock:
            self._monthly_resource_job = job
        try:
            threading.Thread(target=self._scan_monthly_resources,
                             args=(year, month, batch, force, target_ids), daemon=True).start()
        except Exception:
            self._monthly_resource_lock.release()
            raise
        return {"success": True, "message": f"后台开始核对 {len(batch)} 部电影的站点资源；匹配结果逐步显示"}

    def _request_mteam_torrents(self, site: dict, keyword: str) -> list:
        """读取馒头 API，区分真实空结果与限流/接口错误。"""
        spider = MTorrentSpider(site)
        if not spider._apikey:
            raise PTSearchUnavailable("馒头站点没有配置 API Key")
        cls = type(self)
        with cls._pt_request_lock:
            now = time.monotonic()
            if now < cls._pt_cooldown_until:
                wait_minutes = math.ceil((cls._pt_cooldown_until - now) / 60)
                raise PTSearchUnavailable(f"馒头接口仍在限流，请约 {wait_minutes} 分钟后重试")
            # 站点建议近 24 小时最多 1000 次；插件最多使用其中 400 次，
            # 其余留给 MoviePilot 和用户的手动搜索。跨重启保存，避免重启重置额度。
            wall_now = time.time()
            attempts = [stamp for stamp in (self.get_data(self._pt_request_log_key) or [])
                        if isinstance(stamp, (int, float)) and wall_now - 86400 < stamp <= wall_now]
            if len(attempts) >= 400:
                wait_minutes = math.ceil((attempts[0] + 86400 - wall_now) / 60)
                raise PTSearchUnavailable(f"馒头搜索已达到插件近 24 小时安全额度，请约 {wait_minutes} 分钟后重试")
            delay = cls._pt_next_request_at - now
            if delay > 0:
                time.sleep(delay)
            # 短时间批量选择可更快处理；若站点仍返回限流，沿用一小时冷却。
            cls._pt_next_request_at = time.monotonic() + 30
            attempts.append(time.time())
            self.save_data(self._pt_request_log_key, attempts)
            try:
                response = RequestUtils(
                    headers={"Content-Type": "application/json",
                             "User-Agent": str(spider._ua or "MoviePilot"),
                             "x-api-key": spider._apikey},
                    proxies=spider._proxy, referer=f"{spider._domain}browse",
                    timeout=spider._timeout,
                ).post_res(url=spider._searchurl,
                           json=spider._MTorrentSpider__get_params(keyword, MediaType.MOVIE, 0))
            except Exception as err:
                raise PTSearchUnavailable(f"馒头接口连接异常：{type(err).__name__}，未缓存为无资源") from err
            if response is None:
                raise PTSearchUnavailable("馒头接口连接失败，未缓存为无资源")
            if response.status_code != 200:
                raise PTSearchUnavailable(f"馒头接口 HTTP {response.status_code}，未缓存为无资源")
            try:
                payload = response.json()
            except ValueError as err:
                raise PTSearchUnavailable("馒头接口未返回有效 JSON，未缓存为无资源") from err
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                message = str(payload.get("message") or "接口未返回数据") if isinstance(payload, dict) else "接口未返回数据"
                if "頻繁" in message or "频繁" in message or str(payload.get("code")) == "4":
                    cls._pt_cooldown_until = time.monotonic() + 3600
                    raise PTSearchUnavailable("馒头接口请求过于频繁，已暂停站点查询 1 小时；不会标记为无资源")
                raise PTSearchUnavailable(f"馒头接口错误：{message[:100]}；未缓存为无资源")
            rows = data.get("data") or []
            if not isinstance(rows, list):
                raise PTSearchUnavailable("馒头接口资源格式异常，未缓存为无资源")
            # 馒头有些种子的 status 为 null；MoviePilot 原解析器会在 .get 处崩溃。
            rows = [{**row, "status": row.get("status") or {}}
                    for row in rows if isinstance(row, dict)]
            try:
                parsed = spider._MTorrentSpider__parse_result(rows)
            except Exception as err:
                raise PTSearchUnavailable(f"馒头资源解析失败：{type(err).__name__}，未缓存为无资源") from err
            return [TorrentInfo(site=site.get("id"), site_name=site.get("name"),
                                site_cookie=site.get("cookie"), site_ua=site.get("ua"),
                                site_proxy=site.get("proxy"), site_order=site.get("pri"),
                                site_downloader=site.get("downloader"), **row)
                    for row in parsed]

    def _search_site_contexts(self, tmdb_id: int) -> list:
        """沿用 MoviePilot 的过滤与精确匹配，馒头查询额外处理限流。"""
        indexers = {site.get("id"): site for site in SitesHelper().get_indexers()}
        unavailable = [sid for sid in self._site_ids if sid not in indexers]
        if unavailable:
            raise PTSearchUnavailable(f"所选站点 {unavailable} 未启用或不可用，未标记为无资源")
        mteam = [indexers[sid] for sid in self._site_ids
                 if sid in indexers and indexers[sid].get("parser") == "mTorrent"]
        other_sites = [sid for sid in self._site_ids if sid not in {site["id"] for site in mteam}]
        contexts = []
        if mteam:
            chain = SearchChain()
            media = chain.recognize_media(tmdbid=int(tmdb_id), mtype=MediaType.MOVIE)
            if not media:
                raise PTSearchUnavailable(f"TMDB {tmdb_id} 媒体信息识别失败")
            keywords = list(dict.fromkeys(str(value).strip() for value in
                                          (media.original_title, media.en_title, media.title)
                                          if value and str(value).strip()))
            for site in mteam:
                for keyword in keywords:
                    torrents = self._request_mteam_torrents(site, keyword)
                    if not torrents:
                        continue
                    matched = chain._SearchChain__parse_result(torrents=torrents, mediainfo=media)
                    if matched:
                        contexts.extend(matched)
                        break
        if other_sites:
            contexts.extend(SearchChain().search_by_id(
                tmdbid=int(tmdb_id), mtype=MediaType.MOVIE,
                sites=other_sites, cache_local=False) or [])
        return contexts

    def _scan_monthly_resources(self, year: int, month: int, candidates: list, force: bool,
                                target_tmdb_ids: list = None) -> None:
        try:
            cached = {} if force else self._load_monthly_resource_cache(year, month)
            library = self._library_snapshot_for_scan()
            downloaded = {str(item.get("tmdb_id")) for item in self._load_stats_history()}
            queued = {str(item.get("tmdb_id")) for item in self._load_download_queue()}
            remaining = {str(item["tmdb_id"]): item for item in candidates}
            ordered_ids = list(remaining)
            while remaining or self._monthly_resource_job.get("priority_ids"):
                with self._monthly_resource_job_lock:
                    priority = self._monthly_resource_job.get("priority_ids") or []
                    if priority:
                        priority_id = priority.pop(0)
                        item = remaining.pop(priority_id, None)
                        if item is None:
                            archive = self._load_monthly_archive_month(year, month)
                            item = next((entry for entry in (archive or {}).get("candidates", [])
                                         if str(entry.get("tmdb_id")) == priority_id), None)
                            if item:
                                self._monthly_resource_job["total"] += 1
                        diagnostic = True
                    else:
                        while ordered_ids and ordered_ids[0] not in remaining:
                            ordered_ids.pop(0)
                        if not ordered_ids:
                            break
                        item = remaining.pop(ordered_ids.pop(0))
                        diagnostic = bool(target_tmdb_ids)
                if not item:
                    continue
                tmdb_id = str(item["tmdb_id"])
                options = None if diagnostic else cached.get(tmdb_id)
                if tmdb_id in queued and not options:
                    options = None
                try:
                    if options is None:
                        if (library and tmdb_id in library["tmdb_ids"]) or tmdb_id in downloaded:
                            options = []
                            if diagnostic:
                                self._monthly_resource_job["message"] = f"{item.get('title') or tmdb_id} 已在媒体库或本插件下载记录中，不重复找资源"
                        else:
                            contexts = self._search_site_contexts(int(tmdb_id))
                            options = self._monthly_resource_options(contexts)
                            self._remember_monthly_resource_contexts(year, month, tmdb_id, contexts, options)
                            if diagnostic:
                                name = item.get("display_title") or item.get("title") or tmdb_id
                                self._monthly_resource_job["message"] = (
                                    f"{name}：MoviePilot 在所选站点返回 {len(contexts)} 条规则匹配资源，展示 {len(options)} 条")
                                self._append_plugin_log("资源查询", f"TMDB {tmdb_id} {self._monthly_resource_job['message']}；站点 {self._site_ids}")
                        self._save_monthly_resource_cache(year, month, tmdb_id, options)
                    with self._monthly_resource_job_lock:
                        self._monthly_resource_job["found"] += bool(options)
                except PTSearchUnavailable as err:
                    self._monthly_resource_job["message"] = str(err)
                    self._append_plugin_log("资源查询", f"TMDB {tmdb_id}：{err}", "error")
                    with self._monthly_resource_job_lock:
                        self._monthly_resource_job["errors"] += 1
                    break
                except Exception as err:
                    logger.warning(f"月份资源核对 {tmdb_id} 失败：{err}")
                    if diagnostic:
                        self._monthly_resource_job["message"] = f"TMDB {tmdb_id} 单片资源查询失败：{type(err).__name__}：{str(err)[:120]}"
                        self._append_plugin_log("资源查询", self._monthly_resource_job["message"], "error")
                    with self._monthly_resource_job_lock:
                        self._monthly_resource_job["errors"] += 1
                finally:
                    with self._monthly_resource_job_lock:
                        self._monthly_resource_job["done"] += 1
        finally:
            with self._monthly_resource_job_lock:
                self._monthly_resource_job["running"] = False
                self._monthly_resource_lock.release()

    def _start_monthly_batch_download(self, year: int, month: int, selections: list) -> dict:
        """只保存选中的电影；下载时与随机任务共用 MoviePilot 站点搜索。"""
        if not self._enabled or self._disk_guard_blocks_new():
            return {"success": False, "message": "插件或硬盘保护已停止新增下载"}
        if not isinstance(selections, list) or not 1 <= len(selections) <= 1000:
            return {"success": False, "message": "每次请选择 1–1000 部电影"}
        archive = self._load_monthly_archive_month(year, month)
        if not archive:
            return {"success": False, "message": "月份名单不存在"}
        movies = {str(item["tmdb_id"]): item for item in archive["candidates"]}
        validated, seen = [], set()
        for choice in selections:
            movie_id = str(choice.get("tmdb_id") or "") if isinstance(choice, dict) else ""
            resource_id = str(choice.get("resource_id") or "") if isinstance(choice, dict) else ""
            if movie_id in seen or movie_id not in movies or resource_id:
                return {"success": False, "message": "选择中包含重复、无效影片或旧版预查资源，请刷新名单后重试"}
            seen.add(movie_id)
            validated.append((movies[movie_id], ""))
        if not self._monthly_batch_lock.acquire(blocking=False):
            return {"success": False, "message": "上一次批量下载还在提交中"}
        self._monthly_batch_job = {"running": True, "total": len(validated), "done": 0,
                                   "submitted": 0, "queued": 0, "skipped": 0, "errors": 0,
                                   "year": year, "month": month, "message": ""}
        try:
            threading.Thread(target=self._run_monthly_batch_download,
                             args=(year, month, validated), daemon=True).start()
        except Exception:
            self._monthly_batch_lock.release()
            raise
        return {"success": True, "message": f"正在登记选中的 {len(validated)} 部；已有下载或等候的影片会跳过，首页开启年度推送后才会搜索并提交"}

    def _run_monthly_batch_download(self, year: int, month: int, validated: list) -> None:
        try:
            plugin_ids = {str(item.get("tmdb_id")) for item in self._load_stats_history()}
            library = self._library_snapshot_for_scan(force=True)
            if not library:
                self._monthly_batch_job["errors"] = len(validated)
                self._monthly_batch_job["done"] = len(validated)
                self._append_plugin_log("月份下载", "Emby 目录暂不可核对，未提交下载；请稍后重试", "error")
                return
            # 勾选操作只登记候选；搜索 PT 和提交种子由共享补位器在空位出现时处理。
            # 这样 20 部可立即显示为等候，而不是每搜完一部才出现一条。
            with self._queue_lock:
                try:
                    active_torrents = DownloadChain().downloading() or []
                except Exception as err:
                    self._monthly_batch_job["errors"] = len(validated)
                    self._monthly_batch_job["done"] = len(validated)
                    self._monthly_batch_job["message"] = f"无法核对 MoviePilot 正在下载任务：{type(err).__name__}"
                    return
                active_ids = self._mp_active_movie_ids(active_torrents)
                queue = self._load_download_queue()
                new_entries = []
                queued_ids = {str(entry.get("tmdb_id")) for entry in queue}
                duplicates = 0
                for item, _ in validated:
                    movie_id = str(item["tmdb_id"])
                    try:
                        if not self._enabled or self._disk_guard_blocks_new():
                            self._monthly_batch_job["skipped"] += 1
                        elif movie_id in plugin_ids or movie_id in library["tmdb_ids"] or movie_id in active_ids:
                            self._monthly_batch_job["skipped"] += 1
                        elif movie_id in queued_ids:
                            # 随机队列已经负责下载，不复制到年度队列。
                            duplicates += 1
                            self._monthly_batch_job["skipped"] += 1
                        else:
                            media = MediaInfo(tmdb_info=item["info"])
                            new_entries.append({
                                "key": hashlib.sha1(f"{movie_id}|{datetime.now().isoformat()}".encode()).hexdigest()[:12],
                                "tmdb_id": media.tmdb_id, "title": media.title_year,
                                "source": "annual", "torrent_identity": "",
                                "channel": None, "userid": None,
                                "created_at": datetime.now().isoformat(timespec="seconds"),
                                "attempts": 0,
                            })
                            queued_ids.add(movie_id)
                            self._monthly_batch_job["queued"] += 1
                    except Exception as err:
                        self._monthly_batch_job["errors"] += 1
                        logger.error(f"年度候选登记 {movie_id} 失败：{err}", exc_info=True)
                    finally:
                        self._monthly_batch_job["done"] += 1
                if self._monthly_batch_job["queued"]:
                    # 手动勾选的年度候选优先于自动随机队列补位；旧年度顺序不变。
                    ordered = ([entry for entry in queue if entry.get("source") == "annual"]
                               + new_entries
                               + [entry for entry in queue if entry.get("source") != "annual"])
                    self.save_data(self._download_queue_key, ordered[:2000])
                self._monthly_batch_job["message"] = (
                    f"已登记 {self._monthly_batch_job['queued']} 部；{duplicates} 部已在随机/年度等候队列，"
                    f"当前年度下载 {self._active_download_counts(active_torrents)[0]}/{self._annual_max_active_downloads}；首页开启年度推送后再搜索资源")
            self._append_plugin_log("月份下载", self._monthly_batch_job["message"])
        finally:
            self._monthly_batch_job["running"] = False
            self._monthly_batch_lock.release()

    def _archive_existing_monthly_scans(self) -> None:
        """升级时先归档旧名单，再在后台补齐中文资料，不阻塞插件启动。"""
        try:
            localized_tmdb = TmdbApi(language="zh-CN")
            for task in self._load_monthly_tasks():
                if task.get("scan_state") != "complete":
                    continue
                candidates = list(task.get("candidates") or [])
                key = self._monthly_scan_key(task)
                if not self._load_monthly_archive(key):
                    self._save_monthly_archive(task, candidates)
                changed = False
                for item in candidates:
                    info = item.get("info") or {}
                    item["original_title"] = item.get("original_title") or info.get("original_title") or ""
                    item["vote_count"] = int(item.get("vote_count") or info.get("vote_count") or 0)
                    item["popularity"] = float(item.get("popularity") or info.get("popularity") or 0)
                    if item.get("localization_version") == 2:
                        continue
                    try:
                        detail = localized_tmdb.get_info(MediaType.MOVIE, int(item["tmdb_id"]))
                        if not detail:
                            continue
                        item["display_title"] = self._chinese_movie_title(detail) or item.get("title")
                        item["original_title"] = detail.get("original_title") or item["original_title"]
                        item["poster_path"] = detail.get("poster_path") or item.get("poster_path")
                        item["info"] = {**(item.get("info") or {}),
                                        "title": item["display_title"],
                                        "poster_path": item["poster_path"]}
                        item["localized"] = True
                        item["localization_version"] = 2
                        changed = True
                    except Exception as err:
                        logger.warning(f"月份电影 {item.get('tmdb_id')} 中文资料暂不可用：{type(err).__name__}")
                candidates.sort(key=lambda item: (
                    -float(item.get("popularity") or 0), -int(item.get("vote_count") or 0),
                    -float(item.get("score") or 0), str(item.get("release_date") or "")))
                if changed or any("popularity" not in item for item in task.get("candidates") or []):
                    self._save_monthly_archive(task, candidates)
                    self._update_monthly_task(str(task["id"]), candidates=candidates, scan_key=key)
        except Exception as err:
            logger.error(f"迁移月份名单归档失败：{type(err).__name__}：{err}")

    def _scan_monthly_task(self, task_id: str) -> None:
        """按首映年或月翻页，使用 TMDB 中文发现结果建立候选名单。"""
        # 同时建立多个任务时排队扫描，避免其余任务被误标成失败。
        self._monthly_scan_lock.acquire()
        task = self._monthly_task(task_id)
        try:
            if not task:
                return
            self._update_monthly_task(task_id, scan_state="running", scan_error="")
            year, month, minimum = int(task["year"]), int(task["month"]), float(task["min_score"])
            min_votes = int(task.get("min_votes") or 0) if month == 0 else 0
            module = ModuleManager().get_running_module("TheMovieDbModule")
            if not module or not getattr(module, "tmdb", None):
                raise RuntimeError("MoviePilot 的 TMDB 模块尚未就绪")
            # MoviePilot 的 TMDB 客户端会在 URL 尾部自动追加 language；请求参数中重复传入
            # language 会使 TMDB 返回 Invalid parameters。独立客户端确保中文资料。
            discover = TmdbApi(language="zh-CN").discover
            results = {}
            pages_done = 0
            examined = 0

            def scan_window(scan_month: int, first: int, last: int, profile: str) -> None:
                nonlocal pages_done, examined
                page = 1
                while page <= (2 if profile == "mainstream" else 500):
                    current = self._monthly_task(task_id)
                    if not current or (current["year"], current["month"], current["min_score"]) != (year, month, minimum):
                        raise RuntimeError("任务设置已改变，取消旧扫描")
                    params = {
                        "sort_by": "popularity.desc" if profile == "mainstream" else "vote_count.desc",
                        "include_adult": False, "include_video": False,
                        "primary_release_date.gte": f"{year:04d}-{scan_month:02d}-{first:02d}",
                        "primary_release_date.lte": f"{year:04d}-{scan_month:02d}-{last:02d}",
                        "page": page,
                    }
                    if profile == "mainstream":
                        params["vote_count.gte"] = max(20, min_votes // 2)
                    else:
                        params["vote_average.gte"] = minimum
                        if min_votes:
                            params["vote_count.gte"] = min_votes
                    try:
                        response = discover._request_obj(
                            discover._urls["movies"], urlencode(params), key=None, call_cached=False)
                    except Exception as err:
                        raise RuntimeError(
                            f"TMDB {year} 年 {scan_month} 月 {first}–{last} 日"
                            f"（{profile}，第 {page} 页）查询失败：{err}") from err
                    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
                        raise RuntimeError(f"TMDB 第 {page} 页未返回有效结果，扫描未完成")
                    raw = response["results"]
                    total_pages = int(response.get("total_pages") or 0)
                    if profile != "mainstream" and total_pages > 500:
                        if first == last:
                            raise RuntimeError(f"{first} 日超过 TMDB 500 页上限，不能保证完整名单")
                        midpoint = (first + last) // 2
                        scan_window(scan_month, first, midpoint, profile)
                        scan_window(scan_month, midpoint + 1, last, profile)
                        return
                    if not raw:
                        break
                    pages_done += 1
                    examined += len(raw)
                    for movie in raw:
                        try:
                            movie_id = int(movie.get("id") or 0)
                            if not movie_id:
                                continue
                            votes = int(movie.get("vote_count") or 0)
                            score = float(movie.get("vote_average") or 0)
                            if profile == "mainstream" and votes < max(20, min_votes // 2):
                                continue
                            if profile != "mainstream" and (score < minimum or votes < min_votes):
                                continue
                            if movie_id in results:
                                if profile not in results[movie_id].setdefault("categories", []):
                                    results[movie_id]["categories"].append(profile)
                                continue
                            info = {key: movie.get(key) for key in (
                                "id", "title", "original_title", "release_date", "vote_average",
                                "vote_count", "original_language", "popularity", "overview",
                                "poster_path", "backdrop_path", "genre_ids")}
                            info["id"] = movie_id
                            info["title"] = info.get("title") or info.get("original_title") or str(movie_id)
                            info["media_type"] = "movie"
                            results[movie_id] = {
                                "tmdb_id": movie_id, "title": info.get("title") or str(movie_id),
                                "display_title": info.get("title") or str(movie_id),
                                "original_title": info.get("original_title") or "",
                                "year": year, "release_date": info["release_date"],
                                "score": float(movie.get("vote_average") or 0),
                                "vote_count": int(movie.get("vote_count") or 0),
                                "popularity": float(movie.get("popularity") or 0),
                                "categories": [profile],
                                "countries": [],
                                "poster_path": info.get("poster_path"), "localized": True,
                                "localization_version": 2,
                                "info": info,
                            }
                        except Exception as err:
                            raise RuntimeError(f"TMDB {movie.get('id')} 候选处理失败：{err}") from err
                    self._update_monthly_task(task_id, scan_progress=f"{scan_month} 月：已读 {pages_done} 页 / {examined} 部，符合评分 {len(results)} 部")
                    if page >= total_pages:
                        break
                    page += 1

            scan_months = range(1, 13) if month == 0 else (month,)
            for scan_month in scan_months:
                last_day = calendar.monthrange(year, scan_month)[1]
                scan_window(scan_month, 1, last_day, "high_quality")
                if month == 0:
                    scan_window(scan_month, 1, last_day, "mainstream")
            candidates = sorted(results.values(), key=lambda item: (
                -item["vote_count"], -item["popularity"], -item["score"],
                item["release_date"] or "", item["tmdb_id"]))
            scanned_at = datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds")
            scan_key = self._save_monthly_archive({**task, "scanned_at": scanned_at}, candidates, count_scan=True)
            self._update_monthly_task(
                task_id, candidates=candidates, scan_state="complete", scan_error="",
                scan_progress=f"已扫描 {pages_done} 页、{examined} 部；符合评分和人数规则 {len(candidates)} 部",
                scanned_at=scanned_at, scan_key=scan_key,
            )
            self._append_plugin_log("年度筛选" if month == 0 else "月份筛选", f"{year} 年{'全年' if month == 0 else str(month) + ' 月'}：{len(candidates)} 部符合；名单已保存")
        except Exception as err:
            self._update_monthly_task(task_id, scan_state="error", scan_error=str(err)[:300])
            self._append_plugin_log("月份筛选", f"{task_id} 扫描失败：{type(err).__name__}：{err}", "error")
        finally:
            self._monthly_scan_lock.release()

    def process_monthly_tasks(self) -> None:
        """旧版本年度自动扫描入口；升级后只允许首页控制已勾选的候选队列。"""
        return

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

    def _rank_candidates(self, items: List[MediaInfo], recency_weight: float = 0.15,
                         scan_history: Optional[dict] = None) -> List[MediaInfo]:
        """先考虑口碑热度，再轻度倾向已上线一段时间且未反复搜空的电影。"""
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
                age_days = 3650
            availability = -0.12 if age_days < 14 else -0.04 if age_days < 45 else 0.04 if age_days < 365 else 0.0
            previous = (scan_history or {}).get(str(media.tmdb_id)) or {}
            if previous.get("status") == "no_resource":
                availability -= 0.06  # 旧的搜空记录过期后仍可重试，只是稍后搜索。
            return (bayesian / 10.0) * 0.55 + popularity * 0.25 + recency * recency_weight + availability + random.random() * 0.05

        return sorted(items, key=score, reverse=True)

    def _candidate_buckets(self, scan_history: Optional[dict] = None) -> Dict[str, List[MediaInfo]]:
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
            "popularity.desc", max(5.5, self._min_score), 30, new_floor.isoformat(), rolling_pages
        )
        recent_source = discover(
            "popularity.desc", max(6.5, self._min_score), 200, recent_floor.isoformat(), random.sample(range(1, 41), 5)
        )
        classic_source = discover(
            "vote_count.desc", max(7.0, self._min_score), 800, "", random.sample(range(1, 101), 6)
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
                if media.type != MediaType.MOVIE or not media.tmdb_id:
                    continue
                if media.tmdb_id in seen or not predicate(media):
                    continue
                seen.add(media.tmdb_id)
                output.append(media)
            return output

        new_movies = unique(new_source, lambda m: bool(
            self._release_date(m) and new_floor <= self._release_date(m) <= today
            and float(getattr(m, "vote_average", 0) or 0) >= self._min_score))
        recent_movies = unique(recent_source, lambda m: bool(
            self._release_date(m) and recent_floor <= self._release_date(m) < new_floor
            and float(getattr(m, "vote_average", 0) or 0) >= max(6.5, self._min_score)
            and self._vote_count(m) >= 100))
        classic_movies = unique(classic_source, lambda m: bool(
            self._release_date(m) and self._release_date(m) < recent_floor
            and float(getattr(m, "vote_average", 0) or 0) >= max(7.0, self._min_score)
            and self._vote_count(m) >= 500))
        random_movies = unique(random_source, lambda m: bool(
            self._release_date(m) and self._release_date(m) <= today
            and float(getattr(m, "vote_average", 0) or 0) >= self._min_score
            and self._vote_count(m) >= self._min_votes))
        return {
            "new": self._rank_candidates(new_movies, recency_weight=0.20, scan_history=scan_history),
            "recent": self._rank_candidates(recent_movies, recency_weight=0.15, scan_history=scan_history),
            "classic": self._rank_candidates(classic_movies, recency_weight=0.02, scan_history=scan_history),
            "random": self._rank_candidates(random_movies, recency_weight=0.08, scan_history=scan_history),
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

    def _scan_scope(self) -> str:
        """站点或 MP 搜索过滤规则变化时，旧的无资源结论立即失效。"""
        rules = {}
        for key in (SystemConfigKey.SearchFilterRuleGroups,
                    SystemConfigKey.UserFilterRuleGroups,
                    SystemConfigKey.CustomFilterRules):
            try:
                rules[key.value] = self.systemconfig.get(key)
            except Exception:
                rules[key.value] = None
        payload = json.dumps({"sites": sorted(self._site_ids), "rules": rules},
                             ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    def _load_scan_cache(self, include_expired: bool = False) -> Dict[str, dict]:
        value = self.get_data(self._scan_cache_key)
        if not isinstance(value, dict):
            return {}
        now = datetime.now()
        result = {}
        scope = self._scan_scope()
        for tmdb_id, item in value.items():
            if not isinstance(item, dict):
                continue
            try:
                checked_at = datetime.fromisoformat(str(item.get("checked_at")))
            except (TypeError, ValueError):
                continue
            status = str(item.get("status"))
            if status in {"no_resource", "error"} and item.get("scope") != scope:
                continue
            try:
                age_days = int(item.get("age_days") if item.get("age_days") is not None else 3650)
            except (TypeError, ValueError):
                age_days = 3650
            ttl = (24 if status == "library" else
                   3 if status == "no_resource" and age_days < 30 else
                   6 if status == "no_resource" and age_days < 365 else
                   18 if status == "no_resource" else
                   0.25 if status == "error" else 0)
            if ((ttl and now - checked_at < timedelta(hours=ttl)) or
                    (include_expired and status == "no_resource" and
                     now - checked_at < timedelta(days=7))):
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
        results = self._search_site_contexts(int(media.tmdb_id))
        return results[0] if results else None

    def _load_pending(self) -> dict:
        value = self.get_data(self._pending_key)
        return value if isinstance(value, dict) else {}

    def _load_download_queue(self) -> List[dict]:
        value = self.get_data(self._download_queue_key)
        return value if isinstance(value, list) else []

    def _remove_queued_movie(self, tmdb_id: Any, reason: str = "已提交下载") -> int:
        """同片已提交或由其他来源处理后清除等候项；调用者须持有 _queue_lock。"""
        movie_id = str(tmdb_id or "")
        if not movie_id:
            return 0
        queue = self._load_download_queue()
        retained = [item for item in queue if str(item.get("tmdb_id") or "") != movie_id]
        removed = len(queue) - len(retained)
        if removed:
            self.save_data(self._download_queue_key, retained)
            self._append_plugin_log("队列去重", f"TMDB {movie_id} {reason}，移除 {removed} 条同片等候任务")
        return removed

    def _load_download_history(self) -> List[dict]:
        value = self.get_data(self._download_history_key)
        return value if isinstance(value, list) else []

    def _history_archive(self):
        connection = sqlite3.connect(str(self.get_data_path() / "download_history.sqlite"), timeout=20)
        connection.execute("CREATE TABLE IF NOT EXISTS history_archive (uid TEXT PRIMARY KEY, submitted_at TEXT, payload TEXT NOT NULL)")
        return connection

    def _save_download_history(self, history: List[dict]) -> None:
        """热数据仍保持 1000 条；淘汰的历史安全归档，供月/年统计使用。"""
        for item in history:
            if not item.get("record_uid"):
                identity = [item.get("submitted_at"), item.get("download_id"),
                            item.get("tmdb_id"), item.get("title")]
                item["record_uid"] = hashlib.sha256(
                    json.dumps(identity, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
        older = history[:-1000]
        if older:
            try:
                with self._history_archive_lock:
                    with closing(self._history_archive()) as db:
                        with db:
                            db.executemany(
                                "INSERT OR REPLACE INTO history_archive(uid, submitted_at, payload) VALUES (?, ?, ?)",
                                [(item["record_uid"], str(item.get("submitted_at") or ""),
                                  json.dumps(item, ensure_ascii=False)) for item in older],
                            )
            except Exception as err:
                # 归档失败时宁可暂时放大 MP 记录，也不丢失淘汰的任务。
                logger.error(f"归档本插件历史下载记录失败，暂不截断：{err}")
                self.save_data(self._download_history_key, history)
                return
        self.save_data(self._download_history_key, history[-1000:])

    def _load_stats_history(self) -> List[dict]:
        active = self._load_download_history()
        try:
            with self._history_archive_lock:
                with closing(self._history_archive()) as db:
                    older = [json.loads(row[0]) for row in db.execute("SELECT payload FROM history_archive")]
            active_ids = {str(item.get("record_uid")) for item in active if item.get("record_uid")}
            return [item for item in older if str(item.get("record_uid")) not in active_ids] + active
        except Exception as err:
            logger.error(f"读取本插件历史归档失败，统计仅含近期记录：{err}")
            return active

    def _save_reconciled_history(self, changed_items: List[dict]) -> None:
        """把后续核验结果写回原记录，归档后仍保留原提交日期。"""
        if not changed_items:
            return
        changes = {str(item.get("record_uid")): item for item in changed_items
                   if item.get("record_uid")}
        if not changes:
            logger.error("核验记录缺少 record_uid，无法安全写回历史")
            return
        active = self._load_download_history()
        active_ids = {str(item.get("record_uid")) for item in active if item.get("record_uid")}
        active_changed = False
        for index, item in enumerate(active):
            updated = changes.get(str(item.get("record_uid")))
            if updated is not None:
                active[index] = updated
                active_changed = True
        if active_changed:
            self._save_download_history(active)
        archived = [item for uid, item in changes.items() if uid not in active_ids]
        if archived:
            try:
                with self._history_archive_lock:
                    with closing(self._history_archive()) as db:
                        with db:
                            db.executemany(
                                "UPDATE history_archive SET payload = ? WHERE uid = ?",
                                [(json.dumps(item, ensure_ascii=False), item["record_uid"])
                                 for item in archived],
                            )
            except Exception as err:
                logger.error(f"写回归档下载状态失败：{err}")

    def _history_total_count(self, active: Optional[List[dict]] = None) -> int:
        active = active if active is not None else self._load_download_history()
        try:
            with self._history_archive_lock:
                with closing(self._history_archive()) as db:
                    archived = int(db.execute("SELECT COUNT(*) FROM history_archive").fetchone()[0])
            return len(active) + archived
        except Exception as err:
            logger.error(f"读取本插件历史总数失败：{err}")
            return len(active)

    def _migrate_legacy_organized_history(self) -> None:
        """迁移旧记录：MP 整理能证明下载完成，但不能证明 Emby 入库。"""
        history = self._load_download_history()
        changed = 0
        for item in history:
            legacy = item.pop("completed_at", None)
            if legacy:
                item.setdefault("organized_at", legacy)
                if not item.get("emby_ingested_at"):
                    item["status"] = "organized"
                changed += 1
            if item.get("organized_at") and not item.get("download_completed_at"):
                item["download_completed_at"] = item["organized_at"]
                item["download_completion_source"] = "transfer"
                changed += 1
        if changed:
            self._save_download_history(history)
            self._append_plugin_log("入库核验", f"已将 {changed} 条旧整理记录改为等待 Emby 核验")

    def _load_plugin_logs(self) -> List[dict]:
        value = self.get_data(self._plugin_logs_key)
        return value if isinstance(value, list) else []

    def _append_plugin_log(self, category: str, message: str, level: str = "info") -> None:
        with self._plugin_log_lock:
            logs = self._load_plugin_logs()
            logs.append({
                "created_at": datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds"),
                "category": str(category or "运行"),
                "message": str(message or ""),
                "level": str(level or "info"),
            })
            self.save_data(self._plugin_logs_key, logs[-1000:])

    def _set_run_status(self, run_id: str, source: str, stage: str,
                        detail: str = "", **counts: Any) -> None:
        status = {
            "run_id": run_id, "source": source, "stage": stage,
            "detail": detail,
            "updated_at": datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds"),
        }
        status.update(counts)
        self.save_data(self._run_status_key, status)

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
                    "media_title": title,
                    "year": year,
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
            self._save_download_history(history)
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

    def _active_download_counts(self, torrents: Optional[List[Any]] = None,
                                history: Optional[List[dict]] = None) -> Tuple[int, int]:
        """按本插件提交记录拆分年度与随机/其他活动任务；未知来源保守计入随机/其他。"""
        try:
            if torrents is None:
                torrents = DownloadChain().downloading() or []
            if history is None:
                history = self._load_stats_history()
            annual_hashes = {str(item.get("download_id") or "").strip().lower()
                             for item in history if item.get("source") == "annual" and item.get("download_id")}
            annual_ids = {str(item.get("tmdb_id")) for item in history
                          if item.get("source") == "annual" and item.get("tmdb_id")}
            annual = 0
            for row in torrents:
                row_hash = str(self._download_value(
                    row, "download_hash", "hash", "torrent_hash", "infohash", "info_hash"
                ) or "").strip().lower()
                if row_hash in annual_hashes or (
                    not row_hash and str(self._download_value(row, "source", "plugin") or "") == self.__class__.__name__
                    and bool(self._mp_active_movie_ids([row]) & annual_ids)
                ):
                    annual += 1
            return annual, len(torrents) - annual
        except Exception as err:
            logger.error(f"无法区分年度与随机下载任务，暂停新增：{err}")
            return self._annual_max_active_downloads, self._max_active_downloads

    @staticmethod
    def _mp_active_movie_ids(torrents: List[Any]) -> set:
        """仅用 MP 下载历史附带的 TMDB ID 去重，不按片名猜测。"""
        movie_ids = set()
        for torrent in torrents:
            media = getattr(torrent, "media", None)
            if isinstance(torrent, dict):
                media = torrent.get("media") or media
            if isinstance(media, dict):
                raw_id = media.get("tmdbid") or media.get("tmdb_id")
            else:
                raw_id = getattr(media, "tmdbid", None) or getattr(media, "tmdb_id", None)
            if raw_id:
                movie_ids.add(str(raw_id))
        return movie_ids

    @staticmethod
    def _download_value(item: Any, *keys: str) -> Any:
        data = item if isinstance(item, dict) else None
        for key in keys:
            if data is not None and data.get(key) is not None:
                return data.get(key)
            value = getattr(item, key, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _format_speed(value: Any) -> str:
        if value in (None, ""):
            return "-"
        if isinstance(value, str):
            return value
        try:
            speed = float(value)
            units = ["B/s", "KB/s", "MB/s", "GB/s"]
            index = 0
            while speed >= 1024 and index < len(units) - 1:
                speed /= 1024
                index += 1
            return f"{speed:.1f} {units[index]}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _localized_download_state(value: Any, progress: float = 0) -> str:
        state = str(value or "").strip().lower()
        names = {
            "downloading": "下载中", "forceddl": "强制下载中", "metadl": "获取种子信息",
            "stalleddl": "等待下载", "queueddl": "排队下载", "checkingdl": "检查文件中",
            "pauseddl": "已暂停", "stoppeddl": "已停止", "allocating": "分配空间中",
            "moving": "移动文件中", "checkingresume": "检查恢复数据",
            "uploading": "做种中", "forcedup": "强制做种中", "stalledup": "等待做种",
            "queuedup": "排队做种", "pausedup": "已暂停做种", "stoppedup": "已停止做种",
            "error": "下载错误", "missingfiles": "文件缺失", "unknown": "状态未知",
        }
        if state in names:
            return names[state]
        if re.search(r"[\u4e00-\u9fff]", str(value or "")):
            return str(value)
        return "已完成" if progress >= 100 else "状态未知"

    def _is_plugin_download_row(self, row: Any, history: List[dict]) -> bool:
        known_hashes = {
            str(item.get("download_id") or "").strip().lower()
            for item in history if item.get("download_id")
        }
        row_hash = str(self._download_value(
            row, "download_hash", "hash", "torrent_hash", "infohash", "info_hash"
        ) or "").strip().lower()
        if row_hash:
            return row_hash in known_hashes
        # 不使用片名/TMDB 模糊匹配，避免把用户手动下载的同名影片算成本插件任务。
        return str(self._download_value(row, "source", "plugin") or "") == self.__class__.__name__

    def _archived_chinese_movie_title(self, tmdb_id: Any, fallback_year: Any = None) -> str:
        """旧下载记录没有中文名时，从已保存的年度片单恢复译名，不访问 TMDB。"""
        if not tmdb_id:
            return ""
        path = self.get_data_path() / "monthly_scans.sqlite"
        if not path.is_file():
            return ""
        try:
            with closing(sqlite3.connect(str(path), timeout=1)) as db:
                row = db.execute("SELECT payload FROM monthly_scan_movies WHERE tmdb_id=? LIMIT 1",
                                 (str(tmdb_id),)).fetchone()
            movie = json.loads(row[0]) if row else {}
            title = str(movie.get("display_title") or movie.get("title") or "").strip()
            if not re.search(r"[\u4e00-\u9fff]", title):
                return ""
            year = str(fallback_year or movie.get("year") or str(movie.get("release_date") or "")[:4]).strip()
            return f"{title} ({year})" if year and not title.endswith(f"({year})") else title
        except (OSError, sqlite3.Error, ValueError, TypeError) as err:
            logger.debug(f"年度片单中文名称读取失败：{type(err).__name__}")
            return ""

    def _active_download_snapshot(self) -> Tuple[int, List[dict]]:
        """仅返回由本插件提交、当前仍在下载的任务实时摘要。"""
        try:
            downloads = DownloadChain().downloading() or []
            history = self._load_download_history()
            records = {str(item.get("download_id") or "").strip().lower(): item
                       for item in history if item.get("download_id")}
            items = []
            for row in downloads:
                if not self._is_plugin_download_row(row, history):
                    continue
                row_hash = str(self._download_value(
                    row, "download_hash", "hash", "torrent_hash", "infohash", "info_hash"
                ) or "").strip().lower()
                record = records.get(row_hash) or {}
                raw_title = str(self._download_value(row, "title", "name", "torrent_name") or "").strip()
                media = self._download_value(row, "media", "media_info")
                media_title = str(self._download_value(media, "title", "title_year") or "").strip() if media else ""
                saved_title = str(record.get("title") or "").strip()
                title = next((candidate for candidate in (saved_title, media_title, raw_title)
                              if re.search(r"[\u4e00-\u9fff]", candidate)),
                             saved_title or media_title or raw_title or "未命名任务")
                if not re.search(r"[\u4e00-\u9fff]", title):
                    title = self._archived_chinese_movie_title(
                        record.get("tmdb_id") or self._download_value(media, "tmdbid", "tmdb_id"),
                        record.get("year")) or title
                progress = self._download_value(row, "progress", "percent", "completion") or 0
                try:
                    progress = round(float(progress), 1)
                except (TypeError, ValueError):
                    progress = 0
                if 0 < progress <= 1:
                    progress = round(progress * 100, 1)
                speed = self._download_value(
                    row, "dlspeed", "download_speed", "downloadSpeed", "speed"
                )
                items.append({
                    "title": str(title),
                    "source": record.get("source") or "legacy",
                    "progress": min(max(progress, 0), 100),
                    "speed": self._format_speed(speed),
                    "state": self._localized_download_state(
                        self._download_value(row, "state", "status"), progress),
                    "eta": str(self._download_value(row, "eta", "remaining_time") or "-"),
                })
            return len(items), items
        except Exception as err:
            logger.error(f"读取 MoviePilot 正在下载详情失败：{err}")
            return 0, []

    def _enqueue_download(self, media: MediaInfo, context: Context,
                          channel: Any = None, userid: Any = None,
                          source: str = "random") -> bool:
        queue = self._load_download_queue()
        tmdb_id = str(media.tmdb_id)
        if any(str(item.get("tmdb_id")) == tmdb_id for item in queue):
            logger.info(f"电影已在顺序下载队列，忽略重复入队和重复通知：{media.title_year}")
            return False
        try:
            if tmdb_id in self._mp_active_movie_ids(DownloadChain().downloading() or []):
                logger.info(f"MoviePilot 已在下载，电影不再入队：{media.title_year}")
                return False
        except Exception as err:
            logger.warning(f"暂不能核对 MoviePilot 下载，保守跳过入队：{type(err).__name__}")
            return False
        queue.append({
            "key": hashlib.sha1(f"{tmdb_id}|{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            "tmdb_id": media.tmdb_id,
            "title": media.title_year,
            "source": source,
            "torrent_identity": self._torrent_identity(context),
            "channel": channel.value if hasattr(channel, "value") else channel,
            "userid": userid,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "attempts": 0,
        })
        self.save_data(self._download_queue_key, queue[-2000:])
        logger.info(f"已加入顺序下载队列：{media.title_year}，当前等候 {len(queue)} 部")
        return True

    def _record_download(self, media: MediaInfo, download_id: Any,
                         source: str = "random", display_title: str = "") -> None:
        history = self._load_download_history()
        history.append({
            "record_uid": secrets.token_hex(16),
            "tmdb_id": media.tmdb_id,
            "title": display_title or media.title_year,
            "media_title": media.title,
            "year": media.year,
            "download_id": str(download_id or ""),
            "source": source,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._save_download_history(history)
        self._append_plugin_log("年度下载" if source == "annual" else "提交下载",
                                f"{media.title_year} 已提交到 MoviePilot，任务 {download_id}")

    def reconcile_download_completions(self) -> int:
        """以下载器的完成记录为准；已移除种子的任务由成功整理记录兜底。"""
        history = self._load_stats_history()
        timezone = pytz.timezone(settings.TZ)
        now = datetime.now(tz=timezone)
        recent = now - timedelta(days=2)
        candidates = [item for item in history if item.get("download_id") and (
            not item.get("download_completed_at") or (
                item.get("download_completion_source") == "transfer" and
                (self._parse_history_time(item.get("submitted_at"), timezone) or now) >= recent
            )
        )]
        if not candidates:
            return 0
        hashes = list({str(item["download_id"]).strip().lower() for item in candidates})
        completed = {}
        # qB 原始接口提供 completion_on，避免午夜附近的任务被归入错误日期。
        try:
            module = ModuleManager().get_running_module("QbittorrentModule")
            for server in (module.get_instances() if module else {}).values():
                for torrent in server.get_completed_torrents(ids=hashes) or []:
                    torrent_hash = str(torrent.get("hash") or "").strip().lower()
                    if not torrent_hash:
                        continue
                    try:
                        finished = int(torrent.get("completion_on") or 0)
                    except (TypeError, ValueError):
                        finished = 0
                    completed[torrent_hash] = (
                        datetime.fromtimestamp(finished, tz=timezone).isoformat(timespec="seconds")
                        if finished > 0 else now.isoformat(timespec="seconds"),
                        "qb" if finished > 0 else "observed",
                    )
        except Exception as err:
            logger.warning(f"读取 qB 已完成任务失败：{type(err).__name__}")
        # 其他下载器没有统一的完成时间字段；仅在真实进度为 100% 时记录检测时间。
        unresolved = [torrent_hash for torrent_hash in hashes if torrent_hash not in completed]
        if unresolved:
            try:
                for torrent in DownloadChain().list_torrents(
                    hashs=unresolved, include_all_tags=True
                ) or []:
                    torrent_hash = str(getattr(torrent, "hash", "") or "").strip().lower()
                    progress = float(getattr(torrent, "progress", 0) or 0)
                    state = str(getattr(torrent, "state", "") or "").lower()
                    if torrent_hash and state == "completed" and (progress >= 99.9 or progress == 1):
                        completed[torrent_hash] = (now.isoformat(timespec="seconds"), "observed")
            except Exception as err:
                logger.warning(f"读取下载器完成状态失败：{type(err).__name__}")
        if not completed:
            return 0
        # 网络请求期间可能新增下载，必须在保存前重新读取，避免覆盖新记录。
        history = self._load_stats_history()
        changed = 0
        changed_items = []
        for item in history:
            result = completed.get(str(item.get("download_id") or "").strip().lower())
            if not result:
                continue
            finished_at, source = result
            if item.get("download_completed_at") and source != "qb":
                continue
            if item.get("download_completed_at") == finished_at and item.get("download_completion_source") == source:
                continue
            item["download_completed_at"] = finished_at
            item["download_completion_source"] = source
            changed += 1
            changed_items.append(item)
        if changed:
            self._save_reconciled_history(changed_items)
            logger.info(f"插件下载完成核验：更新 {changed} 部")
        return changed

    def reconcile_mp_transfer_results(self, all_pending: bool = False) -> int:
        """按插件提交的种子 hash 核对 MP 整理成功/失败记录。"""
        history = self._load_stats_history()
        timezone = pytz.timezone(settings.TZ)
        cutoff = datetime.now(tz=timezone) - timedelta(days=3)
        candidates = [item for item in history if item.get("download_id") and not item.get("organized_at")
                      and (all_pending or (self._parse_history_time(
                          item.get("download_completed_at") or item.get("submitted_at"), timezone
                      ) or cutoff) >= cutoff)]
        if not candidates:
            return 0
        oper = TransferHistoryOper()
        results = {}
        for torrent_hash in {str(item["download_id"]).strip().lower() for item in candidates}:
            try:
                rows = oper.list_by_hash(torrent_hash) or []
                successful = [row for row in rows if getattr(row, "status", None) is True]
                failed = [row for row in rows if getattr(row, "status", None) is False]
                if successful:
                    results[torrent_hash] = ("success", min(successful, key=lambda row: str(getattr(row, "date", "") or "")))
                elif failed:
                    results[torrent_hash] = ("failed", max(failed, key=lambda row: str(getattr(row, "date", "") or "")))
            except Exception as err:
                logger.warning(f"查询 MoviePilot 整理记录失败：{torrent_hash[:12]}：{err}")
        if not results:
            return 0
        # 查询期间可能新增记录，避免覆盖新的插件下载历史。
        history = self._load_stats_history()
        changed = 0
        changed_items = []
        for item in history:
            result = results.get(str(item.get("download_id") or "").strip().lower())
            if not result or item.get("organized_at"):
                continue
            outcome, row = result
            timestamp = self._parse_history_time(getattr(row, "date", None), timezone)
            if outcome == "success":
                if not timestamp:
                    continue
                title = str(getattr(row, "title", "") or "").strip()
                year = str(getattr(row, "year", "") or "").strip()
                if title:
                    item["title"] = f"{title} ({year})" if year and year not in title else title
                    item["media_title"] = title
                    item["year"] = year
                item["organized_at"] = timestamp.isoformat(timespec="seconds")
                item.pop("organize_failed_at", None)
                item.pop("organize_error", None)
                if not item.get("download_completed_at"):
                    item["download_completed_at"] = item["organized_at"]
                    item["download_completion_source"] = "transfer"
                if not item.get("emby_ingested_at"):
                    item["status"] = "organized"
                changed += 1
                changed_items.append(item)
            else:
                failed_at = (timestamp or datetime.now(tz=timezone)).isoformat(timespec="seconds")
                reason = str(getattr(row, "errmsg", "") or "").strip()[:300]
                if item.get("organize_failed_at") == failed_at and item.get("organize_error") == reason:
                    continue
                item["organize_failed_at"] = failed_at
                item["organize_error"] = reason
                item["status"] = "organize_failed"
                changed += 1
                changed_items.append(item)
        if changed:
            self._save_reconciled_history(changed_items)
            logger.info(f"插件电影 MoviePilot 整理结果核对：更新 {changed} 条")
        return changed

    def _submit_download(self, media: MediaInfo, context: Context,
                         channel: Any = None, userid: Any = None,
                         username: str = "智能下载影视资源_惹咪之北",
                         origin: str = "random", display_title: str = "") -> Tuple[bool, Optional[str]]:
        if self._disk_guard_blocks_new():
            return False, "硬盘保护中，候选已保留等候，不向 qB 添加新种子"
        try:
            active_ids = self._mp_active_movie_ids(DownloadChain().downloading() or [])
        except Exception as err:
            return False, f"暂不能核对 MoviePilot 正在下载任务：{type(err).__name__}"
        if str(media.tmdb_id or "") in active_ids:
            self._remove_queued_movie(media.tmdb_id, "MoviePilot 已在下载")
            return False, "该影片已由 MoviePilot 下载，未重复提交"
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
        self._record_download(media, download_id, source=origin, display_title=display_title)
        self._remove_queued_movie(media.tmdb_id)
        return True, None

    def process_download_queue(self) -> None:
        """每分钟清理重复候选，并分别按随机与年度的独立空位补位。"""
        if not self._enabled:
            return
        if self._disk_guard_blocks_new():
            queue_count = len(self._load_download_queue())
            if queue_count:
                logger.info(f"硬盘保护中：保留 {queue_count} 部 MoviePilot 候选等候，不添加新种子")
            return
        if not self._queue_lock.acquire(blocking=False):
            return
        try:
            queue = self._load_download_queue()
            if not queue:
                return
            try:
                active_torrents = DownloadChain().downloading() or []
            except Exception as err:
                logger.warning(f"等候队列暂不能核对 MoviePilot 下载：{type(err).__name__}")
                return
            active_movie_ids = self._mp_active_movie_ids(active_torrents)
            history = self._load_stats_history()
            submitted_movie_ids = {str(row.get("tmdb_id")) for row in history
                                   if row.get("tmdb_id")}
            annual_active, non_annual_active = self._active_download_counts(active_torrents, history)
            annual_slots = max(0, self._annual_max_active_downloads - annual_active)
            non_annual_slots = max(0, self._max_active_downloads - non_annual_active)
            # 有下载空位时强制更新 Emby 索引，避免其他来源刚入库的影片被重复提交。
            library = self._library_snapshot_for_scan(force=annual_slots > 0 or non_annual_slots > 0)
            emby_ids = set(library["tmdb_ids"]) if library else set()
            retained = [item for item in queue if str(item.get("tmdb_id") or "")
                        not in (emby_ids | active_movie_ids | submitted_movie_ids)]
            if len(retained) != len(queue):
                self.save_data(self._download_queue_key, retained)
                self._append_plugin_log("队列去重", f"Emby 已入库或 MoviePilot 已有下载记录/正在下载，移除 {len(queue) - len(retained)} 条同片等候任务")
                queue = retained
            if not queue:
                return
            if annual_slots <= 0 and non_annual_slots <= 0:
                logger.info(f"下载队列等待中：随机/其他 {non_annual_active}/{self._max_active_downloads}，"
                            f"年度 {annual_active}/{self._annual_max_active_downloads}，等候 {len(queue)}")
                return
            if not library:
                logger.warning("等候队列暂停补位：Emby 目录暂不可核对，避免重复下载")
                return

            remaining = list(queue)
            submitted = 0
            annual_submitted = 0
            non_annual_submitted = 0
            annual_attempts = 0
            non_annual_blocked = False
            # 只处理本次进入函数时已有的项目，失败项留到下一分钟，防止同轮反复重试。
            for item in queue[:]:
                is_annual = item.get("source") == "annual"
                if is_annual and annual_submitted >= annual_slots:
                    continue
                if not is_annual and (non_annual_blocked or non_annual_submitted >= non_annual_slots):
                    continue
                if is_annual and (not self._annual_dispatch_enabled or annual_submitted >= self._annual_dispatch_count
                                  or annual_attempts >= self._annual_dispatch_count * 2):
                    continue
                if is_annual and item.get("last_attempt"):
                    try:
                        last_attempt = datetime.fromisoformat(str(item["last_attempt"]))
                        retry_minutes = min(15 * 2 ** min(max(int(item.get("attempts") or 1) - 1, 0), 4), 240)
                        if datetime.now(tz=last_attempt.tzinfo) - last_attempt < timedelta(minutes=retry_minutes):
                            continue
                    except (TypeError, ValueError, OverflowError):
                        pass
                if not any(row.get("key") == item.get("key") for row in remaining):
                    continue
                if is_annual:
                    annual_attempts += 1
                try:
                    if is_annual:
                        self._append_plugin_log("年度下载", f"正在查询 {item.get('title')} 的 PT 资源（本次补位 {annual_attempts}/{self._annual_dispatch_count * 2}）")
                    results = self._search_site_contexts(int(item["tmdb_id"]))
                    context = next(
                        (ctx for ctx in results if self._torrent_identity(ctx) == item.get("torrent_identity")),
                        results[0] if results else None,
                    )
                    if not context:
                        if item.get("source") == "annual":
                            remaining = [row for row in self._load_download_queue()
                                         if row.get("key") != item.get("key")]
                            self.save_data(self._download_queue_key, remaining)
                            self._append_plugin_log("年度下载", f"{item.get('title')}：PT 站没有符合 MoviePilot 规则的资源，已从候选队列移除")
                            continue
                        raise RuntimeError("所选站点中已找不到可下载资源")
                    media = context.media_info
                    ok, error = self._submit_download(
                        media, context, channel=None, userid=item.get("userid"),
                        username="智能电影推荐队列",
                        origin=item.get("source") or "random",
                        display_title=str(item.get("title") or ""),
                    )
                    if not ok:
                        raise RuntimeError(error or "提交失败")
                    # _submit_download 已从共享队列移除同片任务；不能再用进入函数时的旧快照覆盖。
                    remaining = self._load_download_queue()
                    submitted += 1
                    if is_annual:
                        annual_submitted += 1
                    else:
                        non_annual_submitted += 1
                    logger.info(f"顺序下载队列已提交：{item.get('title')}")
                except Exception as err:
                    # 提交时如发现 MP 刚开始下载，同片等候项已被清除，不得用旧快照写回来。
                    remaining = self._load_download_queue()
                    if not any(row.get("key") == item.get("key") for row in remaining):
                        continue
                    for row in remaining:
                        if row.get("key") == item.get("key"):
                            row["attempts"] = int(row.get("attempts") or 0) + 1
                            row["last_error"] = str(err)[:300]
                            row["last_attempt"] = datetime.now().isoformat(timespec="seconds")
                            break
                    # 后续候选若成功，会重新读取队列并保存；先落盘以免覆盖本片的重试状态。
                    self.save_data(self._download_queue_key, remaining)
                    logger.error(f"顺序下载队列提交失败：{item.get('title')}：{err}")
                    if is_annual:
                        self._append_plugin_log("年度下载", f"{item.get('title')} 提交失败：{err}", "error")
                    # 同一来源内保持原有语义，但一边失败不能阻止另一边补位。
                    if not is_annual:
                        non_annual_blocked = True
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
        if self._telegram_admins_override:
            raw = self._telegram_admins_override.replace(";", ",")
            return {self._normalize_admin(item) for item in raw.split(",") if item.strip()}
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

    @staticmethod
    def _is_telegram_token(value: str) -> bool:
        parts = str(value or "").split(":", 1)
        return len(parts) == 2 and parts[0].isdigit() and bool(parts[1])

    def _stop_custom_telegram_bot(self) -> None:
        with self._custom_telegram_lock:
            bot = self._custom_telegram_bot
            self._custom_telegram_bot = None
            self._custom_telegram_token = ""
            self._custom_telegram_thread = None
            if bot:
                try:
                    bot.stop_polling()
                except Exception:
                    pass

    def _configure_custom_telegram_bot(self) -> None:
        """独立 Token 自行接收按钮；MoviePilot 已配置的 Token 复用原实例。"""
        token = self._telegram_source if self._is_telegram_token(self._telegram_source) else ""
        module = self._telegram_module()
        if token and module:
            for conf in module.get_configs().values():
                if str((conf.config or {}).get("TELEGRAM_TOKEN") or "") == token:
                    token = ""
                    break
        with self._custom_telegram_lock:
            if token and self._custom_telegram_bot and self._custom_telegram_token == token:
                return
        self._stop_custom_telegram_bot()
        if not token:
            return
        try:
            bot = TeleBot(token, threaded=False)

            @bot.callback_query_handler(
                func=lambda call: str(call.data or "").startswith(
                    f"[PLUGIN]{self.__class__.__name__}|"
                )
            )
            def handle_plugin_button(call):
                if self._custom_telegram_bot is not bot:
                    return
                try:
                    bot.answer_callback_query(call.id)
                    self.message_action(SimpleNamespace(event_data={
                        "plugin_id": self.__class__.__name__,
                        "text": str(call.data).split("|", 1)[1],
                        "channel": MessageChannel.Telegram,
                        "source": "__custom_telegram__",
                        "userid": str(call.from_user.id),
                        "username": getattr(call.from_user, "username", None),
                        "original_message_id": call.message.message_id,
                        "original_chat_id": str(call.message.chat.id),
                    }))
                except Exception as err:
                    logger.error(f"处理插件专用 Telegram 按钮失败：{err}")

            @bot.message_handler(commands=["start", "smartmovie", "help"])
            def handle_plugin_command(message):
                if self._custom_telegram_bot is not bot:
                    return
                user = getattr(message, "from_user", None)
                chat_id = str(getattr(message.chat, "id", ""))
                userid = getattr(user, "id", None)
                username = getattr(user, "username", None)
                command = str(getattr(message, "text", "") or "").split(maxsplit=1)[0]
                command = command.split("@", 1)[0].lower()
                if command == "/help":
                    self._show_telegram_help(chat_id, userid, username)
                else:
                    self._show_telegram_menu(chat_id, userid, username)

            # 独立机器人专供本插件使用；把命令注册到 Telegram 原生菜单，
            # 首次点 Open 发出的 /start 也能直接打开统计菜单。
            try:
                bot.set_my_commands([
                    telegram_types.BotCommand("start", "打开智能电影管理菜单"),
                    telegram_types.BotCommand("smartmovie", "查看下载统计和当前状态"),
                    telegram_types.BotCommand("help", "查看中文命令说明"),
                ])
                bot.set_chat_menu_button(menu_button=telegram_types.MenuButtonCommands())
            except Exception as err:
                # 命令列表设置失败也不能妨碍机器人接收 /start 和 /help。
                logger.warning(f"Telegram 命令菜单注册失败，继续启动消息接收：{err}")

            def poll():
                try:
                    bot.infinity_polling(skip_pending=False, long_polling_timeout=20)
                except Exception as err:
                    logger.error(f"插件专用 Telegram 接收服务停止：{err}")

            thread = threading.Thread(target=poll, daemon=True, name="SmartMoviePushTelegram")
            with self._custom_telegram_lock:
                self._custom_telegram_bot = bot
                self._custom_telegram_token = token
                self._custom_telegram_thread = thread
            thread.start()
        except Exception as err:
            logger.error(f"启动插件专用 Telegram 机器人失败：{err}")

    def _telegram_delivery_warning(self) -> str:
        target = self._telegram_target()
        if not target:
            return "尚未设置通知频道 Chat ID"
        if self._is_telegram_token(self._telegram_source) and self._custom_telegram_bot:
            try:
                bot = self._custom_telegram_bot
                member = bot.get_chat_member(target, bot.get_me().id)
                if member.status not in {"administrator", "creator", "member"}:
                    return "机器人没有加入目标频道"
                if member.status == "administrator" and getattr(member, "can_post_messages", True) is False:
                    return "机器人没有频道发布权限"
                return ""
            except Exception:
                return "机器人无法访问目标频道，请先将机器人加入频道并授予发布权限"
        if self._telegram_source and not self._is_telegram_token(self._telegram_source):
            module = self._telegram_module()
            if not module or self._telegram_source not in module.get_configs():
                return "机器人实例名不存在"
        return ""

    def _send_with_custom_bot(self, bot: TeleBot, **kwargs) -> Optional[dict]:
        target = str(kwargs.get("userid") or self._telegram_target() or "")
        if not target:
            return None
        title = str(kwargs.get("title") or "")
        text = str(kwargs.get("text") or "")
        is_html = kwargs.get("parse_mode") == "HTML"
        caption = f"<b>{html.escape(title)}</b>\n{text if is_html else html.escape(text)}".strip()
        link = kwargs.get("link")
        if link:
            caption += f'\n<a href="{html.escape(str(link), quote=True)}">查看详情</a>'
        markup = None
        if kwargs.get("buttons"):
            markup = telegram_types.InlineKeyboardMarkup()
            for row in kwargs["buttons"]:
                markup.row(*[
                    telegram_types.InlineKeyboardButton(
                        text=str(button["text"]), callback_data=str(button["callback_data"])
                    ) for button in row
                ])
        try:
            image = kwargs.get("image")
            if image and len(caption) <= 1024:
                try:
                    sent = bot.send_photo(target, image, caption=caption,
                                          parse_mode="HTML", reply_markup=markup)
                except Exception:
                    sent = bot.send_message(target, caption, parse_mode="HTML",
                                            reply_markup=markup, disable_web_page_preview=True)
            else:
                sent = bot.send_message(target, caption, parse_mode="HTML",
                                        reply_markup=markup, disable_web_page_preview=True)
            return {"success": True, "message_id": sent.message_id, "chat_id": sent.chat.id}
        except Exception as err:
            logger.error(f"插件专用 Telegram 发送失败：{err}")
            return None

    def _send_telegram_direct(self, **kwargs) -> Tuple[Optional[str], Optional[dict]]:
        """直接调用现有 Telegram 实例，以便保存消息 ID 供午夜精确撤回。"""
        module = self._telegram_module()
        if self._is_telegram_token(self._telegram_source):
            if self._custom_telegram_bot:
                result = self._send_with_custom_bot(self._custom_telegram_bot, **kwargs)
                return ("__custom_telegram__", result) if result else (None, None)
            if module:
                for source, conf in module.get_configs().items():
                    if str((conf.config or {}).get("TELEGRAM_TOKEN") or "") == self._telegram_source:
                        client = module.get_instance(conf.name)
                        result = client.send_msg(**kwargs) if client else None
                        return (source, result) if result and result.get("success") else (None, None)
            return None, None
        if not module:
            return None, None
        configs = module.get_configs()
        if self._telegram_source:
            conf = configs.get(self._telegram_source)
            candidates = [(self._telegram_source, conf)] if conf else []
        else:
            candidates = list(configs.items())
        for source, conf in candidates:
            if not conf:
                continue
            client = module.get_instance(conf.name)
            if not client:
                continue
            result = client.send_msg(**kwargs)
            if result and result.get("success"):
                return source, result
        return None, None

    def _delete_telegram_message(self, source: Optional[str], message_id: Any, chat_id: Any) -> bool:
        if source == "__custom_telegram__" and self._custom_telegram_bot and message_id:
            try:
                return bool(self._custom_telegram_bot.delete_message(chat_id, int(message_id)))
            except Exception as err:
                logger.warning(f"删除插件专用 Telegram 消息失败：{err}")
                return False
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

    def _delete_download_messages(self, tmdb_id: Any) -> Tuple[int, int]:
        """删除指定影片仍保留在 Telegram 中的全部插件推送消息。"""
        target = str(tmdb_id or "")
        if not target:
            return 0, 0
        retained = []
        deleted = 0
        failed = 0
        for item in self._load_daily_messages():
            if str(item.get("tmdb_id") or "") != target:
                retained.append(item)
                continue
            if self._delete_telegram_message(
                source=item.get("source"),
                message_id=item.get("message_id"),
                chat_id=item.get("chat_id"),
            ):
                deleted += 1
            else:
                # 删除失败时保留记录，午夜清理会再次尝试。
                retained.append(item)
                failed += 1
        self.save_data(self._daily_messages_key, retained)
        return deleted, failed

    @eventmanager.register(EventType.TransferComplete)
    def transfer_complete(self, event: Event):
        """仅记录 MoviePilot 整理完成；Emby 入库由定时核验确认。"""
        data = event.event_data or {}
        media = data.get("mediainfo")
        download_hash = str(data.get("download_hash") or "").strip().lower()
        if not download_hash:
            return
        history = self._load_download_history()
        history_item = next(
            (item for item in reversed(history)
             if str(item.get("download_id") or "").strip().lower() == download_hash),
            None,
        )
        # TransferComplete 是全局事件；哈希不属于插件时绝不能统计或清理消息。
        if not history_item:
            return
        tmdb_id = history_item.get("tmdb_id") or (getattr(media, "tmdb_id", None) if media else None)
        title = getattr(media, "title_year", None) if media else None
        if title:
            history_item["title"] = str(title)
        if media:
            history_item["media_title"] = str(getattr(media, "title", "") or "")
            history_item["year"] = str(getattr(media, "year", "") or "")
        history_item["organized_at"] = datetime.now(
            tz=pytz.timezone(settings.TZ)
        ).isoformat(timespec="seconds")
        history_item.pop("organize_failed_at", None)
        history_item.pop("organize_error", None)
        if not history_item.get("download_completed_at"):
            history_item["download_completed_at"] = history_item["organized_at"]
            history_item["download_completion_source"] = "transfer"
        history_item["status"] = "organized"
        self._save_download_history(history)
        self._append_plugin_log("整理完成", f"{history_item.get('title') or f'TMDB {tmdb_id}'} 等待 Emby 入库")
        deleted, failed = self._delete_download_messages(tmdb_id)
        if deleted or failed:
            logger.info(
                f"影片整理完成，清理 Telegram 推送：TMDB {tmdb_id}，"
                f"已删除 {deleted} 条，待重试 {failed} 条"
            )

    @staticmethod
    def _emby_media_info(item: dict) -> Optional[MediaInfo]:
        title = str(item.get("media_title") or "").strip()
        year = str(item.get("year") or "").strip()
        if not title:
            display = str(item.get("title") or "").strip()
            match = re.fullmatch(r"(.+?)\s*\((\d{4})\)", display)
            title = match.group(1).strip() if match else display
            year = year or (match.group(2) if match else "")
        if not title or title.startswith("TMDB "):
            return None
        try:
            tmdb_id = int(item.get("tmdb_id"))
        except (TypeError, ValueError):
            tmdb_id = None
        return MediaInfo(type=MediaType.MOVIE, title=title, year=year,
                         tmdb_id=tmdb_id)

    @staticmethod
    def _emby_index_for_server(config: dict) -> Tuple[dict, dict]:
        """一次分页读取 Emby 电影索引；避免逐部查询造成午夜统计积压。"""
        host = str(config.get("host") or "").rstrip("/")
        apikey = str(config.get("apikey") or "")
        if not host or not apikey:
            raise ValueError("Emby 地址或 API Key 缺失")
        by_tmdb = {}
        by_title_year = {}
        start = 0
        page_size = 10000
        with requests.Session() as client:
            while True:
                response = client.get(
                    f"{host}/emby/Items",
                    params={
                        "IncludeItemTypes": "Movie",
                        "Recursive": "true",
                        "Fields": "ProviderIds,ProductionYear",
                        "StartIndex": start,
                        "Limit": page_size,
                        "api_key": apikey,
                    },
                    timeout=(5, 45),
                )
                response.raise_for_status()
                payload = response.json()
                movies = payload.get("Items") or []
                for movie in movies:
                    if not isinstance(movie, dict) or not movie.get("Id"):
                        continue
                    provider_ids = movie.get("ProviderIds") or {}
                    tmdb_id = next(
                        (str(value) for key, value in provider_ids.items()
                         if str(key).lower() == "tmdb" and value), ""
                    )
                    if tmdb_id:
                        by_tmdb.setdefault(tmdb_id, movie)
                    title = " ".join(str(movie.get("Name") or "").casefold().split())
                    year = str(movie.get("ProductionYear") or "")
                    if title and year:
                        by_title_year.setdefault((title, year), movie)
                start += len(movies)
                total = int(payload.get("TotalRecordCount") or 0)
                if not movies or start >= total:
                    break
        return by_tmdb, by_title_year

    def _remember_library_snapshot(self, indexes: list, server_names: list) -> None:
        """只保存所有已启用 Emby 均成功读取的完整快照；不依赖同步中的 MP 表。"""
        tmdb_ids = set()
        title_years = set()
        for _, by_tmdb, by_title_year in indexes:
            tmdb_ids.update(by_tmdb)
            title_years.update(by_title_year)
        if not tmdb_ids and not title_years:
            return
        with self._library_snapshot_lock:
            self._library_snapshot = {
                "servers": tuple(sorted(str(name) for name in server_names)),
                "tmdb_ids": tmdb_ids,
                "title_years": title_years,
            }
            self._library_snapshot_time = time.monotonic()

    def _library_snapshot_for_scan(self, force: bool = False) -> Optional[dict]:
        """每轮复用最近的 Emby 全量索引；失败时回退到 MP 原有逐部核验。"""
        module = ModuleManager().get_running_module("EmbyModule")
        configs = module.get_configs() if module else {}
        servers = [(name, conf) for name, conf in (configs or {}).items()
                   if getattr(conf, "enabled", False) and getattr(conf, "type", "") == "emby"]
        names = tuple(sorted(str(name) for name, _ in servers))
        if not servers:
            return None
        with self._library_snapshot_lock:
            if (not force and self._library_snapshot
                    and self._library_snapshot.get("servers") == names
                    and time.monotonic() - self._library_snapshot_time < 300):
                return self._library_snapshot
        indexes = []
        for name, conf in servers:
            try:
                indexes.append((name, *self._emby_index_for_server(conf.config or {})))
            except Exception as err:
                logger.warning(f"预取 Emby 电影索引失败：{name}：{type(err).__name__}；回退逐部核验")
                return None
        if not any(by_tmdb or by_title_year for _, by_tmdb, by_title_year in indexes):
            logger.warning("Emby 返回空电影目录，本轮回退 MoviePilot 逐部核验")
            return None
        self._remember_library_snapshot(indexes, list(names))
        with self._library_snapshot_lock:
            return self._library_snapshot if self._library_snapshot_time and time.monotonic() - self._library_snapshot_time < 300 else None

    @staticmethod
    def _snapshot_has_movie(snapshot: dict, media: MediaInfo) -> bool:
        tmdb_id = str(media.tmdb_id or "")
        if tmdb_id and tmdb_id in snapshot["tmdb_ids"]:
            return True
        # 有 TMDB ID 时不按片名兜底，避免翻拍或同名电影误判。
        if tmdb_id:
            return False
        title = " ".join(str(media.title or "").casefold().split())
        year = str(media.year or "")
        return bool(title and year and (title, year) in snapshot["title_years"])

    def verify_emby_ingestion(self) -> int:
        """每轮重查 Emby 实际目录；已删除的条目不得继续算作入库。"""
        self._last_emby_check_ok = False
        history = self._load_stats_history()
        if not any(item.get("download_completed_at") for item in history):
            self._last_emby_check_ok = True
            return 0
        module = ModuleManager().get_running_module("EmbyModule")
        configs = module.get_configs() if module else {}
        servers = [(name, conf) for name, conf in (configs or {}).items()
                   if getattr(conf, "enabled", False) and getattr(conf, "type", "") == "emby"]
        if not servers:
            logger.warning("Emby 入库核验暂不可用：没有已启用的 Emby 服务器")
            return 0
        indexes = []
        for name, conf in servers:
            try:
                by_tmdb, by_title_year = self._emby_index_for_server(conf.config or {})
                indexes.append((name, by_tmdb, by_title_year))
            except Exception as err:
                # 不把含 API Key 的请求地址写进日志。
                logger.warning(f"读取 Emby 电影索引失败：{name}：{type(err).__name__}")
        if not indexes:
            return 0
        if all(not by_tmdb and not by_title_year for _, by_tmdb, by_title_year in indexes) and any(
            item.get("emby_ingested_at") for item in history
        ):
            logger.warning("Emby 返回空电影目录，但插件此前已有入库记录；本轮不清除标记也不发送日报")
            return 0
        all_servers_loaded = len(indexes) == len(servers)
        self._last_emby_check_ok = all_servers_loaded
        if all_servers_loaded:
            self._remember_library_snapshot(indexes, [name for name, _ in servers])
        # 索引请求期间可能新增或更新下载记录，避免用旧快照覆盖它们。
        history = self._load_stats_history()
        now = datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds")
        found = 0
        checked = 0
        changed = False
        changed_items = []
        for item in history:
            if not item.get("download_completed_at"):
                continue
            checked += 1
            item["last_emby_check_at"] = now
            tmdb_id = str(item.get("tmdb_id") or "")
            media = self._emby_media_info(item) if not tmdb_id else None
            fallback = (
                (" ".join(media.title.casefold().split()), str(media.year or ""))
                if media and media.year else None
            )
            for server, by_tmdb, by_title_year in indexes:
                movie = by_tmdb.get(tmdb_id) if tmdb_id else by_title_year.get(fallback)
                if not movie:
                    continue
                if not item.get("emby_ingested_at"):
                    item["emby_ingested_at"] = now
                    found += 1
                    changed = True
                    changed_items.append(item)
                    self._append_plugin_log("Emby 已入库", f"{item.get('title')} 已在 {server} 核实")
                item["status"] = "emby_ingested"
                item["emby_server"] = server
                item["emby_item_id"] = str(movie["Id"])
                break
            else:
                # 还有服务器未响应时不能认定条目已经从全部 Emby 消失。
                if all_servers_loaded and item.pop("emby_ingested_at", None):
                    item.pop("emby_server", None)
                    item.pop("emby_item_id", None)
                    item["status"] = "organized" if item.get("organized_at") else "download_completed"
                    changed = True
                    changed_items.append(item)
                    self._append_plugin_log("Emby 已移除", f"{item.get('title')} 当前不在 Emby，已取消入库标记", "warning")
        if changed:
            self._save_reconciled_history(changed_items)
        logger.info(f"Emby 批量核验完成：已查 {checked} 部，本轮新增确认 {found} 部")
        return found

    @staticmethod
    def _parse_history_time(value: Any, timezone) -> Optional[datetime]:
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                return timezone.localize(parsed)
            return parsed.astimezone(timezone)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_daily_movie_rows(items: List[dict], start_index: int = 1) -> str:
        if not items:
            return "本日没有本插件提交下载的电影。"
        rows = []
        for index, item in enumerate(items, start_index):
            movie_title = item.get("title") or f"TMDB {item.get('tmdb_id', '')}"
            if item.get("emby_ingested_at"):
                stage = ""
            elif item.get("organized_at"):
                stage = "🔴 待入库"
            elif item.get("organize_failed_at"):
                stage = "🔴 整理失败"
            elif item.get("download_completed_at"):
                stage = "🟡 待整理"
            else:
                stage = "🟠 未完成"
            rows.append(f"{index}. {movie_title}{'  ' + stage if stage else ''}")
        return "\n".join(rows)

    def send_daily_completion_summary(self) -> None:
        """以昨日插件提交的任务为总账，逐项核对下载、整理和 Emby。"""
        timezone = pytz.timezone(settings.TZ)
        now = datetime.now(tz=timezone)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        summary_date = start.strftime("%Y.%m.%d")
        previous = self.get_data(self._daily_summary_key) or {}
        if previous.get("date") == summary_date and previous.get("direct_success"):
            return

        self.reconcile_download_completions()
        # qB 种子已删除时，只有 MP 成功整理记录才能反证下载确实完成；
        # 整理失败记录只标记失败，不能单独充当下载完成凭据。
        self.reconcile_mp_transfer_results(all_pending=True)
        self.verify_emby_ingestion()
        if not getattr(self, "_last_emby_check_ok", False):
            logger.warning("Emby 暂不可用，每日统计暂缓发送，避免将真实入库数误报为 0")
            return
        history = self._load_stats_history()

        submitted = []
        for item in history:
            submitted_at = self._parse_history_time(item.get("submitted_at"), timezone)
            if submitted_at and start <= submitted_at < end:
                submitted.append(item)
        # 总账按插件实际提交的每条任务计数；同一影片提交两次也是两条任务。
        submitted.sort(key=lambda item: str(item.get("submitted_at") or ""))
        downloaded_count = sum(1 for item in submitted if item.get("download_completed_at"))
        organized_count = sum(1 for item in submitted if item.get("organized_at"))
        ingested_count = sum(1 for item in submitted if item.get("emby_ingested_at"))
        failed_items = [item for item in submitted if not item.get("organized_at") and item.get("organize_failed_at")]
        awaiting_count = sum(1 for item in submitted if item.get("download_completed_at")
                             and not item.get("organized_at") and not item.get("organize_failed_at"))
        organized_waiting_emby = sum(1 for item in submitted if item.get("organized_at")
                                     and not item.get("emby_ingested_at"))
        title = (
            f"📊 {summary_date}｜插件提交 {len(submitted)} 项｜"
            f"下载完成 {downloaded_count} 项｜Emby 已有 {ingested_count} 项"
        )
        header = (
            f"未完成下载：{len(submitted) - downloaded_count} 项｜MP 已整理：{organized_count} 项\n"
            f"MP 整理失败：{len(failed_items)} 项｜下载完待整理：{awaiting_count} 项\n"
            f"待入库：{organized_waiting_emby} 项\n"
        )
        footer = "\n以本日插件提交的任务为总账；无标记表示 Emby 已有，🟠 未完成下载，🟡 待整理，🔴 整理失败或待入库。"
        # Telegram 单条文本上限为 4096 字符。保守预留标题、分段标记和实体转义空间；
        # 不按固定部数分页，能装下一条就只发送一条，失败影片在名单内直接标记。
        row_limit = max(1000, 3800 - len(title) - len(header) - len(footer))
        rows = [html.escape(self._format_daily_movie_rows([item], index))
                for index, item in enumerate(submitted, 1)] or ["本日没有本插件提交下载的电影。"]
        pages, current, current_length = [], [], 0
        for row in rows:
            extra = len(row) + (1 if current else 0)
            if current and current_length + extra > row_limit:
                pages.append(current)
                current, current_length = [], 0
            current.append(row)
            current_length += len(row) + (1 if current_length else 0)
        if current:
            pages.append(current)
        messages = []
        for page_number, page_rows in enumerate(pages):
            page_label = f"名单 {page_number + 1}/{len(pages)}：\n" if len(pages) > 1 else ""
            messages.append((title, header + page_label + "\n".join(page_rows) + footer))
        sent_pages = min(int(previous.get("sent_pages") or 0), len(messages)) if previous.get("date") == summary_date else 0
        for message_number in range(sent_pages, len(messages)):
            title, body = messages[message_number]
            source, result = self._send_telegram_direct(
                title=title,
                text=body,
                userid=self._telegram_target(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            if not source or not result:
                logger.error(f"每日电影统计第 {message_number + 1}/{len(messages)} 页未送达 Telegram")
                self.save_data(self._daily_summary_key, {
                    "date": summary_date, "count": len(submitted), "downloaded_count": downloaded_count,
                    "organized_count": organized_count, "completed_count": ingested_count,
                    "failed_count": len(failed_items), "awaiting_count": awaiting_count,
                    "sent_pages": message_number, "total_pages": len(messages),
                    "direct_success": False,
                })
                return
            self.save_data(self._daily_summary_key, {
                "date": summary_date, "count": len(submitted), "downloaded_count": downloaded_count,
                "organized_count": organized_count, "completed_count": ingested_count,
                "failed_count": len(failed_items), "awaiting_count": awaiting_count,
                "sent_pages": message_number + 1, "total_pages": len(messages),
                "sent_at": now.isoformat(timespec="seconds"),
                "direct_success": message_number + 1 == len(messages),
            })
        detail = (f"{summary_date} 插件提交 {len(submitted)} 项，下载完成 {downloaded_count} 项，"
                  f"MoviePilot 已整理 {organized_count} 部，整理失败 {len(failed_items)} 部，"
                  f"待整理 {awaiting_count} 部，Emby 已有 {ingested_count} 部")
        if submitted:
            detail += "：" + "、".join(
                f"{item.get('title') or ''}{'（已入库）' if item.get('emby_ingested_at') else ''}"
                for item in submitted
            )
        self._append_plugin_log("每日统计", detail, "success")
        logger.info(f"插件每日下载/入库统计已发送：{detail}")

    def midnight_maintenance(self) -> None:
        self.send_daily_completion_summary()
        self.cleanup_daily_messages()

    def cleanup_daily_messages(self) -> None:
        """午夜撤回以前的推荐；未点击的电影同时解除推送去重，可在以后随机再次出现。"""
        today = datetime.now(tz=pytz.timezone(settings.TZ)).date()
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
        if self._telegram_chat_id_override:
            return self._telegram_chat_id_override
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

    def _delete_telegram_reply_later(self, source: Optional[str], result: Optional[dict], seconds: int = 10):
        if not source or not result or not result.get("message_id"):
            return
        timer = threading.Timer(seconds, self._delete_telegram_message,
                                args=(source, result["message_id"], result.get("chat_id")))
        timer.daemon = True
        timer.start()

    def _reply_telegram_action(self, title: str, text: str, chat_id: Any) -> None:
        source, result = self._send_telegram_direct(title=title, text=text,
                                                    userid=str(chat_id or self._telegram_target() or ""))
        if not result:
            logger.error(f"Telegram 按钮反馈未送达：{title}")
        else:
            self._delete_telegram_reply_later(source, result)

    def _show_telegram_menu(self, chat_id: str, userid: Any, username: Any = None) -> None:
        if not self._is_telegram_admin(userid, username):
            self._reply_telegram_action("无操作权限", "只有已配置的 Telegram 管理员可以查看本插件统计。", chat_id)
            return
        prefix = f"[PLUGIN]{self.__class__.__name__}|stats|"
        rows = [
            [("今天", "today"), ("昨天", "yesterday")],
            [("本周", "week"), ("本月", "month")],
            [("上个月", "last_month"), ("今年", "year")],
            [("当前状态", "status"), ("最近运行", "last_run")],
        ]
        buttons = [[{"text": label, "callback_data": prefix + key} for label, key in row]
                   for row in rows]
        source, result = self._send_telegram_direct(
            title="智能电影插件 · 管理菜单",
            text="请选择统计范围。今天和昨天会附电影名单；其余周期只显示汇总。\n"
                 "按任务提交时间归属周期，下载、整理和 Emby 状态约每 5 分钟核验。",
            userid=chat_id, buttons=buttons,
        )
        if not result:
            logger.error("Telegram 统计菜单未送达")
        else:
            self._delete_telegram_reply_later(source, result)

    def _show_telegram_help(self, chat_id: str, userid: Any, username: Any = None) -> None:
        if not self._is_telegram_admin(userid, username):
            self._reply_telegram_action("无操作权限", "只有已配置的 Telegram 管理员可以使用本插件指令。", chat_id)
            return
        self._reply_telegram_action(
            "智能电影插件 · 命令说明",
            "/start — 打开管理菜单（首次点 Open 自动执行）\n"
            "/smartmovie — 打开统计与状态菜单\n"
            "/help — 查看这份中文说明\n\n"
            "菜单中可点选今天、昨天、本周、本月、上个月、今年的统计，"
            "以及当前状态和最近运行。只接受已配置管理员的操作。",
            chat_id,
        )

    @eventmanager.register(EventType.PluginAction)
    def telegram_command_action(self, event: Event) -> None:
        data = event.event_data or {}
        if data.get("action") != "smartmovie_menu":
            return
        userid = data.get("user") or data.get("userid")
        username = data.get("username")
        chat_id = str(data.get("chat_id") or data.get("chatid") or userid or "")
        self._show_telegram_menu(chat_id, userid, username)

    @staticmethod
    def _stats_range(period: str, now: datetime) -> Optional[Tuple[datetime, datetime, str, bool]]:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            return midnight, now, "今天", True
        if period == "yesterday":
            return midnight - timedelta(days=1), midnight, "昨天", True
        if period == "week":
            return midnight - timedelta(days=midnight.weekday()), now, "本周", False
        if period == "month":
            return midnight.replace(day=1), now, "本月", False
        if period == "last_month":
            first = midnight.replace(day=1)
            previous = (first - timedelta(days=1)).replace(day=1)
            return previous, first, "上个月", False
        if period == "year":
            return midnight.replace(month=1, day=1), now, "今年", False
        return None

    def _telegram_stats_messages(self, period: str) -> List[Tuple[str, str]]:
        timezone = pytz.timezone(settings.TZ)
        now = datetime.now(tz=timezone)
        if period == "last_run":
            state = self.get_data(self._run_status_key) or {}
            if not state:
                return [("智能电影插件 · 最近运行", "尚无运行记录。")]
            origin = "手动" if state.get("source") == "manual" else "定时"
            return [("智能电影插件 · 最近运行",
                     f"时间：{state.get('updated_at') or '-'}\n"
                     f"来源：{origin}\n阶段：{state.get('stage') or '-'}\n"
                     f"目标：{state.get('target', 0)}｜站点查询：{state.get('searched', 0)}\n"
                     f"选中：{state.get('selected', 0)}｜已推送：{state.get('sent', 0)}\n"
                     f"说明：{html.escape(str(state.get('detail') or '-'))}")]
        if period == "status":
            active, _ = self._active_download_snapshot()
            annual_occupied, other_occupied = self._active_download_counts()
            queue = len(self._load_download_queue())
            disk = "保护中" if self._disk_guard_blocks_new() else "正常"
            return [("智能电影插件 · 当前状态",
                     f"插件：{'已开启' if self._enabled else '已关闭'}\n"
                     f"定时推送：{'已开启' if self._auto_push else '已暂停'}\n"
                     f"下载模式：{'自动' if self._auto_download else '手动'}\n"
                     f"本插件正在下载：{active} 部｜随机/其他：{other_occupied}/{self._max_active_downloads}｜年度：{annual_occupied}/{self._annual_max_active_downloads}\n"
                     f"等候下载：{queue}\n硬盘空间保护：{disk}")]
        selected = self._stats_range(period, now)
        if not selected:
            return []
        start, end, label, show_titles = selected
        history = self._load_stats_history()
        items = []
        for item in history:
            submitted_at = self._parse_history_time(item.get("submitted_at"), timezone)
            if submitted_at and start <= submitted_at < end:
                items.append(item)
        items.sort(key=lambda item: str(item.get("submitted_at") or ""))
        downloaded = sum(bool(item.get("download_completed_at")) for item in items)
        organized = sum(bool(item.get("organized_at")) for item in items)
        ingested = sum(bool(item.get("emby_ingested_at")) for item in items)
        failed = sum(bool(item.get("organize_failed_at")) and not item.get("organized_at") for item in items)
        waiting = sum(bool(item.get("organized_at")) and not item.get("emby_ingested_at") for item in items)
        title = f"📊 {label} · 智能电影插件"
        header = (f"{start.strftime('%Y.%m.%d %H:%M')}—{end.strftime('%Y.%m.%d %H:%M')}\n"
                  f"插件提交：{len(items)} 项｜下载完成：{downloaded} 项\n"
                  f"MP 已整理：{organized} 项｜整理失败：{failed} 项\n"
                  f"Emby 已有：{ingested} 项｜待入库：{waiting} 项")
        if len(history) >= 1000:
            oldest = min((parsed for item in history
                          if (parsed := self._parse_history_time(item.get("submitted_at"), timezone))),
                         default=None)
            if oldest and oldest > start:
                header += f"\nℹ️ 可核验记录始于 {oldest.strftime('%Y.%m.%d')}；更早已丢失的任务无法追溯"
        if not show_titles:
            return [(title, header)]
        rows = [html.escape(self._format_daily_movie_rows([item], index))
                for index, item in enumerate(items, 1)] or ["本日没有本插件提交下载的电影。"]
        pages, current, length = [], [], 0
        limit = max(1000, 3800 - len(title) - len(header))
        for row in rows:
            if current and length + len(row) + 1 > limit:
                pages.append(current)
                current, length = [], 0
            current.append(row)
            length += len(row) + 1
        if current:
            pages.append(current)
        return [(title, header + f"\n名单 {index}/{len(pages)}：\n" + "\n".join(page))
                for index, page in enumerate(pages, 1)]

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
        if self._disk_guard_blocks_new():
            raise RuntimeError("硬盘空间保护中，电影推荐暂停发送")
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
            title="🎬 智能下载影视资源_惹咪之北",
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
                             force_queue: bool = False,
                             allow_queue: bool = True,
                             source: str = "random") -> Tuple[bool, bool]:
        if self._disk_guard_blocks_new():
            return False, False
        if force_queue:
            if not allow_queue:
                logger.warning(f"立即运行没有可用下载位，跳过且不排队：{media.title_year}")
                return False, False
            if not self._enqueue_download(media, context, source=source):
                return False, False
            self._push_movie(media, context, queued=True)
            return True, False
        ok, error = self._submit_download(media, context, origin=source)
        if not ok:
            if self._disk_guard_blocks_new():
                return False, False
            if not allow_queue:
                logger.error(f"立即运行提交 {media.title_year} 失败且不排队：{error or '未知错误'}")
                return False, False
            logger.error(f"自动下载 {media.title_year} 暂时失败，转入队列：{error or '未知错误'}")
            if not self._enqueue_download(media, context, source=source):
                return False, False
            self._push_movie(media, context, queued=True)
            return True, False
        self._push_movie(media, context, auto_downloaded=True)
        return True, True

    def run_once(self, limit: Optional[int] = None, test_mode: bool = False,
                 month_task_id: str = ""):
        month_task = self._monthly_task(month_task_id) if month_task_id else None
        if month_task_id and (not month_task or not month_task.get("active")
                              or month_task.get("scan_state") != "complete"):
            return
        source = (f"月份任务 {month_task['year']}-{month_task['month']:02d}" if month_task
                  else "手动立即运行" if test_mode else "定时任务")
        auto_mode = self._auto_download or bool(month_task)
        if not self._enabled:
            self._append_plugin_log(source, "插件已关闭，未执行", "warning")
            logger.info("智能电影推送插件已关闭，本轮不执行")
            return
        if self._disk_guard_blocks_new():
            self._append_plugin_log(source, "硬盘空间保护中，未扫描也未推送", "warning")
            logger.warning("硬盘空间保护中，本轮电影扫描、推荐推送和新增下载全部跳过")
            return
        if not self._running_lock.acquire(blocking=False):
            self._append_plugin_log(source, "已有扫描任务正在运行，本轮跳过", "warning")
            logger.warning("智能电影推送已有任务运行，本轮跳过")
            return
        run_id = datetime.now(tz=pytz.timezone(settings.TZ)).strftime("%m%d-%H%M%S")
        def trace(category: str, message: str, level: str = "info") -> None:
            self._append_plugin_log(category, f"[{run_id}] {message}", level)
        try:
            target = max(1, min(int(limit or self._limit), 50))
            trace(source, f"开始执行；目标 {target} 部，下载模式 {'自动' if auto_mode else '手动'}，站点 {self._site_ids}，每轮最多查询 {self._max_searches} 部")
            self._set_run_status(run_id, source, "读取 TMDB 候选", "正在读取月份名单" if month_task else "正在获取热门、近期、经典与随机电影", target=target, selected=0, searched=0, sent=0)
            pushed = self._load_recent_pushes()
            pushed_ids = set(pushed)
            if month_task:
                # 月份任务可以反复续跑，历史提交与等待队列必须永久排除，不能只依赖 30 天推送去重。
                pushed_ids.update(str(item.get("tmdb_id")) for item in self._load_stats_history() if item.get("tmdb_id"))
                pushed_ids.update(str(item.get("tmdb_id")) for item in self._load_download_queue() if item.get("tmdb_id"))
            suppressed_ids = set(self._load_suppressed())
            scan_history = self._load_scan_cache(include_expired=True)
            scan_cache = self._load_scan_cache()
            search_scope = self._scan_scope()
            buckets = ({"monthly": [MediaInfo(tmdb_info=item["info"])
                                    for item in month_task.get("candidates") or [] if item.get("info")]
                       } if month_task else self._candidate_buckets(scan_history))
            trace("候选获取", "；".join(f"{name} {len(items)} 部" for name, items in buckets.items()))
            self._set_run_status(run_id, source, "读取媒体库索引", "批量获取 Emby 电影目录", target=target, selected=0, searched=0, sent=0)
            library_snapshot = self._library_snapshot_for_scan()
            if library_snapshot:
                trace("媒体库索引", f"已载入 {len(library_snapshot['tmdb_ids'])} 个 TMDB ID；候选查询将使用内存比对")
            else:
                trace("媒体库索引", "完整 Emby 索引暂不可用，自动下载暂缓，避免重复提交", "warning")
                if auto_mode:
                    return
            try:
                active_mp_ids = self._mp_active_movie_ids(DownloadChain().downloading() or [])
            except Exception as err:
                active_mp_ids = set()
                trace("下载核对", f"MoviePilot 正在下载列表暂不可用：{type(err).__name__}", "warning")
            plans = [
                ("new", min(self._new_count, target)),
                ("recent", min(self._recent_count, target)),
                ("classic", min(self._classic_count, target)),
                ("random", min(self._random_count, target)),
            ] if not month_task else [("monthly", target)]
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
                    if month_task_id and not (self._monthly_task(month_task_id) or {}).get("active"):
                        break
                    if self._disk_guard_blocks_new():
                        logger.warning("扫描期间触发硬盘保护，停止本轮电影搜索")
                        break
                    if len(selected) >= target or bucket_sent >= wanted:
                        break
                    tmdb_id = str(media.tmdb_id)
                    if tmdb_id in active_mp_ids:
                        with self._queue_lock:
                            self._remove_queued_movie(tmdb_id, "MoviePilot 已在下载")
                        trace("下载跳过", f"{media.title_year}：MoviePilot 已在下载")
                        continue
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
                    if cached and cached.get("status") == "library":
                        if not library_snapshot or not self._snapshot_has_movie(library_snapshot, media):
                            scan_cache.pop(tmdb_id, None)  # Emby 移除或索引不可用时重新核验。
                            scan_history.pop(tmdb_id, None)
                            cached = None
                    if cached and cached.get("status") in {"library", "no_resource", "error"}:
                        stats["cached"] += 1
                        continue
                    if stats["searched"] >= self._max_searches:
                        break
                    try:
                        if (self._snapshot_has_movie(library_snapshot, media)
                                if library_snapshot else self._already_in_library(media)):
                            stats["library"] += 1
                            scan_cache[tmdb_id] = {
                                "status": "library", "checked_at": datetime.now().isoformat(timespec="seconds")}
                            continue
                        stats["searched"] += 1
                        self._set_run_status(run_id, source, "搜索站点", f"正在查询 {media.title_year}", target=target, selected=len(selected), searched=stats["searched"], sent=0)
                        trace("资源查询", f"第 {stats['searched']}/{self._max_searches} 部：{media.title_year}，开始搜索站点 {self._site_ids}")
                        best = self._search_best(media)
                        if not best:
                            stats["no_resource"] += 1
                            trace("资源查询", f"{media.title_year}：无资源或未通过 MoviePilot 过滤规则")
                            released = self._release_date(media)
                            age_days = max(0, (datetime.now().date() - released).days) if released else 3650
                            scan_cache[tmdb_id] = {
                                "status": "no_resource", "scope": search_scope,
                                "age_days": age_days,
                                "checked_at": datetime.now().isoformat(timespec="seconds")}
                            continue
                        selected.append((media, best))
                        scan_history.pop(tmdb_id, None)
                        torrent = best.torrent_info
                        trace("筛选成功", f"{media.title_year}：{torrent.title or '未知资源'}；站点 {torrent.site}；大小 {StringUtils.format_size(torrent.size) if torrent.size else '未知'}")
                        self._set_run_status(run_id, source, "搜索站点", f"已选中 {media.title_year}", target=target, selected=len(selected), searched=stats["searched"], sent=0)
                        bucket_sent += 1
                    except Exception as err:
                        stats["errors"] += 1
                        trace("筛选异常", f"{media.title_year}：{err}", "error")
                        scan_cache[tmdb_id] = {
                            "status": "error", "scope": search_scope,
                            "checked_at": datetime.now().isoformat(timespec="seconds")}
                        logger.error(f"电影推送处理 {media.title_year} 失败：{err}", exc_info=True)
                return bucket_sent

            for bucket_name, wanted in plans:
                try_bucket(buckets[bucket_name], wanted)

            # 某一组资源不足时，按新片→近期→经典→随机的顺序继续补齐到总数。
            if len(selected) < target and not month_task:
                fallback = []
                for bucket_name in ("new", "recent", "classic", "random"):
                    fallback.extend(buckets[bucket_name])
                try_bucket(fallback, target - len(selected))

            # 扫描阶段完成后才集中发送，避免用户在漫长搜索过程中零散收到消息。
            diagnostic = (
                f"TMDB候选 {stats['tmdb']}，已推送跳过 {stats['pushed']}，不再推送 {stats['suppressed']}，"
                f"缓存跳过 {stats['cached']}，媒体库已有 {stats['library']}，查询站点 {stats['searched']}，"
                f"无资源/未命中过滤 {stats['no_resource']}，异常 {stats['errors']}，选中 {len(selected)}"
            )
            logger.info(f"电影扫描完成：{diagnostic}；开始集中推送")
            trace("扫描完成", diagnostic)
            trace("候选名单", "、".join(media.title_year for media, _ in selected) or "无")
            if auto_mode and selected:
                library_snapshot = self._library_snapshot_for_scan(force=True)
                if not library_snapshot:
                    trace("运行终止", "提交前未能复核 Emby 目录，未新增下载或等候任务", "warning")
                    return
            self._set_run_status(run_id, source, "批量发送", diagnostic, target=target, selected=len(selected), searched=stats["searched"], sent=0)
            if self._disk_guard_blocks_new():
                trace("运行终止", "扫描结束时触发硬盘保护；没有发送或新增下载", "warning")
                self._set_run_status(run_id, source, "已终止", "硬盘空间保护中", target=target, selected=len(selected), searched=stats["searched"], sent=0)
                logger.warning("扫描完成时硬盘保护已启动，本轮候选保留在扫描缓存但不推送、不下载")
                scan_history.update(scan_cache)
                self.save_data(self._scan_cache_key, scan_history)
                return
            sent = 0

            def send_batch(auto_slots: int = 0, allow_queue: bool = True) -> None:
                nonlocal sent
                auto_submitted = 0
                for media, best in selected:
                    if month_task_id and not (self._monthly_task(month_task_id) or {}).get("active"):
                        break
                    if self._disk_guard_blocks_new():
                        logger.warning("批量推送期间触发硬盘保护，剩余电影停止推送和下载")
                        break
                    tmdb_id = str(media.tmdb_id)
                    try:
                        # 快照获取后电影可能刚入库；真正下载前仅对选中的少数影片再核验一次。
                        if ((library_snapshot and self._snapshot_has_movie(library_snapshot, media))
                                or self._already_in_library(media)):
                            trace("发送跳过", f"{media.title_year}：提交前复核发现已在媒体库")
                            scan_cache[tmdb_id] = {
                                "status": "library", "checked_at": datetime.now().isoformat(timespec="seconds")}
                            continue
                        # 手动“立即运行”与定时开关相互独立，但执行与定时任务
                        # 完全相同：自动下载模式下真实提交下载；达到并发上限
                        # 或触发硬盘保护时进入等候队列。
                        if auto_mode:
                            # 手动立即运行是一次有严格数量上限的实际测试。
                            # 没有空位的项目不能进入长期队列，否则用户只点一次
                            # “运行 5 部”，后续却会随着空位不断继续下载。
                            if not allow_queue and auto_submitted >= auto_slots:
                                break
                            handled, submitted = self._auto_download_movie(
                                media, best,
                                force_queue=allow_queue and auto_submitted >= auto_slots,
                                allow_queue=allow_queue,
                                source="annual" if month_task else "random",
                            )
                            if not handled:
                                trace("提交失败", f"{media.title_year}：未提交，也未加入本次发送", "warning")
                                continue
                            if submitted:
                                auto_submitted += 1
                        else:
                            self._push_movie(media, best)
                        pushed_ids.add(tmdb_id)
                        pushed[tmdb_id] = datetime.now().isoformat(timespec="seconds")
                        sent += 1
                        trace("推送成功", f"{media.title_year}：{'已提交下载' if auto_mode and submitted else '已加入等候下载' if auto_mode else '已发送手动确认消息'}")
                        self._set_run_status(run_id, source, "批量发送", f"刚发送 {media.title_year}", target=target, selected=len(selected), searched=stats["searched"], sent=sent)
                    except Exception as err:
                        trace("推送失败", f"{media.title_year}：{err}", "error")
                        logger.error(f"集中推送 {media.title_year} 失败：{err}", exc_info=True)

            if auto_mode:
                # 锁住“读随机/其他活动数→批量提交”全过程；年度任务有独立名额。
                with self._queue_lock:
                    _, active = self._active_download_counts()
                    slots = max(0, self._max_active_downloads - active)
                    send_batch(slots, allow_queue=not test_mode)
                if test_mode and len(selected) > sent:
                    skipped = len(selected) - sent
                    if slots <= 0:
                        notice = (
                            f"正在下载任务已满：{active}/{self._max_active_downloads}。\n"
                            f"本次立即运行未提交电影，选中的 {len(selected)} 部没有加入等候队列。"
                        )
                        title = "❌ 电影推荐立即运行失败"
                    else:
                        notice = (
                            f"立即运行目标 {target} 部，当前已有 {active}/{self._max_active_downloads} 部正在下载。\n"
                            f"本次实际提交 {sent} 部；受同时下载上限限制，另外 {skipped} 部没有加入等候队列。"
                        )
                        title = "⚠️ 电影推荐立即运行受限"
                    source, result = self._send_telegram_direct(
                        title=title,
                        text=notice,
                        userid=self._telegram_target(),
                        disable_web_page_preview=True,
                    )
                    if not source or not result:
                        logger.error("立即运行受限通知未送达 Telegram，请检查机器人和目标频道权限")
                    logger.warning(notice.replace("\n", " "))
            else:
                send_batch()

            scan_history.update(scan_cache)
            self.save_data(self._scan_cache_key, scan_history)
            self.save_data(self._pushed_key, pushed)
            trace("运行完成", f"目标 {target} 部；选中 {len(selected)} 部；推送 {sent} 部；提交下载详见‘提交下载’日志")
            self._set_run_status(run_id, source, "已完成", diagnostic, target=target, selected=len(selected), searched=stats["searched"], sent=sent)
            logger.info(f"智能下载影视资源完成：目标 {target}，实际推送 {sent} 部，手动立即运行={test_mode}")
            if sent == 0 and not month_task and not (auto_mode and test_mode and selected):
                _, result = self._send_telegram_direct(
                    title="智能电影推荐立即运行完成",
                    text=f"本轮未选出电影。\n{diagnostic}",
                    userid=self._telegram_target(),
                )
                if not result:
                    trace("通知失败", "无候选结果的 Telegram 通知未送达", "warning")
                    logger.error("本轮未选出电影的通知未送达 Telegram")
        except Exception as err:
            trace("运行异常", f"{type(err).__name__}：{err}", "error")
            self._set_run_status(run_id, source, "运行失败", str(err)[:300])
            logger.error(f"电影推荐运行失败：{err}", exc_info=True)
        finally:
            if month_task_id and self._monthly_task(month_task_id):
                self._update_monthly_task(
                    month_task_id,
                    last_run_at=datetime.now(tz=pytz.timezone(settings.TZ)).isoformat(timespec="seconds"),
                )
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
        if action not in {"download", "suppress", "disk_ack", "stats"}:
            return
        channel = data.get("channel")
        source = data.get("source")
        userid = data.get("userid")
        username = data.get("username")
        message_id = data.get("original_message_id")
        chat_id = data.get("original_chat_id")

        if not self._is_telegram_admin(userid, username):
            logger.warning(f"拒绝非管理员操作电影推荐：userid={userid}, username={username}, action={action}")
            self._reply_telegram_action("无操作权限", "只有 Telegram 管理员可以操作电影推荐。", chat_id)
            return
        if action == "stats":
            messages = self._telegram_stats_messages(key)
            if not messages:
                self._reply_telegram_action("统计失败", "未知统计范围，请重新输入 /smartmovie。", chat_id)
                return
            if source and message_id:
                self._delete_telegram_message(source, message_id, chat_id)
            target = str(chat_id or userid or self._telegram_target() or "")
            for title, body in messages:
                sent_source, result = self._send_telegram_direct(
                    title=title, text=body, userid=target, parse_mode="HTML")
                if not result:
                    logger.error(f"Telegram 统计结果未送达：{key}")
                    break
                self._delete_telegram_reply_later(sent_source, result, seconds=600)
            return
        pending = self._load_pending()
        item = pending.get(key)
        if action == "disk_ack":
            result = self._ack_disk_guard(key)
            if result.get("success") and source and message_id:
                self._delete_telegram_message(source, message_id, chat_id)
            self._reply_telegram_action("硬盘保护", result.get("message") or "已处理", chat_id)
            return
        if action == "download" and not self._enabled:
            self._reply_telegram_action("插件已关闭",
                                        "当前不会提交或加入等候下载；请先在插件页面开启“插件状态”。", chat_id)
            return
        if action == "download" and self._disk_guard_blocks_new():
            self._reply_telegram_action("硬盘保护中",
                                        "暂不接受新下载；原推荐保留，清理空间并手动恢复保护后可再点击。", chat_id)
            return
        if not item:
            self._reply_telegram_action("操作失败", "这条推荐已过期，请等待下一轮推荐。", chat_id)
            return

        # 管理员点击即视为确认：先移除任务并立即撤回原消息，不等待后续下载反馈。
        pending.pop(key, None)
        self.save_data(self._pending_key, pending)
        self._remove_daily_record(key)
        if source and message_id:
            deleted = self._delete_telegram_message(source, message_id, chat_id)
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

        results = self._search_site_contexts(int(item["tmdb_id"]))
        context = next(
            (ctx for ctx in results if self._torrent_identity(ctx) == item.get("torrent_identity")),
            results[0] if results else None,
        )
        if not context:
            self._reply_telegram_action("下载失败", "所选站点中已找不到这条资源。", chat_id)
            return

        media = context.media_info
        # 独立机器人按钮不能把 MoviePilot 默认 TG 渠道传给下载链。
        download_channel = None if source == "__custom_telegram__" else channel
        download_userid = None if source == "__custom_telegram__" else userid
        with self._queue_lock:
            _, active = self._active_download_counts()
            if self._disk_guard_blocks_new() or active >= self._max_active_downloads:
                self._enqueue_download(media, context, channel=download_channel,
                                       userid=download_userid)
                logger.info(
                    f"管理员确认后进入等候下载：{media.title_year}，"
                    f"硬盘保护={self._disk_guard_blocks_new()}，活动任务 {active}/{self._max_active_downloads}"
                )
                return

            ok, error = self._submit_download(
                media, context, channel=download_channel, userid=download_userid,
                username="Telegram 智能电影推荐",
            )
        if not ok:
            self._reply_telegram_action("下载提交失败", error or "未知错误", chat_id)
            return


