#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from report_common import (
    TG_MESSAGE,
    TG_ALERT,
    STATS_JSON,
    STATE_JSON,
    load_json,
    pct,
    short_hash,
    classify_severity,
    fmt_tg_date_time,
    repo_report_url,
    trend_eval,
)


def tg_header(sev: str) -> List[str]:
    # Unified header for all Telegram notifications from GitHub Actions build system
    if sev == "ОК":
        src = "🟢 GitHub Actions"
        tag = "ℹ️ INFO"
        pr = "🟢 ПРИОРИТЕТ: НИЗКИЙ"
    elif sev == "ПРЕДУПРЕЖДЕНИЕ":
        src = "🟡 GitHub Actions"
        tag = "⚠️ WARNING"
        pr = "🟡 ПРИОРИТЕТ: СРЕДНИЙ"
    else:
        src = "🔴 GitHub Actions"
        tag = "🚨 CRITICAL"
        pr = "🔴 ПРИОРИТЕТ: ВЫСОКИЙ"
    return [
        "📦 BUILD SYSTEM",
        src,
        "━━━━━━━━━━━━━━━━━━",
        tag,
        "",
        pr,
        "",
    ]


def tg_problems_lines(state: Dict) -> List[str]:
    lines: List[str] = []
    failed = state.get("failed_categories") or []
    empty = state.get("empty_categories") or []

    for f in failed:
        name = str(f)
        if "HTTP" in name:
            # "tiktok (HTTP 404)" -> "🔴 tiktok — 404"
            cat = name.split("(", 1)[0].strip()
            tail = name.split("HTTP", 1)[1].strip().strip("()")
            code = tail.split()[0]
            lines.append(f"🔴 {cat} — {code}")
        else:
            cat = name.split("(", 1)[0].strip()
            lines.append(f"🔴 {cat} — ошибка")

    for e in empty:
        lines.append(f"🟡 {e} — пусто")

    max_lines = int(state.get("max_lines", 3000))
    threshold = int(state.get("near_limit_threshold", 2900))
    total = int(state.get("final_total", 0))
    p = pct(total, max_lines)
    if total >= threshold or p >= 96.0:
        lines.append("🟠 Почти лимит")

    trunc = int(state.get("truncated", 0))
    if trunc > 0:
        lines.append(f"🔴 Обрезка — {trunc}")

    bad = int(state.get("bad_output_lines", 0))
    if bad > 0:
        lines.append(f"🔴 Некорректные строки — {bad}")

    return lines


def format_tg(state: Dict, stats: List[Dict], prev_rec: Optional[Dict]) -> Tuple[str, str]:
    sev = classify_severity(state)
    date_s, time_s = fmt_tg_date_time(str(state.get("build_time_utc", "")))

    max_lines = int(state.get("max_lines", 3000))
    total = int(state.get("final_total", 0))
    p = pct(total, max_lines)
    rest = max_lines - total

    sha = short_hash(str(state.get("sha256_final", "")))
    url = repo_report_url(str(state.get("repo", "")))

    avg7, delta, deviation, eval_line = trend_eval(stats, prev_rec, total)
    problems = tg_problems_lines(state)

    hdr = tg_header(sev)

    badge = "🟢" if p < 85.0 else ("🟡" if p < 96.0 else "🔴")
    msg = []
    msg.extend(hdr)

    if not problems:
        msg += ["🚀 Сборка завершена", "🟢 Система стабильна", ""]
    else:
        msg += ["⚠️ Есть замечания", "", "Проблемы:"]
        msg += [f"- {x}" for x in problems]
        msg += [""]

    msg += [
        f"🗓 {date_s}",
        f"🕒 {time_s}",
        "",
        f"📊 {total} / {max_lines} ({p:.1f}%) {badge}",
        "",
        "📈 ТРЕНД",
        f"Среднее (7): {avg7}",
        f"Δ к прошлой: {delta:+d}",
        eval_line,
        "",
        "✅ Замечаний нет" if not problems else "⚠️ Есть замечания",
        "",
        f"🔐 sha256: {sha}",
    ]
    if url:
        msg.append(f"🔗 Отчёт: {url}")
    return "\n".join(msg).rstrip() + "\n", ""


def main() -> int:
    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict):
        state = {}
    stats = load_json(STATS_JSON, [])
    if not isinstance(stats, list):
        stats = []
    prev_rec = stats[-2] if len(stats) >= 2 and isinstance(stats[-2], dict) else None

    tg_msg, tg_alert = format_tg(state, stats, prev_rec)
    TG_MESSAGE.write_text(tg_msg, encoding="utf-8")

    if tg_alert.strip():
        TG_ALERT.write_text(tg_alert, encoding="utf-8")
    else:
        TG_ALERT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
