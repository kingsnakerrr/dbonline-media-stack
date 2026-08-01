#!/usr/bin/env python3
"""Delete completed qB torrents after MDCng has moved the main media.

The program uses qB's file manifest plus read-only filesystem checks.  It never
touches the MDCng library path.  After the configured quiet period it asks qB
to remove both the torrent and any files still left in the original download
location (deleteFiles=true by default).
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import re
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path, PurePosixPath


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = env(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是整数，当前值：{raw!r}") from exc
    if value < minimum:
        raise SystemExit(f"{name} 不能小于 {minimum}")
    return value


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = env(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} 必须是数字，当前值：{raw!r}") from exc
    if not minimum <= value <= maximum:
        raise SystemExit(f"{name} 必须在 {minimum}～{maximum} 之间")
    return value


def env_bool(name: str, default: bool) -> bool:
    raw = env(name, "true" if default else "false").lower()
    if raw not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
        raise SystemExit(f"{name} 必须是 true/false，当前值：{raw!r}")
    return raw in {"1", "true", "yes", "on"}


QB_URL = env("QB_URL", "http://host.docker.internal:8080").rstrip("/")
QB_USERNAME = env("QB_USERNAME")
QB_PASSWORD = env("QB_PASSWORD")
QB_CATEGORY = env("QB_CATEGORY")
QB_TAG = env("QB_TAG")
QB_PATH_PREFIX = PurePosixPath(env("QB_PATH_PREFIX", "/downloads"))
LOCAL_PATH_PREFIX = Path(env("LOCAL_PATH_PREFIX", "/downloads")).resolve()
SENTINEL = env("MOUNT_SENTINEL", ".qb-autoremove-mounted")
POLL_SECONDS = env_int("POLL_SECONDS", 60, 5)
QUIET_SECONDS = env_int("QUIET_SECONDS", 3600, 60)
MIN_COMPLETED_AGE_SECONDS = env_int("MIN_COMPLETED_AGE_SECONDS", 600, 0)
FALLBACK_MOVED_PERCENT = env_float("FALLBACK_MOVED_PERCENT", 90, 1, 100)
DRY_RUN = env_bool("DRY_RUN", True)
DELETE_REMAINING_FILES = env_bool("DELETE_REMAINING_FILES", True)
MIN_MEDIA_SIZE = env_int("MIN_MEDIA_SIZE_MB", 20, 0) * 1024 * 1024
STATE_PATH = Path("/data/state.json")

DEFAULT_MEDIA_EXTENSIONS = (
    ".mp4,.mkv,.avi,.mov,.wmv,.m4v,.flv,.webm,.mpg,.mpeg,.mpe,"
    ".ts,.mts,.m2ts,.m2t,.vob,.rmvb,.rm,.asf,.divx,.f4v,.ogv,"
    ".3gp,.3g2,.mxf,.iso,.img"
)
MEDIA_EXTENSIONS = {
    suffix if suffix.startswith(".") else "." + suffix
    for suffix in (
        part.strip().lower()
        for part in env("MEDIA_EXTENSIONS", DEFAULT_MEDIA_EXTENSIONS).split(",")
    )
    if suffix
}

DEFAULT_JUNK_KEYWORDS = (
    "sample,trailer,preview,bonus,extra,sp,special,specials,ova,oad,ona,"
    "ncop,nced,opening,ending,op,ed,pv,cm,特典,特别篇,番外,花絮,"
    "预告,宣传,广告"
)
JUNK_KEYWORDS = {
    item.strip().casefold()
    for item in env("JUNK_KEYWORDS", DEFAULT_JUNK_KEYWORDS).split(",")
    if item.strip()
}

logging.basicConfig(
    level=getattr(logging, env("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("qb-mdcng-autoremove")
stopping = False


def stop(_signum: int, _frame: object) -> None:
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


@dataclass(frozen=True)
class FileEntry:
    name: str
    size: int
    path: Path

    @property
    def exists(self) -> bool:
        return self.path.exists()


@dataclass(frozen=True)
class MediaUnit:
    """One logical media item; a disc directory may contain many physical files."""

    name: str
    size: int
    paths: tuple[Path, ...]
    junk: bool = False

    @property
    def exists(self) -> bool:
        return any(path.exists() for path in self.paths)


@dataclass(frozen=True)
class Classification:
    mode: str
    primary: tuple[MediaUnit, ...]
    reason: str


class QBClient:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def request(self, path: str, data: dict[str, str] | None = None):
        encoded = None if data is None else urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(QB_URL + path, data=encoded)
        try:
            with self.opener.open(req, timeout=20) as response:
                body = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
                return json.loads(body) if "json" in content_type else body
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise PermissionError("qB WebUI 鉴权失败") from exc
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"qB API HTTP {exc.code}: {detail[:200]}") from exc

    def login(self) -> None:
        result = self.request(
            "/api/v2/auth/login",
            {"username": QB_USERNAME, "password": QB_PASSWORD},
        )
        if str(result).strip() != "Ok.":
            raise PermissionError(f"qB 登录失败：{result!r}")

    def torrents(self) -> list[dict]:
        query: dict[str, str] = {"filter": "all"}
        if QB_CATEGORY:
            query["category"] = QB_CATEGORY
        if QB_TAG:
            query["tag"] = QB_TAG
        result = self.request(
            "/api/v2/torrents/info?" + urllib.parse.urlencode(query)
        )
        if not isinstance(result, list):
            raise RuntimeError("qB 返回的任务列表格式异常")
        return result

    def files(self, torrent_hash: str) -> list[dict]:
        result = self.request(
            "/api/v2/torrents/files?"
            + urllib.parse.urlencode({"hash": torrent_hash})
        )
        if not isinstance(result, list):
            raise RuntimeError("qB 返回的文件列表格式异常")
        return result

    def delete_torrent(self, torrent_hash: str) -> None:
        self.request(
            "/api/v2/torrents/delete",
            {
                "hashes": torrent_hash,
                "deleteFiles": "true" if DELETE_REMAINING_FILES else "false",
            },
        )


def load_state() -> dict[str, dict]:
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("顶层不是对象")
        result: dict[str, dict] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[str(key)] = value
        return result
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        log.warning("状态文件无法读取，将重新计时：%s", exc)
        return {}


def save_state(state: dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_PATH)


def map_qb_path(raw: str) -> Path:
    normalized = PurePosixPath(posixpath.normpath(raw.replace("\\", "/")))
    try:
        relative = normalized.relative_to(QB_PATH_PREFIX)
    except ValueError as exc:
        raise ValueError(
            f"qB 路径 {raw!r} 不在 QB_PATH_PREFIX={str(QB_PATH_PREFIX)!r} 下"
        ) from exc
    local = (LOCAL_PATH_PREFIX / Path(*relative.parts)).resolve()
    if local != LOCAL_PATH_PREFIX and LOCAL_PATH_PREFIX not in local.parents:
        raise ValueError(f"路径越界：{local}")
    return local


def mount_is_safe() -> bool:
    marker = LOCAL_PATH_PREFIX / SENTINEL
    if not LOCAL_PATH_PREFIX.is_dir():
        log.error("下载目录挂载不存在：%s；本轮不执行", LOCAL_PATH_PREFIX)
        return False
    if not marker.is_file():
        log.error("安全哨兵不存在：%s；本轮不执行任何删种", marker)
        return False
    return True


def tokenized(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", text.casefold()).strip()


def is_junk_name(name: str) -> bool:
    folded = name.casefold()
    tokens = set(tokenized(folded).split())
    for keyword in JUNK_KEYWORDS:
        # One/two-letter Latin markers (SP/OP/ED/PV/CM) must be standalone.
        if keyword.isascii() and len(keyword) <= 2:
            if keyword in tokens or re.search(
                rf"(?:^|[^a-z]){re.escape(keyword)}\d{{0,3}}(?:$|[^a-z])",
                folded,
            ):
                return True
        elif keyword.isascii():
            if re.search(
                rf"(?:^|[^a-z]){re.escape(keyword)}s?\d{{0,3}}(?:$|[^a-z])",
                folded,
            ):
                return True
        elif keyword in folded:
            return True
    return False


def disc_root(name: str) -> str | None:
    parts = name.replace("\\", "/").split("/")
    for index, part in enumerate(parts[:-1]):
        if part.casefold() in {"bdmv", "video_ts"}:
            return "/".join(parts[: index + 1])
    return None


def build_manifest(
    torrent: dict, raw_files: list[dict]
) -> tuple[list[FileEntry], list[MediaUnit]]:
    save_path = str(torrent.get("save_path") or "")
    if not save_path:
        raise ValueError("任务没有 save_path")

    selected: list[FileEntry] = []
    disc_groups: dict[str, list[FileEntry]] = {}
    media: list[MediaUnit] = []

    for item in raw_files:
        if int(item.get("priority", 0) or 0) <= 0:
            continue
        name = str(item.get("name") or "").replace("\\", "/")
        if not name:
            continue
        full_qb_path = posixpath.join(save_path.replace("\\", "/"), name)
        entry = FileEntry(
            name=name,
            size=int(item.get("size", 0) or 0),
            path=map_qb_path(full_qb_path),
        )
        selected.append(entry)

        root = disc_root(name)
        if root:
            disc_groups.setdefault(root, []).append(entry)
            continue
        if PurePosixPath(name).suffix.lower() in MEDIA_EXTENSIONS:
            media.append(
                MediaUnit(name, entry.size, (entry.path,), is_junk_name(name))
            )

    for root, entries in disc_groups.items():
        media.append(
            MediaUnit(
                name=root,
                size=sum(item.size for item in entries),
                paths=tuple(item.path for item in entries),
                junk=is_junk_name(root),
            )
        )
    return selected, media


CHINESE_NUMBER = r"[零〇一二两三四五六七八九十百千万\d]+"
EPISODE_PATTERNS = [
    re.compile(r"(?i)(?:^|[^a-z0-9])s\d{1,4}\s*[._ -]*e\d{1,5}(?:$|[^a-z0-9])"),
    re.compile(r"(?i)(?:^|[^a-z0-9])\d{1,4}x\d{1,5}(?:$|[^a-z0-9])"),
    re.compile(r"(?i)(?:^|[^a-z])(?:ep(?:isode)?|e)[ ._-]*\d{1,5}(?:$|[^a-z0-9])"),
    re.compile(rf"(?:第\s*)?{CHINESE_NUMBER}\s*(?:集|话|回|期|章)"),
]
DATE_PATTERN = re.compile(
    r"(?<!\d)(?:19|20)\d{2}[._-]?(?:0?[1-9]|1[0-2])[._-]?(?:0?[1-9]|[12]\d|3[01])(?!\d)"
)
SEGMENT_PATTERN = re.compile(
    r"(?i)(?:^|[^a-z])(?:cd|disc|disk|part|pt)[ ._-]*\d{1,3}(?:$|[^a-z0-9])|(?:^|[._ -])(?:上|中|下)(?:集|部|篇)?(?:$|[._ -])"
)
TECH_NUMBERS = {264, 265, 480, 576, 720, 1080, 1440, 2160, 4320}


def has_episode_marker(name: str) -> bool:
    stem = str(PurePosixPath(name).with_suffix(""))
    return any(pattern.search(stem) for pattern in EPISODE_PATTERNS)


def has_date_marker(name: str) -> bool:
    return bool(DATE_PATTERN.search(str(PurePosixPath(name).with_suffix(""))))


def has_segment_marker(name: str) -> bool:
    return bool(SEGMENT_PATTERN.search(str(PurePosixPath(name).with_suffix(""))))


def bare_sequence_group(items: list[MediaUnit]) -> list[MediaUnit]:
    """Find the largest stable filename skeleton containing >=3 numeric items."""
    groups: dict[str, list[tuple[int, MediaUnit]]] = {}
    for item in items:
        stem = PurePosixPath(item.name).stem.casefold()
        matches = list(re.finditer(r"(?<!\d)(\d{1,5})(?!\d)", stem))
        for match in reversed(matches):
            number = int(match.group(1))
            if number in TECH_NUMBERS or 1900 <= number <= 2099:
                continue
            skeleton = stem[: match.start()] + "#" + stem[match.end() :]
            skeleton = re.sub(
                r"(?i)\b(?:1080p?|2160p?|4k|h[._-]?26[45]|hevc|av1|10bit)\b",
                "",
                skeleton,
            )
            skeleton = re.sub(r"\s+", " ", skeleton).strip()
            groups.setdefault(skeleton, []).append((number, item))
            break
    valid: list[list[tuple[int, MediaUnit]]] = []
    for group in groups.values():
        numbers = {number for number, _item in group}
        if len(group) >= 3 and len(numbers) >= 3:
            valid.append(group)
    if not valid:
        return []
    best = max(valid, key=len)
    return [item for _number, item in best]


def classify_media(media: list[MediaUnit]) -> Classification:
    clean = [item for item in media if not item.junk]
    if not clean:
        return Classification("none", (), "没有识别到非垃圾视频")

    # Prefer sizeable files, but fall back to all clean media for short content.
    sizeable = [item for item in clean if item.size >= MIN_MEDIA_SIZE]
    candidates = sizeable or clean
    if len(candidates) == 1:
        return Classification("single", (candidates[0],), "唯一正片载体")

    episodic = [item for item in candidates if has_episode_marker(item.name)]
    if episodic:
        return Classification("series", tuple(episodic), "集数/季集命名")

    dated = [item for item in candidates if has_date_marker(item.name)]
    if len(dated) >= 2:
        return Classification("series", tuple(dated), "日期递增节目")

    segmented = [item for item in candidates if has_segment_marker(item.name)]
    if len(segmented) >= 2:
        return Classification("multipart", tuple(segmented), "CD/Disc/Part/上中下")

    numbered = bare_sequence_group(candidates)
    if numbered:
        return Classification("series", tuple(numbered), "纯数字递增命名")

    return Classification("fallback", (), "多视频命名无法可靠分组")


BUSY_STATES = {
    "checkingup",
    "checkingdl",
    "moving",
    "allocating",
    "metadl",
    "downloading",
    "forceddl",
    "stalleddl",
    "queueddl",
}


def torrent_is_completed(torrent: dict, now: float) -> bool:
    if float(torrent.get("progress", 0) or 0) < 0.999999:
        return False
    completed_on = int(torrent.get("completion_on", 0) or 0)
    if completed_on <= 0 or now - completed_on < MIN_COMPLETED_AGE_SECONDS:
        return False
    return str(torrent.get("state", "")).casefold() not in BUSY_STATES


def update_observation(entry: dict, selected: list[FileEntry], now: float) -> None:
    missing = sorted(item.name for item in selected if not item.exists)
    previous = entry.get("missing")
    if not isinstance(previous, list) or previous != missing:
        entry["missing"] = missing
        entry["last_activity"] = now
        entry.pop("ready_since", None)


def decision(
    torrent: dict,
    selected: list[FileEntry],
    media: list[MediaUnit],
    entry: dict,
    now: float,
) -> tuple[bool, str]:
    classification = classify_media(media)
    update_observation(entry, selected, now)

    if classification.mode == "none":
        entry.pop("ready_since", None)
        return False, classification.reason

    if classification.mode in {"single", "series", "multipart"}:
        remaining = [item for item in classification.primary if item.exists]
        if remaining:
            entry.pop("ready_since", None)
            return (
                False,
                f"{classification.reason}：正片仍存在 {len(remaining)}/"
                f"{len(classification.primary)}",
            )
        ready_since = float(entry.setdefault("ready_since", now))
        quiet = now - ready_since
        return (
            quiet >= QUIET_SECONDS,
            f"{classification.reason}：正片已全部移动，静默 "
            f"{int(quiet)}/{QUIET_SECONDS}s",
        )

    # Unrecognized multi-video torrent: capacity-based fallback. Use qB's web
    # total when available, otherwise the selected-file sum.
    total_size = int(torrent.get("total_size", 0) or 0)
    if total_size <= 0:
        total_size = sum(item.size for item in selected)
    if total_size <= 0:
        entry.pop("ready_since", None)
        return False, "种子总容量为0"
    moved_size = sum(item.size for item in selected if not item.exists)
    moved_media = any(not item.exists for item in media if not item.junk)
    percent = moved_size * 100.0 / total_size
    if not moved_media or percent < FALLBACK_MOVED_PERCENT:
        entry.pop("ready_since", None)
        return False, f"容量回退：已移动 {percent:.1f}%/{FALLBACK_MOVED_PERCENT:.1f}%"

    last_activity = float(entry.get("last_activity", now))
    ready_since = float(entry.setdefault("ready_since", max(now, last_activity)))
    quiet = now - max(ready_since, last_activity)
    return (
        quiet >= QUIET_SECONDS,
        f"容量回退：已移动 {percent:.1f}%，静默 {int(quiet)}/{QUIET_SECONDS}s",
    )


def run_once(client: QBClient, state: dict[str, dict]) -> None:
    if not mount_is_safe():
        return

    client.login()
    torrents = client.torrents()
    now = time.time()
    seen: set[str] = set()

    for torrent in torrents:
        torrent_hash = str(torrent.get("hash", ""))
        name = str(torrent.get("name", torrent_hash))
        if not torrent_hash:
            continue
        seen.add(torrent_hash)

        if not torrent_is_completed(torrent, now):
            state.pop(torrent_hash, None)
            continue

        try:
            selected, media = build_manifest(torrent, client.files(torrent_hash))
            if not selected:
                state.pop(torrent_hash, None)
                log.warning("任务 %s 没有已选择下载的文件，跳过", name)
                continue
            entry = state.setdefault(torrent_hash, {})
            should_delete, reason = decision(
                torrent, selected, media, entry, now
            )
        except ValueError as exc:
            state.pop(torrent_hash, None)
            log.error("任务 %s 路径或清单异常：%s", name, exc)
            continue

        if not should_delete:
            log.info("等待：%s；%s", name, reason)
            continue

        if DRY_RUN:
            log.warning(
                "[DRY-RUN] 符合删除条件：%s；%s；deleteFiles=%s",
                name,
                reason,
                DELETE_REMAINING_FILES,
            )
            continue

        client.delete_torrent(torrent_hash)
        state.pop(torrent_hash, None)
        log.warning(
            "已删除种子%s：%s；%s",
            "及全部剩余文件" if DELETE_REMAINING_FILES else "（保留剩余文件）",
            name,
            reason,
        )

    for stale_hash in set(state) - seen:
        state.pop(stale_hash, None)
    save_state(state)


def validate_config() -> None:
    if not QB_USERNAME or not QB_PASSWORD:
        raise SystemExit("必须设置 QB_USERNAME 和 QB_PASSWORD")
    if not QB_CATEGORY and not QB_TAG:
        raise SystemExit("为防止误删，QB_CATEGORY 和 QB_TAG 至少设置一个白名单")
    if not QB_PATH_PREFIX.is_absolute() or not LOCAL_PATH_PREFIX.is_absolute():
        raise SystemExit("QB_PATH_PREFIX 和 LOCAL_PATH_PREFIX 必须是绝对路径")
    if "/" in SENTINEL or "\\" in SENTINEL or SENTINEL in {"", ".", ".."}:
        raise SystemExit("MOUNT_SENTINEL 必须是下载根目录中的单个文件名")
    if not MEDIA_EXTENSIONS:
        raise SystemExit("MEDIA_EXTENSIONS 不能为空")


def main() -> None:
    validate_config()
    log.warning(
        "启动：category=%r tag=%r dry_run=%s delete_files=%s quiet=%ds fallback=%.1f%%",
        QB_CATEGORY,
        QB_TAG,
        DRY_RUN,
        DELETE_REMAINING_FILES,
        QUIET_SECONDS,
        FALLBACK_MOVED_PERCENT,
    )
    client = QBClient()
    state = load_state()
    while not stopping:
        try:
            run_once(client, state)
        except Exception:
            log.exception("本轮检查失败；不会执行未确认的删种")
        deadline = time.monotonic() + POLL_SECONDS
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1, max(0, deadline - time.monotonic())))
    log.info("收到停止信号，退出")


if __name__ == "__main__":
    main()
