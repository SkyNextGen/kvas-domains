#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"

STATE_JSON = DIST_DIR / "state.json"
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATS_JSON = DIST_DIR / "stats.json"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def diff_sets(prev: Set[str], curr: Set[str]) -> Tuple[List[str], List[str]]:
    added = sorted(curr - prev)
    removed = sorted(prev - curr)
    return added, removed


def format_change(added: int, removed: int) -> str:
    return f"+{added} / -{removed}"


def format_top_list(items: List[str], limit: int = 20) -> str:
    if not items:
        return "- none"
    return "\n".join([f"{i}. {x}" for i, x in enumerate(items[:limit], 1)])


def short_hash(h: str) -> str:
    if not h or len(h) < 8:
        return h or ""
    return f"{h[:4]}...{h[-4:]}"


def now_msk_str() -> str:
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    return msk.strftime("%Y-%m-%d %H:%M МСК")


def make_v2fly_table_rows(cats: List[str], per_cat: Dict[str, Dict]) -> str:
    rows: List[str] = []
    for cat in cats:
        d = per_cat.get(cat, {})
        rows.append(
            f"| {cat} | {int(d.get('valid_domains', 0))} | {int(d.get('extras_added', 0))} | "
            f"{int(d.get('invalid_lines', 0))} | {int(d.get('skipped_directives', 0))} | {d.get('status', 'FAIL')} |"
        )
    return "\n".join(rows)


def append_stats(total: int, itdog: int, v2fly: int, warnings: List[str]) -> Optional[int]:
    """
    Возвращает delta_total (текущий total - предыдущий total) или None, если предыдущей записи нет.
    """
    data = load_json(STATS_JSON, [])
    if not isinstance(data, list):
        data = []

    prev = data[-1] if data else None
    prev_total = prev.get("total") if isinstance(prev, dict) else None

    rec = {
        "ts_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total": total,
        "itdog": itdog,
        "v2fly": v2fly,
        "warnings": warnings,
    }
    data.append(rec)
    data = data[-200:]
    STATS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if isinstance(prev_total, int):
        return total - prev_total
    return None


def build_tg_message(ts_msk: str, total: int, delta_total: Optional[int], has_warnings: bool) -> str:
    delta_str = f"{delta_total:+d}" if delta_total is not None else "—"
    warn_line = "⚠️ Есть предупреждения" if has_warnings else "✅ Без предупреждений"
    return (
        "📦 KVAS Domains — сборка завершена\n"
        f"🕒 {ts_msk}\n\n"
        f"📌 Итоговых доменов: {total} (Δ {delta_str})\n"
        f"{warn_line}\n"
    )


def build_tg_alert(ts_msk: str, warnings: List[str]) -> str:
    if not warnings:
        return ""
    body = "\n".join([f"- {w}" for w in warnings])
    return (
        "⚠️ KVAS Domains — предупреждения\n"
        f"🕒 {ts_msk}\n\n"
        f"{body}\n"
    )


def main() -> int:
    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict):
        raise SystemExit("Bad state.json")

    prev = state.get("prev", {}) if isinstance(state.get("prev", {}), dict) else {}

    repo = state.get("repo", "unknown/unknown")
    output = state.get("output", "dist/inside-kvas.lst")
    max_lines = int(state.get("max_lines", 3000))
    threshold = int(state.get("near_limit_threshold", 2900))

    itdog_set = set(state.get("itdog_domains", []) or [])
    v2fly_set = set(state.get("v2fly_extras", []) or [])
    final_set = set(state.get("final_domains", []) or [])

    prev_itdog = set(prev.get("itdog_domains", []) or [])
    prev_v2fly = set(prev.get("v2fly_extras", []) or [])
    prev_final = set(prev.get("final_domains", []) or [])

    itdog_added, itdog_removed = diff_sets(prev_itdog, itdog_set)
    v2fly_added, v2fly_removed = diff_sets(prev_v2fly, v2fly_set)
    final_added, final_removed = diff_sets(prev_final, final_set)

    itdog_change = format_change(len(itdog_added), len(itdog_removed))
    v2fly_change = format_change(len(v2fly_added), len(v2fly_removed))
    final_change = format_change(len(final_added), len(final_removed))

    v2fly_ok = int(state.get("v2fly_ok", 0))
    v2fly_fail = int(state.get("v2fly_fail", 0))

    truncated_count = int(state.get("truncated", 0))
    bad_output_lines = int(state.get("bad_output_lines", 0))
    truncated_yesno = str(state.get("truncated_yesno", "NO"))

    build_time_utc = str(state.get("build_time_utc", "")).replace(" UTC", "")
    sha = short_hash(str(state.get("sha256_final", "")))

    warnings = state.get("warnings", []) or []
    if not isinstance(warnings, list):
        warnings = []

    failed_categories = state.get("failed_categories", []) or []
    if not isinstance(failed_categories, list):
        failed_categories = []

    empty_categories = state.get("empty_categories", []) or []
    if not isinstance(empty_categories, list):
        empty_categories = []

    final_total = len(final_set)
    itdog_total = len(itdog_set)
    v2fly_total = len(v2fly_set)

    usage_pct = round((final_total / max_lines) * 100, 1) if max_lines else 0.0
    near_limit = "YES" if final_total >= threshold else "NO"

    cats = state.get("v2fly_categories", []) or []
    per_cat = state.get("v2fly_per_category", {}) or {}
    if not isinstance(cats, list):
        cats = []
    if not isinstance(per_cat, dict):
        per_cat = {}

    table_rows = make_v2fly_table_rows(cats, per_cat)

    # ---- Warnings inline (без “двух none”)
    failed_inline = "none" if not failed_categories else ", ".join(failed_categories)
    empty_inline = "none" if not empty_categories else ", ".join(empty_categories)

    report = f"""# KVAS domains build report

Build time (UTC): {build_time_utc}
Repo: {repo}
Output: {output}
Max lines: {max_lines}

## Summary
- itdog:
  - total: {itdog_total}
  - change vs prev: {itdog_change}
- v2fly (extras only: not in itdog):
  - total: {v2fly_total}
  - change vs prev: {v2fly_change}
  - lists: ok={v2fly_ok}, fail={v2fly_fail}
- final output:
  - total: {final_total}
  - change vs prev: {final_change}
  - truncated: {truncated_count}

## Limit status
- usage: {final_total} / {max_lines} ({usage_pct}%)
- near limit: {near_limit} (threshold: {threshold})

## itdog changes vs prev (top 20)
### Added
{format_top_list(itdog_added, 20)}
### Removed
{format_top_list(itdog_removed, 20)}

## v2fly extras changes vs prev (top 20)
### Added
{format_top_list(v2fly_added, 20)}
### Removed
{format_top_list(v2fly_removed, 20)}

## final output changes vs prev (top 20)
### Added
{format_top_list(final_added, 20)}
### Removed
{format_top_list(final_removed, 20)}

## v2fly per-category stats
| category | valid_domains | extras_added | invalid_lines | skipped_directives | status |
|---|---:|---:|---:|---:|---|
{table_rows}

Notes:
- `valid_domains` = домены, извлечённые из категории после фильтра (full:/domain:/голые домены)
- `extras_added` = домены, которые реально попали в хвост (не пересекаются с itdog)
- `skipped_directives` = include:/regexp:/keyword:/etc (мы их не разворачиваем)

## Warnings
- Failed categories (download/parse errors): {failed_inline}
- Empty categories (0 valid domains): {empty_inline}
- Bad output lines: {bad_output_lines}
- Truncated output: {truncated_yesno}

## Hashes
- sha256(final): {sha}
"""

    REPORT_OUT.write_text(report, encoding="utf-8")

    # ---- stats + telegram texts
    delta_total = append_stats(final_total, itdog_total, v2fly_total, warnings)
    ts_msk = now_msk_str()

    TG_MESSAGE_OUT.write_text(
        build_tg_message(ts_msk, final_total, delta_total, has_warnings=bool(warnings)),
        encoding="utf-8",
    )

    alert_text = build_tg_alert(ts_msk, warnings)
    if alert_text:
        TG_ALERT_OUT.write_text(alert_text, encoding="utf-8")
    else:
        TG_ALERT_OUT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
