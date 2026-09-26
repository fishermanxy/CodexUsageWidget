# -*- coding: utf-8 -*-
"""
Codex Usage Widget — 桌面悬浮用量卡片
- 4 套主题可切换：明亮模式 / 暗黑模式 / 信息面板 / 极简仪表盘
- 多账号切换、窗口可缩放且状态记忆、配额显示剩余用量
- 数据目录自动发现，零硬编码路径
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QFileSystemWatcher, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSizeGrip,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

# ──────────────────────────────── 常量 ────────────────────────────────

APP_NAME = "Codex Usage Widget"
STATE_FILE = "widget-state.json"
USAGE_THROTTLE_MS = 30_000
WATCH_DEBOUNCE_MS = 250
WATCH_HEALTH_MS = 5 * 60_000
RESET_CREDIT_CACHE = "reset-credit-details-cache.json"
RESET_CREDIT_SCHEMA_VERSION = 1
RESET_CREDIT_PRODUCER_VERSION = "2.60.0"
REQUIRED_FILES = ("codex-quota-cache.json", "config.json", "usage.jsonl")
WATCHED_FILES = (*REQUIRED_FILES, RESET_CREDIT_CACHE)

DEFAULT_SIZE = (400, 250)
MIN_SIZE = (280, 170)

# ──────────────────────────────── 主题 ────────────────────────────────

THEMES: Dict[str, Dict[str, Any]] = {
    "light": {
        "title": "明亮模式",
        "density": "standard",
        "bg": "#f6f8fb", "border": "#dde3ec", "fg": "#101828",
        "muted": "#475467", "faint": "#98a2b3",
        "accent": "#155eef", "track": "#e4e9f2",
        "hover": "#e8edf5", "close_hover_bg": "#fee4e2", "close_hover_fg": "#d92d20",
        "avatar_bg": "#e0e9fe", "shadow": 50,
    },
    "dark": {
        "title": "暗黑模式",
        "density": "standard",
        "bg": "#1e1e24", "border": "#34343e", "fg": "#e8e8ee",
        "muted": "#9a9aa8", "faint": "#6a6a78",
        "accent": "#2dd4bf", "track": "#34343e",
        "hover": "#2a2a33", "close_hover_bg": "#4a2530", "close_hover_fg": "#f87171",
        "avatar_bg": "#14332c", "shadow": 90,
    },
    "panel": {
        "title": "信息面板",
        "density": "rich",
        "bg": "#f6f8fb", "border": "#dde3ec", "fg": "#101828",
        "muted": "#475467", "faint": "#98a2b3",
        "accent": "#155eef", "track": "#e4e9f2",
        "hover": "#e8edf5", "close_hover_bg": "#fee4e2", "close_hover_fg": "#d92d20",
        "avatar_bg": "#e0e9fe", "shadow": 50,
    },
    "minimal": {
        "title": "极简仪表盘",
        "density": "compact",
        "bg": "#101418", "border": "#232a32", "fg": "#f2f4f6",
        "muted": "#8b949e", "faint": "#5b636c",
        "accent": "#7ee787", "track": "#232a32",
        "hover": "#1a212a", "close_hover_bg": "#3d2326", "close_hover_fg": "#ff7b72",
        "avatar_bg": "#15211a", "shadow": 90,
    },
}
THEME_ORDER = ["light", "dark", "panel", "minimal"]

# ──────────────────────────────── 工具函数 ────────────────────────────────

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def state_path() -> Path:
    return app_dir() / STATE_FILE


def load_state() -> Dict[str, Any]:
    try:
        p = state_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    try:
        state_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def normalize_ts(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return f / 1000.0 if f > 1e12 else f


def is_free_plan(plan: Any) -> bool:
    return isinstance(plan, str) and plan.strip().lower() == "free"


def account_key(value: Any) -> str:
    """Normalize account identifiers before comparing config and cache values."""
    return str(value or "").strip().casefold()


def today_midnight_ts() -> float:
    now = datetime.now().astimezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def human_bytes(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def human_dur(seconds: float) -> str:
    """A stable, adaptive relative duration suitable for low-frequency repainting."""
    remaining = max(0, int(seconds))
    if remaining >= 24 * 3600:
        return f"{(remaining + 24 * 3600 - 1) // (24 * 3600)} 天后"
    if remaining >= 3600:
        return f"{(remaining + 3600 - 1) // 3600} 小时后"
    if remaining >= 60:
        return f"{(remaining + 59) // 60} 分钟后"
    return f"{remaining} 秒后"


def countdown_refresh_delay(seconds: float) -> int:
    """Milliseconds until the next visible adaptive-duration change."""
    remaining = max(0, seconds)
    if remaining < 60:
        return 1_000
    unit = 60 if remaining < 3600 else 3600 if remaining < 24 * 3600 else 24 * 3600
    remainder = remaining % unit
    return max(1_000, int((remainder if remainder > 0 else unit) * 1000) + 50)


def normalize_datetime(v: Any) -> Optional[float]:
    """Accept Unix timestamps or the ISO timestamps emitted by OpenCodex' safe cache."""
    normalized = normalize_ts(v)
    if normalized is not None:
        return normalized
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def format_credit_expiry(expires_at: Optional[float], now: Optional[float] = None) -> str:
    if expires_at is None:
        return "到期信息暂不可用"
    now = time.time() if now is None else now
    if expires_at <= now:
        return "已到期"
    date = datetime.fromtimestamp(expires_at).strftime("%Y年%m月%d日")
    return f"到期：{date}（{human_dur(expires_at - now)}）"


def format_credit_expiry_parts(expires_at: Optional[float], now: Optional[float] = None) -> Tuple[str, str]:
    """Return the absolute date and remaining time as separate UI fields."""
    if expires_at is None:
        return "到期信息暂不可用", ""
    now = time.time() if now is None else now
    if expires_at <= now:
        return "已到期", ""
    date = datetime.fromtimestamp(expires_at).strftime("%Y年%m月%d日")
    return date, human_dur(expires_at - now)


def reset_countdown(reset_ts: Optional[float], period: int, now: Optional[float] = None) -> str:
    """Format a reset countdown, rolling expired recurring windows forward."""
    if reset_ts is None:
        return "重置 —"
    now = time.time() if now is None else now
    next_reset = reset_ts
    if next_reset <= now and period > 0:
        periods_elapsed = int((now - next_reset) // period) + 1
        next_reset += periods_elapsed * period
    remaining = next_reset - now
    return "重置 —" if remaining <= 0 else f"重置 {human_dur(remaining)}"


def format_reset_credits(value: Any, credits: Optional[List[Dict[str, Any]]] = None) -> str:
    try:
        count = max(0, int(value or 0))
    except (TypeError, ValueError):
        count = 0
    if not count:
        return "重置额度：暂无"
    earliest = min(
        (item.get("expires_at") for item in (credits or []) if item.get("expires_at") is not None),
        default=None,
    )
    return f"重置额度：{count} 次 · {format_credit_expiry(earliest)}"


def format_reset_credit_status(
    updated_at: Optional[float], failed_at: Optional[float], notice: str = ""
) -> str:
    """Describe cache freshness without implying that the widget queried upstream."""
    if notice:
        return f"提示：{notice}"
    if failed_at is not None and (updated_at is None or failed_at >= updated_at):
        return f"详情同步失败 {datetime.fromtimestamp(failed_at).strftime('%m-%d %H:%M')} · 保留上次有效内容"
    if updated_at is not None:
        return f"最近同步 {datetime.fromtimestamp(updated_at).strftime('%m-%d %H:%M')}"
    return "详情尚未同步"

# ──────────────────────────────── 数据目录自动发现 ────────────────────────────────

def candidate_data_dirs() -> List[Path]:
    dirs: List[Path] = []
    home = Path.home()
    dirs.append(home / ".opencodex")
    try:
        users_root = Path(os.environ.get("SYSTEMDRIVE", "C:")) / "Users"
        if users_root.exists():
            for child in users_root.iterdir():
                d = child / ".opencodex"
                if d not in dirs:
                    dirs.append(d)
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "name like '%bun%'", "get", "CommandLine,ExecutablePath", "/format:list"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        for line in out.splitlines():
            m = re.search(r"([A-Za-z]:[\\\/][^\"']*\.opencodex)", line)
            if m:
                d = Path(m.group(1))
                if d not in dirs:
                    dirs.append(d)
    except Exception:
        pass
    return dirs


def find_data_dir(saved: Optional[str] = None) -> Optional[Path]:
    if saved:
        p = Path(saved)
        if all((p / f).exists() for f in REQUIRED_FILES):
            return p
    for d in candidate_data_dirs():
        if all((d / f).exists() for f in REQUIRED_FILES):
            return d
    return None


# ──────────────────────────────── 数据层 ────────────────────────────────

class UsageStats:
    __slots__ = ("requests", "tokens_in", "tokens_out", "tokens_cached", "errors", "models")

    def __init__(self) -> None:
        self.requests = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.tokens_cached = 0
        self.errors = 0
        self.models: Dict[str, int] = {}

    def add(self, row: Dict[str, Any]) -> None:
        self.requests += 1
        usage = row.get("usage") or {}
        self.tokens_in += int(usage.get("inputTokens") or 0)
        self.tokens_out += int(usage.get("outputTokens") or 0)
        self.tokens_cached += int(
            usage.get("cachedInputTokens") or usage.get("cacheReadInputTokens") or 0
        )
        if int(row.get("status") or 0) >= 400:
            self.errors += 1
        model = row.get("resolvedModel") or row.get("model") or "unknown"
        self.models[model] = self.models.get(model, 0) + 1


class DataStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._mtimes: Dict[str, float] = {}
        self._cache: Dict[str, Any] = {}
        self._usage_offset: int = 0
        self._usage_file_marker: Optional[Tuple[int, int]] = None
        self._usage_rebuild_pending = False
        self._usage_day_start: float = today_midnight_ts()
        self._today_stats: Dict[str, UsageStats] = {}
        self._last_usage_scan: float = 0.0

    def invalidate(self, *names: str) -> None:
        for name in names:
            self._mtimes.pop(name, None)
            if name == "usage.jsonl":
                # QFileSystemWatcher reports atomic replacements as a change, and
                # the replacement can be larger than the old file. Defer the
                # rebuild until the normal throttle window expires so the UI
                # keeps the last complete snapshot while writes settle.
                self._usage_rebuild_pending = True

    def _read_json(self, name: str) -> Optional[Dict[str, Any]]:
        p = self.data_dir / name
        try:
            mtime = p.stat().st_mtime
            if self._mtimes.get(name) == mtime:
                return self._cache.get(name)
            self._mtimes[name] = mtime
            result = json.loads(p.read_text(encoding="utf-8"))
            self._cache[name] = result
            return result
        except Exception:
            return self._cache.get(name)

    def read_quota(self) -> Optional[Dict[str, Any]]:
        return self._read_json("codex-quota-cache.json")

    def read_config(self) -> Optional[Dict[str, Any]]:
        return self._read_json("config.json")

    def read_reset_credit_details(self) -> Optional[Dict[str, Any]]:
        return self._read_json(RESET_CREDIT_CACHE)

    def _scan_usage_tail(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_usage_scan) < USAGE_THROTTLE_MS / 1000:
            return
        self._last_usage_scan = now
        p = self.data_dir / "usage.jsonl"
        try:
            stat = p.stat()
            size = stat.st_size
            marker = (getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)), size)
            if self._usage_rebuild_pending:
                self._today_stats = {}
                self._usage_offset = 0
                self._usage_file_marker = None
            day_start = today_midnight_ts()
            if day_start != self._usage_day_start:
                self._usage_day_start = day_start
                self._today_stats = {}
                self._usage_offset = 0
                self._usage_file_marker = None
            elif self._usage_offset and (
                size < self._usage_offset
                or (size == self._usage_offset and marker != self._usage_file_marker)
            ):
                # The producer rotated or rewrote the log. Rebuild the bounded
                # tail instead of seeking past EOF or double-counting old rows.
                self._today_stats = {}
                self._usage_offset = 0
                self._usage_file_marker = None
            if self._usage_offset == 0:
                seek_back = min(size, 2 * 1024 * 1024)
                start_pos = size - seek_back
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(start_pos)
                    if start_pos > 0:
                        f.readline()
                    for line in f:
                        self._process_line(line)
                    self._usage_offset = f.tell()
            else:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._usage_offset)
                    for line in f:
                        self._process_line(line)
                    self._usage_offset = f.tell()
            self._usage_rebuild_pending = False
            self._usage_file_marker = marker
        except Exception:
            pass

    def _process_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            row = json.loads(line)
        except Exception:
            return
        if not isinstance(row, dict):
            return
        ts = normalize_ts(row.get("timestamp"))
        if ts is None or ts < self._usage_day_start:
            return
        provider = str(row.get("provider") or "")
        if provider == "openai":
            account_label = "__main__"
        elif provider.startswith("openai-"):
            account_label = str(row.get("accountLogLabel") or provider.removeprefix("openai-"))
        else:
            return
        self._today_stats.setdefault(account_label, UsageStats()).add(row)

    def today_stats(self, account_log_label: Optional[str], force: bool = False) -> UsageStats:
        self._scan_usage_tail(force)
        return self._today_stats.get(account_log_label or "__main__", UsageStats())

    def usage_wait_ms(self) -> int:
        elapsed_ms = int((time.time() - self._last_usage_scan) * 1000)
        return max(0, USAGE_THROTTLE_MS - elapsed_ms)

    # ---------- 账号列表与快照 ----------

    def account_list(self) -> List[Dict[str, Any]]:
        """返回可展示账号列表：池账号在前，主账号（__main__）在后"""
        config = self.read_config() or {}
        quota = self.read_quota() or {}
        accounts = list(config.get("codexAccounts", []))
        quotas = quota.get("quotas", {})
        if "__main__" in quotas:
            accounts.append({"id": "__main__", "email": "主账号（原生登录）", "plan": "free"})
        # 活动账号排最前
        active_id = (
            config.get("activeCodexAccountId")
            or config.get("activeCodexAccountPinned")
            or config.get("activeCodexAccount", "")
        )
        active_key = account_key(active_id)
        accounts.sort(key=lambda a: 0 if account_key(a.get("id")) == active_key else 1)
        return accounts

    def usage_changed(self) -> bool:
        try:
            stat = (self.data_dir / "usage.jsonl").stat()
            marker = (getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)), stat.st_size)
            return marker != self._usage_file_marker
        except Exception:
            return True

    def reset_credit_details(
        self, account_id: str, count: Any
    ) -> Tuple[List[Dict[str, Optional[float]]], Optional[float], Optional[float], bool, str]:
        cache = self.read_reset_credit_details() or {}
        notice = ""
        if cache:
            schema = cache.get("schemaVersion") if isinstance(cache, dict) else None
            producer = cache.get("producerVersion") if isinstance(cache, dict) else None
            if schema != RESET_CREDIT_SCHEMA_VERSION:
                notice = "详情缓存格式不兼容"
            elif producer != RESET_CREDIT_PRODUCER_VERSION:
                notice = "详情缓存版本不同"
        accounts = cache.get("accounts") if isinstance(cache, dict) else None
        entry = accounts.get(account_id) if isinstance(accounts, dict) else None
        if not isinstance(entry, dict):
            return [], None, None, False, notice
        updated_at = normalize_datetime(entry.get("updatedAt"))
        failed_at = normalize_datetime(entry.get("lastFailureAt"))
        try:
            cached_count = max(0, int(entry.get("availableCount") or 0))
        except (TypeError, ValueError):
            cached_count = -1
        try:
            expected_count = max(0, int(count or 0))
        except (TypeError, ValueError):
            expected_count = 0
        if cached_count != expected_count:
            return [], updated_at, failed_at, False, notice or "详情与当前额度数量不一致，等待同步"
        details: List[Dict[str, Optional[float]]] = []
        for raw in entry.get("credits") or []:
            if not isinstance(raw, dict):
                continue
            expires_at = normalize_datetime(raw.get("expiresAt") or raw.get("expires_at"))
            if expires_at is None:
                continue
            details.append({"expires_at": expires_at, "granted_at": normalize_datetime(raw.get("grantedAt") or raw.get("granted_at"))})
        if len(details) != expected_count:
            return [], updated_at, failed_at, False, notice or "详情不完整，等待同步"
        return sorted(details, key=lambda item: item["expires_at"] or float("inf")), updated_at, failed_at, True, notice

    def snapshot(self, account_id: Optional[str] = None, force_usage: bool = False) -> Dict[str, Any]:
        quota = self.read_quota()
        config = self.read_config()
        stats: UsageStats

        active_id = (
            (config or {}).get("activeCodexAccountId")
            or (config or {}).get("activeCodexAccountPinned")
            or (config or {}).get("activeCodexAccount", "")
        )
        accounts = {a["id"]: a for a in (config or {}).get("codexAccounts", [])}
        accounts.setdefault("__main__", {"id": "__main__", "email": "主账号（原生登录）", "plan": "free"})

        shown_id = account_id or active_id or "__main__"
        shown = accounts.get(shown_id, {"email": "未知账号", "plan": "?"})
        log_label = shown.get("logLabel") or shown_id
        stats = self.today_stats(log_label, force_usage)
        active_key = account_key(active_id)
        shown_keys = {
            account_key(shown_id),
            account_key(shown.get("id")),
            account_key(shown.get("logLabel")),
            account_key(shown.get("email")),
            account_key(shown.get("loginEmail")),
        }

        quotas = (quota or {}).get("quotas", {})
        q = quotas.get(shown_id) or {}
        credit_details, credit_updated, credit_failed, credit_cache_ok, credit_notice = self.reset_credit_details(
            shown_id, q.get("resetCredits", 0)
        )

        return {
            "email": shown.get("email") or "未知账号",
            "plan": shown.get("plan") or "?",
            "shown_id": shown_id,
            "is_active": bool(active_key and active_key in shown_keys),
            "short_percent": q.get("shortPercent", q.get("monthlyPercent", 0)),
            "short_reset": normalize_ts(q.get("shortResetAt") or q.get("monthlyResetAt")),
            "weekly_percent": q.get("weeklyPercent", 0),
            "weekly_reset": normalize_ts(q.get("weeklyResetAt")),
            "reset_credits": q.get("resetCredits", 0),
            "reset_credit_details": credit_details,
            "reset_credit_updated": credit_updated,
            "reset_credit_failed": credit_failed,
            "reset_credit_cache_ok": credit_cache_ok,
            "reset_credit_notice": credit_notice,
            "today": stats,
        }


# ──────────────────────────────── UI：进度条 ────────────────────────────────

class QuotaBar(QWidget):
    """带倒计时的单个配额进度条"""

    def __init__(self, title: str, period: int = 0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._period = period  # 窗口周期（秒），用于已过重置点后推算下次重置
        self._reset_ts: Optional[float] = None
        self._unavailable = False
        self._muted = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._title_label = QLabel(title)
        header.addWidget(self._title_label)
        header.addStretch()
        self._pct_label = QLabel("0%")
        header.addWidget(self._pct_label)
        self._reset_label = QLabel("")
        header.addWidget(self._reset_label)
        layout.addLayout(header)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(8)
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

    def apply_theme(self, t: Dict[str, Any]) -> None:
        self._accent = t["accent"]
        self._track = t["track"]
        self._muted = t["muted"]
        self._title_label.setStyleSheet(f"color:{t['fg']}; font-weight:600; font-size:10pt; background:transparent;")
        self._reset_label.setStyleSheet(f"color:{t['muted']}; font-size:8.5pt; background:transparent;")
        self._apply_color(self._muted if self._unavailable else self._accent)

    def _apply_color(self, color: str) -> None:
        self._pct_label.setStyleSheet(f"color:{color}; font-weight:700; font-size:10pt; background:transparent;")
        self._bar.setStyleSheet(f"""
            QProgressBar {{ background-color: {self._track}; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}
        """)

    def set_value(self, used_percent: int, reset_ts: Optional[float]) -> None:
        """传入已用百分比，界面显示剩余量；窗口已重置时显示100%"""
        self._unavailable = False
        self._bar.setEnabled(True)
        self._reset_ts = reset_ts
        if reset_ts is not None and reset_ts <= time.time():
            remaining = 100
        else:
            remaining = max(0, min(100, 100 - int(used_percent)))
        self._bar.setValue(remaining)
        self._pct_label.setText(f"{remaining}%")
        if remaining < 20:
            color = "#ef4444"
        elif remaining < 50:
            color = "#f59e0b"
        else:
            color = self._accent
        self._apply_color(color)
        self.tick()

    def set_unavailable(self) -> None:
        self._unavailable = True
        self._reset_ts = None
        self._bar.setEnabled(False)
        self._bar.setValue(0)
        self._pct_label.setText("无额度")
        self._reset_label.clear()
        self._apply_color(self._muted)

    def tick(self) -> None:
        if self._unavailable:
            return
        self._reset_label.setText(reset_countdown(self._reset_ts, self._period))


# ──────────────────────────────── 主卡片 ────────────────────────────────

class UsageCard(QMainWindow):
    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(*MIN_SIZE)

        self._drag_pos: Optional[QPoint] = None
        self._state = load_state()
        self._data_dir: Optional[Path] = None
        self._store: Optional[DataStore] = None
        self._last_snap: Optional[Dict[str, Any]] = None
        self._credit_expanded = bool(self._state.get("reset_credit_expanded", False))

        self._theme_key: str = self._state.get("theme", "light")
        if self._theme_key not in THEMES:
            self._theme_key = "light"
        self._last_saved_state: Optional[Dict[str, Any]] = None
        self._applied_theme_key: Optional[str] = None
        self._account_index: int = int(self._state.get("account_index", 0))
        self._accounts: List[Dict[str, Any]] = []

        self._build_ui()
        self._restore_geometry()
        self._discover_data()

        self._watcher = QFileSystemWatcher(self)
        self._watch_dirty: set[str] = set()
        self._watcher.fileChanged.connect(self._on_watched_file_changed)
        self._watcher.directoryChanged.connect(self._on_watched_directory_changed)
        self._watch_debounce = QTimer(self)
        self._watch_debounce.setSingleShot(True)
        self._watch_debounce.timeout.connect(self._flush_watched_changes)
        self._usage_deferred = QTimer(self)
        self._usage_deferred.setSingleShot(True)
        self._usage_deferred.timeout.connect(lambda: self._refresh(force_usage=True))
        self._watch_health = QTimer(self)
        self._watch_health.timeout.connect(self._configure_watchers)
        self._watch_health.start(WATCH_HEALTH_MS)
        self._configure_watchers()
        self._refresh(force_usage=True)
        self._schedule_countdown_refresh()

    # ---------- UI 构建 ----------

    def _build_ui(self) -> None:
        self._central = QWidget(self)
        self._central.setObjectName("card")
        self.setCentralWidget(self._central)

        self._root = QVBoxLayout(self._central)
        self._root.setContentsMargins(16, 14, 16, 10)
        self._root.setSpacing(10)

        # ── 头部 ──
        header = QHBoxLayout()
        self._avatar = QLabel("◈")
        self._avatar.setFixedSize(28, 28)
        self._avatar.setAlignment(Qt.AlignCenter)
        header.addWidget(self._avatar)

        info = QVBoxLayout()
        info.setSpacing(0)
        email_row = QHBoxLayout()
        email_row.setSpacing(2)
        self._prev_btn = self._mk_icon_btn("‹", self._prev_account)
        self._next_btn = self._mk_icon_btn("›", self._next_account)
        self._prev_btn.setFixedSize(20, 20)
        self._next_btn.setFixedSize(20, 20)
        self._email_label = QLabel("未找到数据")
        self._email_label.setMinimumWidth(0)
        email_row.addWidget(self._prev_btn)
        email_row.addWidget(self._email_label, stretch=1)
        email_row.addWidget(self._next_btn)
        info.addLayout(email_row)
        self._plan_label = QLabel("—")
        self._plan_label.setTextFormat(Qt.RichText)
        info.addWidget(self._plan_label)
        self._credit_row = QHBoxLayout()
        self._credit_summary_label = QLabel("重置额度  暂无")
        self._credit_summary_label.setObjectName("resetCredit")
        self._credit_row.addWidget(self._credit_summary_label, stretch=1)
        self._credit_toggle = self._mk_icon_btn("⌄", self._toggle_credit_details)
        self._credit_toggle.setFixedSize(18, 18)
        self._credit_row.addWidget(self._credit_toggle)
        info.addLayout(self._credit_row)
        self._credit_expiry_label = QLabel("")
        self._credit_expiry_label.setObjectName("creditExpiry")
        info.addWidget(self._credit_expiry_label)
        self._reset_credit_status_label = QLabel("")
        self._reset_credit_status_label.setObjectName("resetCreditStatus")
        info.addWidget(self._reset_credit_status_label)
        header.addLayout(info, stretch=1)

        self._pin_btn = self._mk_icon_btn("📌", lambda: self._toggle_pin(self._pin_btn.isChecked()))
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(True)
        header.addWidget(self._pin_btn, alignment=Qt.AlignTop)

        self._close_btn = self._mk_icon_btn("✕", self.close)
        header.addWidget(self._close_btn, alignment=Qt.AlignTop)
        self._root.addLayout(header)

        # ── 极简主题的大数字区 ──
        self._big_row = QHBoxLayout()
        self._big_short = QLabel("0%")
        self._big_weekly = QLabel("0%")
        self._big_reset_labels: List[QLabel] = []
        for lbl, name in ((self._big_short, "5h 剩余"), (self._big_weekly, "每周剩余")):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(lbl, alignment=Qt.AlignCenter)
            sub = QLabel(name)
            sub.setAlignment(Qt.AlignCenter)
            sub.setObjectName("bigSub")
            box.addWidget(sub)
            reset = QLabel("重置 —")
            reset.setAlignment(Qt.AlignCenter)
            reset.setObjectName("bigReset")
            box.addWidget(reset)
            self._big_reset_labels.append(reset)
            self._big_row.addLayout(box)
        big_wrap = QWidget()
        big_wrap.setLayout(self._big_row)
        self._big_wrap = big_wrap
        self._root.addWidget(big_wrap)
        self._big_credit_wrap = QWidget()
        big_credit_row = QHBoxLayout(self._big_credit_wrap)
        big_credit_row.setContentsMargins(0, 0, 0, 0)
        self._big_credit_label = QLabel("重置额度  暂无")
        self._big_credit_label.setAlignment(Qt.AlignCenter)
        self._big_credit_label.setObjectName("bigCredit")
        big_credit_row.addWidget(self._big_credit_label, stretch=1)
        self._big_credit_toggle = self._mk_icon_btn("⌄", self._toggle_credit_details)
        self._big_credit_toggle.setFixedSize(18, 18)
        big_credit_row.addWidget(self._big_credit_toggle)
        self._root.addWidget(self._big_credit_wrap)
        self._big_credit_expiry_label = QLabel("")
        self._big_credit_expiry_label.setAlignment(Qt.AlignCenter)
        self._big_credit_expiry_label.setObjectName("bigCreditExpiry")
        self._root.addWidget(self._big_credit_expiry_label)
        self._big_credit_status_label = QLabel("")
        self._big_credit_status_label.setAlignment(Qt.AlignCenter)
        self._big_credit_status_label.setObjectName("bigCreditStatus")
        self._root.addWidget(self._big_credit_status_label)

        self._credit_details = QWidget()
        credit_layout = QVBoxLayout(self._credit_details)
        credit_layout.setContentsMargins(0, 2, 0, 2)
        credit_layout.setSpacing(2)
        self._credit_details_title = QLabel("额度明细")
        self._credit_details_title.setObjectName("creditDetailsTitle")
        credit_layout.addWidget(self._credit_details_title)
        self._credit_detail_rows: List[Tuple[QWidget, QLabel, QLabel, QLabel]] = []
        for index in range(5):
            row = QWidget()
            row.setObjectName("creditDetailRow")
            row.setFixedHeight(20)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            number = QLabel(f"额度 {index + 1}")
            number.setObjectName("creditDetailNumber")
            number.setFixedWidth(40)
            date = QLabel("")
            date.setObjectName("creditDetailDate")
            remaining = QLabel("")
            remaining.setObjectName("creditDetailRemaining")
            remaining.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_layout.addWidget(number)
            row_layout.addWidget(date, stretch=1)
            row_layout.addWidget(remaining)
            credit_layout.addWidget(row)
            self._credit_detail_rows.append((row, number, date, remaining))
        self._credit_details.setVisible(False)
        self._root.addWidget(self._credit_details)
        self._short_bar = QuotaBar("5 小时窗口剩余", period=5 * 3600)
        self._weekly_bar = QuotaBar("每周窗口剩余", period=7 * 24 * 3600)
        self._root.addWidget(self._short_bar)
        self._root.addWidget(self._weekly_bar)

        # ── 分隔线 ──
        self._sep = QLabel()
        self._sep.setFixedHeight(1)
        self._root.addWidget(self._sep)

        # ── 今日统计 ──
        self._stats_wrap = QWidget()
        stats_row = QHBoxLayout(self._stats_wrap)
        stats_row.setContentsMargins(0, 0, 0, 0)
        self._req_label, req_box = self._make_stat("0", "今日请求")
        self._tok_label, tok_box = self._make_stat("0 / 0", "Tokens (in/out)")
        self._cache_label, cache_box = self._make_stat("0", "缓存 Tokens")
        stats_row.addLayout(req_box)
        stats_row.addLayout(tok_box)
        stats_row.addLayout(cache_box)
        self._root.addWidget(self._stats_wrap)

        # ── 详情面板（仅 rich 密度常驻显示） ──
        self._detail = QWidget()
        dl = QVBoxLayout(self._detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        self._detail_lines: List[QLabel] = []
        for _ in range(3):
            lbl = QLabel("—")
            lbl.setObjectName("detailLine")
            dl.addWidget(lbl)
            self._detail_lines.append(lbl)
        self._detail.setVisible(False)
        self._root.addWidget(self._detail)

        # ── 底部：状态栏 + 缩放手柄 ──
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self._status_label = QLabel("初始化…")
        bottom.addWidget(self._status_label, stretch=1, alignment=Qt.AlignRight)
        self._grip = QSizeGrip(self._central)
        self._grip.setFixedSize(14, 14)
        bottom.addWidget(self._grip, alignment=Qt.AlignBottom | Qt.AlignRight)
        self._root.addLayout(bottom)

        self._apply_theme()

    def _mk_icon_btn(self, text: str, handler) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(text)
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(handler)
        return btn

    def _make_stat(self, value: str, title: str) -> Tuple[QLabel, QVBoxLayout]:
        box = QVBoxLayout()
        box.setSpacing(0)
        v = QLabel(value)
        v.setObjectName("statValue")
        t = QLabel(title)
        t.setObjectName("statTitle")
        box.addWidget(v)
        box.addWidget(t)
        return v, box

    # ---------- 主题 ----------

    def _apply_theme(self) -> None:
        # 同主题重复调用时跳过
        if self._applied_theme_key == self._theme_key:
            return
        self._applied_theme_key = self._theme_key

        t = THEMES[self._theme_key]
        density = t["density"]

        # 透明度渐变平滑过渡（掩盖样式切换的突兀感）
        self.setWindowOpacity(0.3)
        self._do_apply_theme(t, density)
        self._fade_in()

    def _fade_in(self) -> None:
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(150)
        self._fade_anim.setStartValue(0.3)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

    def _do_apply_theme(self, t: Dict[str, Any], density: str) -> None:
        self._central.setStyleSheet(f"""
            #card {{
                background: {t['bg']};
                border-radius: 12px;
                border: 1px solid {t['border']};
            }}
            QLabel {{ background: transparent; color: {t['fg']}; }}
            #statValue {{ font-weight:700; font-size:11pt; }}
            #statTitle {{ color:{t['muted']}; font-size:8pt; }}
            #detailLine {{ color:{t['muted']}; font-size:8.5pt; }}
            #bigSub {{ color:{t['muted']}; font-size:9pt; }}
            #bigReset {{ color:{t['faint']}; font-size:8.5pt; }}
            #resetCredit {{ color:{t['muted']}; font-size:8pt; }}
            #creditExpiry {{ color:{t['fg']}; font-size:8pt; }}
            #resetCreditStatus {{ color:{t['faint']}; font-size:7.5pt; }}
            #bigCredit {{ color:{t['muted']}; font-size:9pt; }}
            #bigCreditExpiry {{ color:{t['fg']}; font-size:8.5pt; }}
            #bigCreditStatus {{ color:{t['faint']}; font-size:7.5pt; }}
            #creditDetailsTitle {{ color:{t['faint']}; font-size:7.5pt; font-weight:600; }}
            #creditDetailNumber {{ color:{t['muted']}; font-size:8pt; }}
            #creditDetailDate {{ color:{t['fg']}; font-size:8pt; }}
            #creditDetailRemaining {{ color:{t['muted']}; font-size:8pt; }}
            QToolButton {{
                background: transparent; border: none; border-radius: 13px;
                color: {t['muted']}; font-size: 12px; font-weight: 700;
            }}
            QToolButton:hover {{ background: {t['hover']}; }}
            QToolButton:checked {{ background: {t['avatar_bg']}; }}
        """)

        self._avatar.setStyleSheet(
            f"background: {t['avatar_bg']}; border-radius: 14px; font-size: 14px; color: {t['accent']};"
        )
        self._email_label.setStyleSheet(f"color:{t['fg']}; font-weight:600; font-size:9.5pt;")
        self._plan_label.setStyleSheet(f"color:{t['muted']}; font-size:8.5pt;")
        self._status_label.setStyleSheet(f"color:{t['faint']}; font-size:8pt;")
        self._sep.setStyleSheet(f"background: {t['track']};")
        self._short_bar.apply_theme(t)
        self._weekly_bar.apply_theme(t)
        for lbl in (self._big_short, self._big_weekly):
            lbl.setStyleSheet(f"color:{t['accent']}; font-weight:800; font-size:22pt;")

        # 密度布局
        self._big_wrap.setVisible(density == "compact")
        self._stats_wrap.setVisible(density != "compact")
        self._sep.setVisible(density != "compact")
        self._avatar.setVisible(density != "compact")
        self._detail.setVisible(density == "rich")
        self._credit_summary_label.setVisible(density != "compact")
        self._credit_toggle.setVisible(density != "compact")
        self._credit_expiry_label.setVisible(density != "compact")
        self._reset_credit_status_label.setVisible(density != "compact")
        self._big_credit_wrap.setVisible(density == "compact")
        self._big_credit_label.setVisible(True)
        self._big_credit_expiry_label.setVisible(density == "compact")
        self._big_credit_status_label.setVisible(density == "compact")
        for bar in (self._short_bar, self._weekly_bar):
            bar.setVisible(density != "compact")
        if density == "rich" and self.height() < 320:
            self.resize(self.width(), 320)

        # 主题切换只更新样式，不触发完整 _refresh（避免 usage 扫描/多次重绘造成卡顿）；
        # 进度条与大数字的颜色用缓存的快照立即重设
        if self._last_snap is not None:
            self._update_quota_display(self._last_snap)
            self._update_detail(self._last_snap)
            self._update_big_countdowns(self._last_snap)

            self._update_reset_credits(self._last_snap)
    def _cycle_theme(self) -> None:
        i = THEME_ORDER.index(self._theme_key)
        self._theme_key = THEME_ORDER[(i + 1) % len(THEME_ORDER)]
        self._state["theme"] = self._theme_key
        self._save_state()
        self._apply_theme()

    def _set_theme(self, key: str) -> None:
        if key == self._theme_key:
            return
        self._theme_key = key
        self._state["theme"] = key
        self._save_state()
        self._apply_theme()

    # ---------- 状态恢复与保存 ----------

    def _restore_geometry(self) -> None:
        size = self._state.get("size")
        if isinstance(size, list) and len(size) == 2:
            self.resize(max(MIN_SIZE[0], int(size[0])), max(MIN_SIZE[1], int(size[1])))
        else:
            self.resize(*DEFAULT_SIZE)
        pos = self._state.get("pos")
        if isinstance(pos, list) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 40, screen.bottom() - self.height() - 40)

    def _save_state(self) -> None:
        new_state = {
            "pos": [self.x(), self.y()],
            "size": [self.width(), self.height()],
            "account_index": self._account_index,
            "theme": self._theme_key,
            "reset_credit_expanded": self._credit_expanded,
        }
        if self._data_dir:
            new_state["dataDir"] = str(self._data_dir)
        if new_state == self._last_saved_state:
            return
        self._last_saved_state = new_state
        save_state(new_state)

    # ---------- 数据目录发现 ----------

    def _discover_data(self) -> None:
        saved = self._state.get("dataDir")
        found = find_data_dir(saved)
        if found:
            self._data_dir = found
            self._store = DataStore(found)
            self._status_label.setText(f"数据目录: {found.name}/")
            if hasattr(self, "_watcher"):
                self._configure_watchers()
            self._save_state()
        else:
            self._data_dir = None
            self._store = None
            self._status_label.setText("未找到 OpenCodex 数据目录")
            self._prompt_manual_select()

    def _prompt_manual_select(self) -> None:
        ret = QMessageBox.question(
            self, APP_NAME,
            "未找到 OpenCodex 数据目录。\n是否手动选择？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if ret == QMessageBox.Yes:
            d = QFileDialog.getExistingDirectory(self, "选择 .opencodex 目录", str(Path.home()))
            if d:
                p = Path(d)
                if all((p / f).exists() for f in REQUIRED_FILES):
                    self._data_dir = p
                    self._store = DataStore(p)
                    self._save_state()
                    self._refresh()
                    return
                QMessageBox.warning(self, APP_NAME, "该目录下缺少必要的数据文件。")

    # ---------- 账号切换 ----------

    def _prev_account(self) -> None:
        self._switch_account(-1)

    def _next_account(self) -> None:
        self._switch_account(1)

    def _switch_account(self, delta: int) -> None:
        if not self._accounts:
            return
        self._account_index = (self._account_index + delta) % len(self._accounts)
        self._save_state()
        self._refresh()

    # ---------- 刷新 ----------

    def _configure_watchers(self) -> None:
        if not self._data_dir:
            return
        directory = str(self._data_dir)
        desired_files = [str(self._data_dir / name) for name in WATCHED_FILES if (self._data_dir / name).exists()]
        current_files = self._watcher.files()
        if current_files:
            self._watcher.removePaths(current_files)
        current_dirs = self._watcher.directories()
        if current_dirs:
            self._watcher.removePaths(current_dirs)
        if desired_files:
            self._watcher.addPaths(desired_files)
        self._watcher.addPath(directory)

    def _on_watched_file_changed(self, path: str) -> None:
        self._watch_dirty.add(Path(path).name)
        self._watch_debounce.start(WATCH_DEBOUNCE_MS)

    def _on_watched_directory_changed(self, _path: str) -> None:
        self._watch_dirty.update(WATCHED_FILES)
        self._watch_debounce.start(WATCH_DEBOUNCE_MS)

    def _flush_watched_changes(self) -> None:
        dirty = set(self._watch_dirty)
        self._watch_dirty.clear()
        if not dirty or not self._store:
            return
        if "usage.jsonl" in dirty and not self._store.usage_changed():
            dirty.remove("usage.jsonl")
        if not dirty:
            return
        self._store.invalidate(*dirty)
        if "usage.jsonl" in dirty and self._store.usage_wait_ms() > 0:
            self._refresh()
            self._usage_deferred.start(self._store.usage_wait_ms())
        else:
            self._refresh(force_usage="usage.jsonl" in dirty)
        self._configure_watchers()

    def _update_quota_display(self, snap: Dict[str, Any]) -> None:
        if is_free_plan(snap.get("plan")):
            self._short_bar.set_unavailable()
            self._weekly_bar.set_unavailable()
        else:
            self._short_bar.set_value(snap["short_percent"], snap["short_reset"])
            self._weekly_bar.set_value(snap["weekly_percent"], snap["weekly_reset"])
        self._update_big_numbers(snap)

    def _refresh(self, force_usage: bool = False) -> None:
        if not self._store:
            return
        try:
            self._accounts = self._store.account_list()
            if self._account_index >= len(self._accounts):
                self._account_index = 0
            shown_id = self._accounts[self._account_index]["id"] if self._accounts else None
            snap = self._store.snapshot(shown_id, force_usage=force_usage)
        except Exception as e:
            self._status_label.setText(f"读取错误: {type(e).__name__}")
            return

        self._email_label.setText(snap["email"])
        plan = snap["plan"]
        accent = THEMES[self._theme_key]["accent"]
        muted = THEMES[self._theme_key]["muted"]
        dot_color = accent if snap["is_active"] else muted
        active_mark = (
            f" <span style='color:{accent}; font-weight:800;'>· 当前</span>"
            if snap["is_active"] else ""
        )
        self._plan_label.setText(
            f"<span style='color:{dot_color}; font-weight:600;'>●</span> {str(plan).upper()}{active_mark}"
        )

        self._update_quota_display(snap)
        self._update_detail(snap)

        t = snap["today"]
        self._req_label.setText(str(t.requests))
        self._tok_label.setText(f"{human_bytes(t.tokens_in)} / {human_bytes(t.tokens_out)}")
        self._cache_label.setText(human_bytes(t.tokens_cached))

        self._last_snap = snap
        self._update_big_countdowns(snap)

        self._update_reset_credits(snap)
        self._schedule_countdown_refresh()
        # 账号切换按钮：多账号才显示
        multi = len(self._accounts) > 1
        self._prev_btn.setVisible(multi)
        self._next_btn.setVisible(multi)

        self._status_label.setText(
            f"更新 {datetime.now().strftime('%H:%M:%S')} · {self._data_dir.name if self._data_dir else '—'}/"
        )

    def _schedule_countdown_refresh(self) -> None:
        if not hasattr(self, "_countdown_timer"):
            self._countdown_timer = QTimer(self)
            self._countdown_timer.setSingleShot(True)
            self._countdown_timer.timeout.connect(self._refresh_countdowns)
        timestamps: List[float] = []
        if self._last_snap:
            if not is_free_plan(self._last_snap.get("plan")):
                timestamps.extend(value for value in (
                    self._last_snap.get("short_reset"), self._last_snap.get("weekly_reset"),
                ) if isinstance(value, (int, float)) and value > time.time())
            timestamps.extend(item["expires_at"] for item in self._last_snap.get("reset_credit_details", []) if item.get("expires_at", 0) > time.time())
        delay = min((countdown_refresh_delay(value - time.time()) for value in timestamps), default=WATCH_HEALTH_MS)
        self._countdown_timer.start(delay)

    def _refresh_countdowns(self) -> None:
        self._short_bar.tick()
        self._weekly_bar.tick()
        if self._last_snap is not None:
            self._update_big_countdowns(self._last_snap)
            self._update_reset_credits(self._last_snap)
        self._schedule_countdown_refresh()

    # ---------- 交互 ----------

    def _update_big_numbers(self, snap: Dict[str, Any]) -> None:
        if is_free_plan(snap.get("plan")):
            for lbl in (self._big_short, self._big_weekly):
                lbl.setText("无额度")
                lbl.setStyleSheet(
                    f"color:{THEMES[self._theme_key]['muted']}; font-weight:800; font-size:22pt;"
                )
            return

        now = time.time()

        def _remain(p: Any, reset_ts: Any) -> int:
            if reset_ts and reset_ts <= now:
                return 100
            return max(0, min(100, 100 - int(p)))

        def _remain_color(r: int) -> str:
            if r < 20:
                return "#ef4444"
            if r < 50:
                return "#f59e0b"
            return THEMES[self._theme_key]["accent"]

        for lbl, pct, rts in (
            (self._big_short, snap["short_percent"], snap["short_reset"]),
            (self._big_weekly, snap["weekly_percent"], snap["weekly_reset"]),
        ):
            r = _remain(pct, rts)
            lbl.setText(f"{r}%")
            lbl.setStyleSheet(f"color:{_remain_color(r)}; font-weight:800; font-size:22pt;")

    def _update_big_countdowns(self, snap: Dict[str, Any]) -> None:
        if is_free_plan(snap.get("plan")):
            for label in self._big_reset_labels:
                label.clear()
            return
        for label, reset_ts, period in (
            (self._big_reset_labels[0], snap["short_reset"], 5 * 3600),
            (self._big_reset_labels[1], snap["weekly_reset"], 7 * 24 * 3600),
        ):
            label.setText(reset_countdown(reset_ts, period))

    def _update_reset_credits(self, snap: Dict[str, Any]) -> None:
        details = snap.get("reset_credit_details", [])
        try:
            credit_count = max(0, int(snap.get("reset_credits") or 0))
        except (TypeError, ValueError):
            credit_count = 0
        summary = "重置额度  暂无" if not credit_count else f"重置额度  {credit_count} 次"
        earliest = min(
            (item.get("expires_at") for item in details if item.get("expires_at") is not None),
            default=None,
        )
        date, remaining = format_credit_expiry_parts(earliest)
        expiry = f"最早到期  {date}"
        if remaining:
            expiry = f"{expiry} · {remaining}"
        status = format_reset_credit_status(
            snap.get("reset_credit_updated"),
            snap.get("reset_credit_failed"),
            str(snap.get("reset_credit_notice") or ""),
        )
        if status.startswith("最近同步 "):
            status = f"同步 {status.removeprefix('最近同步 ')}"
        self._credit_summary_label.setText(summary)
        self._credit_expiry_label.setText(expiry)
        self._reset_credit_status_label.setText(status)
        self._big_credit_label.setText(summary)
        self._big_credit_expiry_label.setText(expiry)
        self._big_credit_status_label.setText(status)
        has_details = bool(details)
        for toggle in (self._credit_toggle, self._big_credit_toggle):
            toggle.setEnabled(has_details)
            toggle.setText("⌃" if self._credit_expanded else "⌄")
            toggle.setToolTip("收起重置额度详情" if self._credit_expanded else "展开重置额度详情")
        if self._credit_expanded and has_details:
            self._credit_details_title.setText(f"额度明细  ·  {len(details)} 项")
            for index, (row, _number, date_label, remaining_label) in enumerate(self._credit_detail_rows):
                if index < len(details):
                    date, remaining = format_credit_expiry_parts(details[index].get("expires_at"))
                    date_label.setText(date)
                    remaining_label.setText(remaining)
                    row.setVisible(True)
                else:
                    row.setVisible(False)
        else:
            for row, _number, date_label, remaining_label in self._credit_detail_rows:
                date_label.setText("")
                remaining_label.setText("")
                row.setVisible(False)
        show_details = self._credit_expanded and has_details
        self._credit_details.setVisible(show_details)
        self._ensure_credit_details_fit(show_details)

    def _ensure_credit_details_fit(self, expanded: bool) -> None:
        minimum_height = MIN_SIZE[1]
        if expanded:
            minimum_height = max(minimum_height, self.minimumSizeHint().height())
        self.setMinimumHeight(minimum_height)
        if expanded and self.height() < minimum_height:
            self.resize(self.width(), minimum_height)

    def _toggle_credit_details(self) -> None:
        if not self._last_snap or not self._last_snap.get("reset_credit_details"):
            return
        self._credit_expanded = not self._credit_expanded
        self._update_reset_credits(self._last_snap)
        self._save_state()

    def _update_detail(self, snap: Dict[str, Any]) -> None:
        if not self._detail.isVisible():
            return
        top_models = sorted(snap["today"].models.items(), key=lambda kv: -kv[1])[:3]
        model_txt = " · ".join(f"{m}×{n}" for m, n in top_models) or "无"
        lines = [
            f"模型分布: {model_txt}",
            f"失败请求: {snap['today'].errors} · 账号 {self._account_index + 1}/{max(1, len(self._accounts))}",
            f"主题: {THEMES[self._theme_key]['title']}（右键切换）",
        ]
        for lbl, txt in zip(self._detail_lines, lines):
            lbl.setText(txt)

    def _toggle_pin(self, checked: bool) -> None:
        flags = self.windowFlags()
        flags = flags | Qt.WindowStaysOnTopHint if checked else flags & ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self._pin_btn.blockSignals(True)
        self._pin_btn.setChecked(checked)
        self._pin_btn.blockSignals(False)
        self._pin_btn.setText("📌" if checked else "📍")
        self._pin_btn.setToolTip("取消置顶" if checked else "置顶窗口")
        self.show()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        self._save_state()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_state"):
            self._save_state()

    def contextMenuEvent(self, event) -> None:
        t = THEMES[self._theme_key]
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {t['bg']}; border: 1px solid {t['border']};
                border-radius: 8px; padding: 4px; color: {t['fg']};
            }}
            QMenu::item {{ padding: 6px 20px 6px 12px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {t['hover']}; }}
        """)

        theme_menu = menu.addMenu("主题")
        for key in THEME_ORDER:
            act = QAction(THEMES[key]["title"], self, checkable=True)
            act.setChecked(key == self._theme_key)
            act.triggered.connect(lambda checked=False, k=key: self._set_theme(k))
            theme_menu.addAction(act)

        pin_action = QAction("置顶", self, checkable=True)
        pin_action.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        pin_action.toggled.connect(self._toggle_pin)
        menu.addAction(pin_action)

        menu.addSeparator()

        dash = QAction("打开 Dashboard", self)
        dash.triggered.connect(lambda: os.startfile("http://127.0.0.1:10100"))
        menu.addAction(dash)

        refresh = QAction("立即刷新", self)
        refresh.triggered.connect(self._refresh)
        menu.addAction(refresh)

        rescan = QAction("重新扫描数据目录", self)
        rescan.triggered.connect(self._discover_data)
        menu.addAction(rescan)

        menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        menu.exec(QCursor.pos())

    def closeEvent(self, event) -> None:
        self._save_state()
        # Qt.Tool windows do not necessarily count as the application's last
        # primary window. Exit explicitly so the hidden event loop (and the
        # PyInstaller one-file launcher waiting for it) cannot remain alive.
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()


# ──────────────────────────────── 入口 ────────────────────────────────

def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))

    card = UsageCard()
    card.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
