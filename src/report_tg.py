#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from report_common import (
    TG_MESSAGE,
    TG_ALERT,
    STATE_JSON,
    STATS_JSON,
    load_json,
    pct,
    short_hash,
    classify_severity,
    fmt_tg_date_time,
    repo_report_url,
    trend_eval,
)


# ------------------------------------------------------
# Header
# ------------------------------------------------------

def tg_header(sev: str) -> List[str]:
    """
    Header block for Telegram notification.
    Uses 'СТАТУС СБОРКИ' instead of 'ПРИОРИТЕТ'.
    """

    if sev == "ОК":
        src = "🟢 GitHub Actions"
        tag = "🧩 INFO"
        status_line = "🟢 СТАТУС СБОРКИ: ОК"
    elif sev == "ПРЕДУПРЕЖДЕНИЕ":
        src = "🟠 GitHub Actions"
        tag = "⚠️ WARNING"
        status_line = "🟠 СТАТУС СБОРКИ: ПРЕДУПРЕЖДЕНИЕ"
    else:
        src = "🔴 GitHub Actions"
        tag = "🔥 CRITICAL"
        status_line = "🔴 СТАТУС СБОРКИ: ОШИБКА"

    return [
        "📦 BUILD SYSTEM",
        src,
        "━━━━━━━━━━━━━━━━━━",
        tag,
        "",
        status_line,
        "",
    ]


# ------------------------------------------------------
# Problems block
# ------------------------------------------------------

def tg_problems_lines(state: Dict) -> List[str]:
    lines: List[str] = []

    failed = state.get("failed_categories") or []
    empty = state.get("empty_categories") or []

    for f in failed:
        name = str(f)
        if "HTTP" in name:
            cat = name.split("(", 1)[0].strip()
            tail = name.split("HTTP", 1)[1].strip().strip("()")
            code = tail.split()[0]
            lines.append(f"❌ {cat} — HTTP {code}")
        else:
            cat = name.split("(", 1)[0].strip()
            lines.append(f"❌ {cat} — ошибка")

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
        lines.append(f"✂️ Обрезка — {trunc}")

    bad = int(state.get("bad_output_lines", 0))
    if bad > 0:
        lines.append(f"⚠️ Некорректные строки — {bad}")

    return lines


# ------------------------------------------------------
# Trend visual: make it логично по delta (к прошлой)
# ------------------------------------------------------

def trend_visual(delta: int) -> Tuple[str, str]:
    """
    Trend label/icon based strictly on Δ to previous run:
      delta > 0 -> Рост
      delta < 0 -> Падение
      delta == 0 -> Стабильно
    """
    if delta > 0:
        return "📈", "Рост"
    if delta < 0:
        return "📉", "Падение"
    return "➡️", "Стабильно"


# ------------------------------------------------------
# Main formatter
# ------------------------------------------------------

def format_tg(
    state: Dict,
    stats: List[Dict],
    prev_rec: Optional[Dict],
) -> Tuple[str, str]:

    sev = classify_severity(state)
    date_s, time_s = fmt_tg_date_time(str(state.get("build_time_utc", "")))

    max_lines = int(state.get("max_lines", 3000))
    total = int(state.get("final_total", 0))
    p = pct(total, max_lines)

    sha = short_hash(str(state.get("sha256_final", "")))
    url = repo_report_url(str(state.get("repo", "")))

    avg7, delta, deviation, eval_line = trend_eval(stats, prev_rec, total)
    icon, label = trend_visual(delta)

    problems = tg_problems_lines(state)
    hdr = tg_header(sev)

    badge = "🟢" if p < 85.0 else ("🟡" if p < 96.0 else "🔴")

    msg: List[str] = []
    msg.extend(hdr)

    # Status text
    if not problems:
        msg += [
            "🚀 Сборка завершена успешно",
            "🟢 Система стабильна",
            "",
        ]
    else:
        msg += [
            "⚠️ Обнаружены замечания",
            "",
            "🔎 Проблемы:",
        ]
        msg += [f"• {x}" for x in problems]
        msg += [""]

    # Date/time
    msg += [
        f"🗓 Дата: {date_s}",
        f"🕒 Время: {time_s}",
        "",
    ]

    # Usage
    msg += [
        "📊 Использование лимита:",
        f"{total} / {max_lines} ({p:.1f}%) {badge}",
        "",
    ]

    # Trend (логично по delta)
    msg += [
        "📈 ТРЕНД ЗА 7 ЗАПУСКОВ",
        f"Среднее: {avg7}",
        f"Δ к прошлой: {delta:+d}",
        f"{icon} {label}",
        "",
    ]

    # Final status
    if not problems:
        msg.append("✅ Замечаний нет")
    else:
        msg.append("⚠️ Требуется внимание")

    msg += [
        "",
        f"🔐 sha256: {sha}",
    ]

    if url:
        msg.append(f"🔗 Отчёт: {url}")

    tg_message = "\n".join(msg).rstrip() + "\n"

    # Alerts disabled (kept for compatibility)
    tg_alert = ""

    return tg_message, tg_alert


# ------------------------------------------------------
# Standalone execution
# ------------------------------------------------------

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
