#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KVAS Telegram message generator (dist/tg_message.txt + dist/tg_alert.txt)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from report_common import *  # noqa: F401,F403


def tg_header(sev: str) -> List[str]:
    # Unified header for all Telegram notifications from GitHub Actions build system
    if sev == "ОК":
        src = "🟢 GitHub Actions"
        tag = "ℹ️ INFO"
        pr = "ПРИОРИТЕТ: НИЗКИЙ"
    elif sev == "ПРЕДУПРЕЖДЕНИЕ":
        src = "🟠 GitHub Actions"
        tag = "⚠️ WARNING"
        pr = "ПРИОРИТЕТ: СРЕДНИЙ"
    else:
        src = "🔴 GitHub Actions"
        tag = "🧨 ERROR"
        pr = "ПРИОРИТЕТ: ВЫСОКИЙ"
    return [
        "📦 BUILD SYSTEM",
        src,
        "━━━━━━━━━━━━━━━━━━",
        tag,
        "",
        pr,
        "",
    ]


def format_tg(state: Dict, stats: List[Dict], prev_rec: Optional[Dict]) -> Tuple[str, str]:
    repo = str(state.get("repo", "unknown/unknown"))
    build_time_s = fmt_tg_date_time(str(state.get("build_time_utc", "")))

    final_total = int(state.get("final_total", 0) or 0)
    max_lines = int(state.get("max_lines", 0) or 0)
    threshold = int(state.get("near_limit_threshold", 0) or 0)

    itdog_total = int(state.get("itdog_total", 0) or 0)
    v2fly_total = int(state.get("v2fly_total", 0) or 0)

    trunc = int(state.get("truncated", 0) or 0)
    bad = int(state.get("bad_output_lines", 0) or 0)

    v2_ok = int(state.get("v2fly_ok", 0) or 0)
    v2_fail = int(state.get("v2fly_fail", 0) or 0)

    warns = state.get("warnings", []) or []
    failed = state.get("failed_categories", []) or []
    empty = state.get("empty_categories", []) or []

    sev = classify_severity(state)
    trend = trend_eval(prev_rec, state)

    def fdelta(x):
        if x is None:
            return "—"
        if x > 0:
            return f"+{x}"
        return str(x)

    report_url = repo_report_url(repo)
    report_line = report_url if report_url else "(report.md link недоступен)"

    # Base message (always sent)
    msg_lines = []
    msg_lines += tg_header(sev)
    msg_lines += [
        f"🕒 {build_time_s}",
        f"📌 Repo: {repo}",
        "",
        "📊 Итоги:",
        f"• final: {final_total} (Δ {fdelta(trend.get('final_delta'))})",
        f"• itdog: {itdog_total} (Δ {fdelta(trend.get('itdog_delta'))})",
        f"• v2fly: {v2fly_total} (Δ {fdelta(trend.get('v2fly_delta'))})",
        f"• лимит: {limit_badge(final_total, max_lines, threshold)}",
        "",
        "✅ Проверки:",
        f"• v2fly categories: OK={v2_ok} / FAIL={v2_fail}",
        f"• bad lines: {bad}",
        f"• truncated: {trunc}",
        "",
        f"📝 Report: {report_line}",
    ]

    tg_message = "\n".join(msg_lines).rstrip() + "\n"

    # Alert message (only if WARNING/ERROR)
    alert_lines: List[str] = []
    if sev != "ОК":
        alert_lines += tg_header(sev)
        alert_lines += [
            f"🕒 {build_time_s}",
            f"📌 Repo: {repo}",
            "",
        ]
        if failed:
            alert_lines.append("❌ Failed categories:")
            alert_lines += [f"• {c}" for c in failed[:50]]
            if len(failed) > 50:
                alert_lines.append(f"• …ещё {len(failed)-50}")
            alert_lines.append("")
        if empty:
            alert_lines.append("🟡 Empty categories:")
            alert_lines += [f"• {c}" for c in empty[:50]]
            if len(empty) > 50:
                alert_lines.append(f"• …ещё {len(empty)-50}")
            alert_lines.append("")
        if warns:
            alert_lines.append("⚠️ Warnings:")
            alert_lines += [f"• {w}" for w in warns[:50]]
            if len(warns) > 50:
                alert_lines.append(f"• …ещё {len(warns)-50}")
            alert_lines.append("")

        alert_lines.append(f"📝 Report: {report_line}")

    tg_alert = "\n".join(alert_lines).rstrip() + "\n" if alert_lines else ""
    return tg_message, tg_alert


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = ensure_state()

    # Standalone mode: no append (to avoid двойной append in workflow).
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
