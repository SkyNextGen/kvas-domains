#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common utilities for KVAS reporting.

Used by:
- src/report.py (orchestrator)
- src/report_md.py (Markdown report formatter)
- src/report_tg.py (Telegram formatter)

IO contract:
- reads dist/state.json + dist/stats.json
- writes dist/stats.json (append)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

STATE_JSON = DIST / "state.json"
STATS_JSON = DIST / "stats.json"
REPORT_MD = DIST / "report.md"
TG_MESSAGE = DIST / "tg_message.txt"
TG_ALERT = DIST / "tg_alert.txt"

MSK = timezone(timedelta(hours=3))
MONTHS_RU = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]


# ---------------- helpers ----------------

def load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj
    except Exception:
        return default


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_dt_utc(s: str) -> datetime:
    """
    Accepts:
      - '2026-02-15 13:06:41 UTC'
      - ISO with Z / +00:00
      - ISO without tz (treated as UTC)
    """
    raw = (s or "").strip()
    if not raw:
        return datetime.now(timezone.utc)

    # 'YYYY-MM-DD HH:MM:SS UTC'
    if raw.endswith(" UTC"):
        core = raw[:-4].strip()
        try:
            dt = datetime.strptime(core, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return datetime.now(timezone.utc)

    # ISO formats
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def fmt_build_time_msk(build_time_utc: str) -> str:
    dt = parse_dt_utc(build_time_utc).astimezone(MSK)
    dd = f"{dt.day:02d}"
    mm = MONTHS_RU[dt.month - 1]
    return f"{dd} {mm} {dt.hour:02d}:{dt.minute:02d} МСК"


def fmt_tg_date_time(build_time_utc: str) -> str:
    dt = parse_dt_utc(build_time_utc).astimezone(MSK)
    dd = f"{dt.day:02d}"
    mm = MONTHS_RU[dt.month - 1]
    return f"{dd} {mm} {dt.hour:02d}:{dt.minute:02d} МСК"


def pct(part: int, total: int) -> float:
    if not total:
        return 0.0
    return (100.0 * float(part) / float(total))


def limit_badge(final_total: int, max_lines: int, threshold: int) -> str:
    if not max_lines:
        return "—"
    p = pct(final_total, max_lines)
    if final_total >= max_lines:
        return f"🧨 ЛИМИТ ({final_total}/{max_lines}, {p:.1f}%)"
    if final_total >= threshold:
        return f"⚠️ Почти лимит ({final_total}/{max_lines}, {p:.1f}%)"
    return f"✅ OK ({final_total}/{max_lines}, {p:.1f}%)"


def diff_lists(prev: List[str], curr: List[str]) -> Tuple[List[str], List[str]]:
    p = set(prev or [])
    c = set(curr or [])
    added = sorted(list(c - p))
    removed = sorted(list(p - c))
    return added, removed


def short_hash(h: str) -> str:
    h = (h or "").strip()
    if len(h) < 10:
        return h or "—"
    return f"{h[:4]}…{h[-4:]}"


def status_emoji(status: str) -> str:
    s = (status or "").upper()
    if s == "OK":
        return "🟢 OK"
    if s == "EMPTY":
        return "🟡 ПУСТО"
    if s == "FAIL":
        return "🔴 FAIL"
    return f"⚪ {s or '—'}"


def classify_severity(state: Dict) -> str:
    warns = state.get("warnings", []) or []
    failed = state.get("failed_categories", []) or []
    empty = state.get("empty_categories", []) or []

    total = int(state.get("final_total", 0) or 0)
    max_lines = int(state.get("max_lines", 0) or 0)
    threshold = int(state.get("near_limit_threshold", 0) or 0)
    trunc = int(state.get("truncated", 0) or 0)
    bad = int(state.get("bad_output_lines", 0) or 0)
    v2_fail = int(state.get("v2fly_fail", 0) or 0)
    p = pct(total, max_lines) if max_lines else 0.0

    if v2_fail > 0 or bad > 0 or trunc > 0 or p >= 96.0 or len(failed) > 0:
        return "ОШИБКА"
    if len(empty) > 0 or len(warns) > 0 or total >= threshold or p >= 85.0:
        return "ПРЕДУПРЕЖДЕНИЕ"
    return "ОК"


def ensure_state() -> Dict:
    """Load dist/state.json, and if missing/broken create a minimal fallback.

    This prevents workflow crashes when build.py fails or dist is empty.
    """
    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict) or not state:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        state = {
            "build_time_utc": now,
            "repo": "unknown/unknown",
            "output": "dist/inside-kvas.lst",
            "max_lines": 3000,
            "near_limit_threshold": 2900,
            "sha256_final": "",
            "itdog_domains": [],
            "v2fly_extras": [],
            "final_domains": [],
            "itdog_total": 0,
            "v2fly_total": 0,
            "final_total": 0,
            "truncated": 0,
            "bad_output_lines": 0,
            "v2fly_ok": 0,
            "v2fly_fail": 0,
            "v2fly_categories": [],
            "v2fly_per_category": {},
            "warnings": ["state.json отсутствует/повреждён"],
            "failed_categories": [],
            "empty_categories": [],
            "prev": {"itdog_domains": [], "v2fly_extras": [], "final_domains": []},
        }
        dump_json(STATE_JSON, state)
    return state


def append_stats(state: Dict) -> Tuple[List[Dict], Optional[Dict]]:
    stats = load_json(STATS_JSON, [])
    if not isinstance(stats, list):
        stats = []
    prev = stats[-1] if stats and isinstance(stats[-1], dict) else None

    rec = {
        "build_time_utc": str(state.get("build_time_utc", "")),
        "final_total": int(state.get("final_total", 0) or 0),
        "itdog_total": int(state.get("itdog_total", 0) or 0),
        "v2fly_total": int(state.get("v2fly_total", 0) or 0),
        "truncated": int(state.get("truncated", 0) or 0),
        "bad_output_lines": int(state.get("bad_output_lines", 0) or 0),
        "v2fly_ok": int(state.get("v2fly_ok", 0) or 0),
        "v2fly_fail": int(state.get("v2fly_fail", 0) or 0),
        "warnings": list(state.get("warnings", []) or []),
        "failed_categories": list(state.get("failed_categories", []) or []),
        "empty_categories": list(state.get("empty_categories", []) or []),
        "sha256_final": str(state.get("sha256_final", "")),
    }

    stats.append(rec)
    # keep last 120 runs
    if len(stats) > 120:
        stats = stats[-120:]

    dump_json(STATS_JSON, stats)
    return stats, prev


def trend_eval(prev_rec: Optional[Dict], curr: Dict) -> Dict:
    if not prev_rec:
        return {
            "final_delta": None,
            "itdog_delta": None,
            "v2fly_delta": None,
            "v2fly_fail_delta": None,
        }

    def d(key: str) -> int:
        return int(curr.get(key, 0) or 0) - int(prev_rec.get(key, 0) or 0)

    return {
        "final_delta": d("final_total"),
        "itdog_delta": d("itdog_total"),
        "v2fly_delta": d("v2fly_total"),
        "v2fly_fail_delta": d("v2fly_fail"),
    }


def repo_report_url(repo: str) -> str:
    repo = (repo or "").strip()
    if not repo or repo == "unknown/unknown":
        return ""
    return f"https://github.com/{repo}/blob/main/dist/report.md"
