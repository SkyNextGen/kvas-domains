#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common helpers extracted from the original report.py (STRICT 1:1 logic).

This module MUST keep behavior identical to the original:
- pct rounding
- limit_badge thresholds
- diff_lists direction
- severity classification rules
- stats.json schema and retention
- trend evaluation messages
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
    raw = (s or "").strip()
    if not raw:
        return datetime.now(timezone.utc)

    # 'YYYY-MM-DD HH:MM:SS UTC'
    if raw.endswith(" UTC"):
        core = raw[:-4].strip()
        try:
            return datetime.strptime(core, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
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
    dt_msk = parse_dt_utc(build_time_utc).astimezone(MSK)
    m = MONTHS_RU[dt_msk.month - 1]
    return f"{dt_msk.day:02d} {m} {dt_msk.year}, {dt_msk:%H:%M} МСК"


def fmt_tg_date_time(build_time_utc: str) -> Tuple[str, str]:
    dt_msk = parse_dt_utc(build_time_utc).astimezone(MSK)
    return dt_msk.strftime("%d.%m.%Y"), dt_msk.strftime("%H:%M:%S МСК")


def pct(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return round(n / d * 100.0, 1)


def limit_badge(p: float) -> str:
    if p >= 96.0:
        return "🔴"
    if p >= 85.0:
        return "🟡"
    return "🟢"


def diff_lists(prev: List[str], curr: List[str]) -> Tuple[List[str], List[str]]:
    p = set(prev or [])
    c = set(curr or [])
    return sorted(c - p), sorted(p - c)


def short_hash(h: str) -> str:
    h = (h or "").strip()
    if len(h) < 10:
        return h or "—"
    return f"{h[:4]}…{h[-4:]}"


def status_emoji(status: str) -> str:
    s = (status or "").upper()
    if s == "OK":
        return "🟢"
    if s == "EMPTY":
        return "🟡"
    if s == "FAIL":
        return "🔴"
    return "—"


def classify_severity(state: Dict) -> str:
    """
    Returns: 'ОК' / 'ПРЕДУПРЕЖДЕНИЕ' / 'ОШИБКА'
    """
    max_lines = int(state.get("max_lines", 3000))
    threshold = int(state.get("near_limit_threshold", 2900))
    total = int(state.get("final_total", 0))
    p = pct(total, max_lines)

    v2_fail = int(state.get("v2fly_fail", 0))
    bad = int(state.get("bad_output_lines", 0))
    trunc = int(state.get("truncated", 0))
    failed = state.get("failed_categories") or []
    empty = state.get("empty_categories") or []
    warns = state.get("warnings") or []

    if v2_fail > 0 or bad > 0 or trunc > 0 or p >= 96.0 or len(failed) > 0:
        return "ОШИБКА"
    if len(empty) > 0 or len(warns) > 0 or total >= threshold or p >= 85.0:
        return "ПРЕДУПРЕЖДЕНИЕ"
    return "ОК"


def append_stats(state: Dict) -> Tuple[List[Dict], Optional[Dict]]:
    stats = load_json(STATS_JSON, [])
    if not isinstance(stats, list):
        stats = []
    prev = stats[-1] if stats and isinstance(stats[-1], dict) else None

    rec = {
        "ts_utc": state.get("build_time_utc"),
        "total": int(state.get("final_total", 0)),
        "severity": classify_severity(state),
    }
    stats.append(rec)
    stats = stats[-400:]
    dump_json(STATS_JSON, stats)
    return stats, prev


def trend_eval(stats: List[Dict], prev_rec: Optional[Dict], curr_total: int) -> Tuple[int, int, int, str]:
    totals = [int(x.get("total", 0)) for x in stats[-7:] if isinstance(x, dict)]
    avg7 = int(round(sum(totals) / len(totals))) if totals else curr_total

    prev_total = int(prev_rec.get("total", 0)) if isinstance(prev_rec, dict) else None
    delta = (curr_total - prev_total) if prev_total is not None else 0
    deviation = curr_total - avg7

    if avg7 > 0 and curr_total >= avg7 * 2:
        eval_line = "📈 Рост (выше среднего ×2)"
    else:
        tol = max(10, int(round(avg7 * 0.01)))
        if abs(deviation) <= tol:
            eval_line = "➡ Стабильно"
        elif deviation > 0:
            eval_line = "📈 Рост"
        else:
            eval_line = "📉 Падение"

    return avg7, delta, deviation, eval_line


def repo_report_url(repo: str) -> str:
    r = (repo or "").strip()
    if not r or "/" not in r:
        return ""
    return f"https://github.com/{r}/blob/main/dist/report.md"
