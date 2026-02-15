#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DIST = Path("dist")
STATE_PATH = DIST / "state.json"
STATS_PATH = DIST / "stats.json"
REPORT_MD_PATH = DIST / "report.md"
TG_MESSAGE_PATH = DIST / "tg_message.txt"
TG_ALERT_PATH = DIST / "tg_alert.txt"
TG_FAILURE_PATH = DIST / "tg_failure.txt"

MONTHS_RU = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _short_sha(full_sha: str) -> str:
    if not full_sha:
        return "—"
    s = full_sha.strip()
    if len(s) <= 10:
        return s
    return f"{s[:4]}…{s[-4:]}"


def _msk_dt_from_state(state: Dict[str, Any]) -> datetime:
    # Preferred: explicit ISO string in state
    iso = state.get("run_time_msk") or state.get("build_time_msk")
    if isinstance(iso, str) and iso:
        # Accept "YYYY-MM-DD HH:MM:SS" or ISO 8601
        try:
            if "T" in iso:
                return datetime.fromisoformat(iso)
            return datetime.strptime(iso, "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # Fallback: UTC iso from build step
    utc_iso = state.get("build_time_utc")
    if isinstance(utc_iso, str) and utc_iso:
        try:
            dt = datetime.fromisoformat(utc_iso.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass

    # Fallback: epoch seconds
    ts = state.get("run_ts") or state.get("timestamp")
    try:
        ts = int(ts)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        # Last resort: now (UTC)
        return datetime.now(tz=timezone.utc)


def _fmt_date_time_msk(dt: datetime) -> Tuple[str, str]:
    """Return (DD.MM.YYYY, HH:MM:SS) in MSK (UTC+3)."""
    msk = timezone(timedelta(hours=3))
    if dt.tzinfo is None:
        d = dt.replace(tzinfo=msk)
    else:
        d = dt.astimezone(msk)
    return (d.strftime('%d.%m.%Y'), d.strftime('%H:%M:%S'))


def _github_report_url(repo: str) -> str:
    # repo like "SkyNextGen/kvas-domains"
    if not repo:
        repo = os.getenv("GITHUB_REPOSITORY", "")
    if not repo:
        return ""
    return f"https://github.com/{repo}/blob/main/dist/report.md"


def _github_actions_run_url(repo: str) -> str:
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if not repo:
        repo = os.getenv("GITHUB_REPOSITORY", "")
    if not repo or not run_id:
        return ""
    return f"https://github.com/{repo}/actions/runs/{run_id}"


@dataclass
class Trend:
    avg7: int
    delta_prev: int
    label: str


def _compute_trend(stats: List[Dict[str, Any]], current_total: int) -> Trend:
    # stats is a list of dicts with key total (final list size)
    totals = [int(x.get("total") or x.get("total_final") or x.get("final_total") or 0) for x in stats if isinstance(x, dict)]
    prev = totals[-2] if len(totals) >= 2 else current_total
    last7 = totals[-7:] if totals else [current_total]
    avg7 = int(round(sum(last7) / max(1, len(last7))))
    delta = int(current_total) - int(prev)

    # Simple stability heuristic
    if abs(delta) <= max(3, int(0.002 * max(1, current_total))):
        label = "➡ Стабильно"
    elif delta > 0:
        label = "⬆ Рост"
    else:
        label = "⬇ Снижение"

    return Trend(avg7=avg7, delta_prev=delta, label=label)


@dataclass
class LimitInfo:
    used: int
    limit: int
    pct: float
    color: str  # emoji
    remain: int
    near_limit: bool


def _limit_info(used: int, limit: int, near_threshold: int = 2900) -> LimitInfo:
    limit = int(limit) if limit else 0
    used = int(used) if used else 0
    pct = (used / limit * 100.0) if limit else 0.0
    remain = max(0, limit - used) if limit else 0

    # Color per earlier rule
    if limit and used / limit < 0.85:
        color = "🟢"
    elif limit and used / limit < 0.96:
        color = "🟡"
    else:
        # near critical
        color = "🟠" if limit and used / limit < 0.99 else "🔴"

    near_limit = bool(limit and used >= near_threshold)
    return LimitInfo(used=used, limit=limit, pct=pct, color=color, remain=remain, near_limit=near_limit)


@dataclass
class Health:
    level: str  # INFO/WARNING/CRITICAL
    header_color: str  # 🟢 🟡 🔴
    build_title: str
    build_subtitle: str
    problems: List[str]


def _health_from_state(state: Dict[str, Any], lim: LimitInfo) -> Health:
    errors: List[str] = []
    warnings: List[str] = []

    # Structured signals
    for x in state.get("errors", []) or []:
        if isinstance(x, str) and x.strip():
            errors.append(x.strip())
    for x in state.get("warnings", []) or []:
        if isinstance(x, str) and x.strip():
            warnings.append(x.strip())

    # v2fly category status
    v2_fail = state.get("v2fly_fail", {}) or {}
    v2_empty = state.get("v2fly_empty", {}) or {}
    if isinstance(v2_fail, dict):
        for k, v in v2_fail.items():
            errors.append(f"{k} — {v}")
    if isinstance(v2_empty, dict):
        for k in v2_empty.keys():
            warnings.append(f"{k} — пусто")

    # Near limit is a warning
    if lim.near_limit or (lim.limit and lim.used / lim.limit >= 0.96):
        warnings.append("Почти лимит")

    if errors:
        return Health(
            level="CRITICAL",
            header_color="🔴",
            build_title="❌ Сборка завершена с ошибками",
            build_subtitle="🔴 Критический статус",
            problems=errors[:10],
        )

    if warnings:
        # compress common warning lines into readable text
        return Health(
            level="WARNING",
            header_color="🟡",
            build_title="✅ Сборка завершена",
            build_subtitle=f"⚠️ Есть предупреждения: {len(warnings)}",
            problems=warnings[:10],
        )

    return Health(
        level="INFO",
        header_color="🟢",
        build_title="🚀 Сборка завершена",
        build_subtitle="🟢 Система стабильна",
        problems=[],
    )


def _tg_header(source_name: str, level: str) -> Tuple[str, str, str]:
    # Returns (line1, line2, label)
    # Source_name example: "GitHub Actions"
    if level == "CRITICAL":
        return ("📦 BUILD SYSTEM", f"🔴 {source_name}", "🚨 CRITICAL")
    if level == "WARNING":
        return ("📦 BUILD SYSTEM", f"🟡 {source_name}", "⚠️ WARNING")
    return ("📦 BUILD SYSTEM", f"🟢 {source_name}", "ℹ️ INFO")


def format_tg(state: Dict[str, Any], stats: List[Dict[str, Any]], repo: str) -> Tuple[str, Optional[str], Optional[str]]:
    # returns (main_msg, alert_msg, failure_msg)
    total_final = int((state.get("total_final") or state.get("final_total") or 0) or 0)
    limit = int(state.get("limit", 3000) or 3000)
    sha = _short_sha(str(state.get("sha256_final", "") or ""))

    lim = _limit_info(total_final, limit, near_threshold=int(state.get("near_threshold", 2900) or 2900))
    trend = _compute_trend(stats, total_final)
    health = _health_from_state(state, lim)

    dt = _msk_dt_from_state(state)
    date_s, time_s = _fmt_date_time_msk(dt)

    report_url = _github_report_url(repo)
    run_url = _github_actions_run_url(repo)

    h1, h2, lvl = _tg_header("GitHub Actions", health.level)

    lines: List[str] = []
    lines.append(h1)
    lines.append(h2)
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(lvl)
    lines.append("")
    lines.append(health.build_title)
    lines.append(health.build_subtitle)
    lines.append("")
    lines.append(f"🗓 {date_s}")
    lines.append(f"🕒 {time_s} МСК")
    lines.append("")
    if lim.limit:
        lines.append(f"📊 {lim.used} / {lim.limit} ({lim.pct:.1f}%) {lim.color}")
        lines.append(f"🧮 Остаток: {lim.remain} строк")
        lines.append("")

    # Trend always shown for INFO/WARNING
    if health.level in ("INFO", "WARNING"):
        lines.append("📈 ТРЕНД")
        lines.append(f"Среднее (7): {trend.avg7}")
        sign = "+" if trend.delta_prev >= 0 else ""
        lines.append(f"Δ к прошлой: {sign}{trend.delta_prev}")
        lines.append(trend.label)
        lines.append("")

    # Problems shown only for WARNING
    if health.level == "WARNING":
        lines.append("⚠ ПРОБЛЕМЫ")
        for p in health.problems:
            if p == "Почти лимит":
                lines.append("🟠 Почти лимит")
            elif "пусто" in p:
                lines.append(f"🟡 {p}")
            else:
                lines.append(f"🔴 {p}")
        lines.append("")

    if health.level == "INFO":
        lines.append("✅ Замечаний нет")
        lines.append("")

    lines.append(f"🔐 sha256: {sha}")

    if report_url:
        lines.append(f"🔗 Отчёт: {report_url}")

    # CRITICAL includes link to actions run
    if health.level == "CRITICAL":
        lines.append("")
        if run_url:
            lines.append(f"⚠ Логи: GitHub Actions (run)\n{run_url}")
        else:
            lines.append("⚠ Логи: GitHub Actions (run)")

    main = "\n".join(lines).strip()

    alert_msg = None
    failure_msg = None
    if health.level == "WARNING":
        alert_msg = main
    if health.level == "CRITICAL":
        failure_msg = main

    return main, alert_msg, failure_msg


def _format_report_md(state: Dict[str, Any], stats: List[Dict[str, Any]]) -> str:
    # Keep it simple: the repo already has a redesigned markdown; here only ensure it's regenerated.
    repo = state.get("repo") or os.getenv("GITHUB_REPOSITORY", "")
    dt = _msk_dt_from_state(state)
    d, t = _fmt_date_time_msk(dt)

    total_final = int((state.get("total_final") or state.get("final_total") or 0) or 0)
    limit = int(state.get("limit", 3000) or 3000)
    lim = _limit_info(total_final, limit, near_threshold=int(state.get("near_threshold", 2900) or 2900))
    trend = _compute_trend(stats, total_final)

    sha = str(state.get("sha256_final", "") or "")
    sha_s = _short_sha(sha)

    # Source summaries
    itdog_total = int(state.get("itdog_total", 0) or 0)
    v2_extras_total = int(state.get("v2fly_extras_total", 0) or 0)
    v2_ok = int(state.get("v2fly_ok_count", 0) or 0)
    v2_fail = int(state.get("v2fly_fail_count", 0) or 0)
    v2_empty = int(state.get("v2fly_empty_count", 0) or 0)

    # Status names in Russian
    status_ok = "ОК"
    status_fail = "ОШИБКА"

    v2_fail_map = state.get("v2fly_fail", {}) or {}
    v2_empty_map = state.get("v2fly_empty", {}) or {}

    warn_lines: List[str] = []
    if v2_fail_map:
        for k, v in v2_fail_map.items():
            warn_lines.append(f"- 🔴 **{k}** — {v}")
    if v2_empty_map:
        for k in v2_empty_map.keys():
            warn_lines.append(f"- 🟡 **{k}** — пусто")

    md: List[str] = []
    md.append("# 📊 Отчёт сборки доменов KVAS")
    md.append("")
    md.append(f"**Сборка:** {d}, {t} МСК  ")
    md.append(f"**Репозиторий:** `{repo}`  ")
    md.append(f"**Выходной файл:** `dist/inside-kvas.lst`  ")
    md.append(f"**Лимит строк:** `{limit}`")
    md.append("")

    md.append("## 🚦 Статус")
    if v2_fail:
        md.append(f"- ❌ {status_fail}: {v2_fail} катег.")
    else:
        md.append(f"- ✅ {status_ok}")
    if v2_empty:
        md.append(f"- 🟡 Пустых категорий: {v2_empty}")
    md.append("")

    md.append("## 📌 Сводка")
    md.append(f"- itdog: **{itdog_total}**")
    md.append(f"- v2fly extras: **{v2_extras_total}** (🟢 ok={v2_ok} / 🔴 {status_fail}={v2_fail} / 🟡 пусто={v2_empty})")
    md.append(f"- итоговый список: **{total_final}**")
    md.append("")

    md.append("## 📈 Лимит")
    md.append(f"- использование: **{lim.used} / {lim.limit} ({lim.pct:.1f}%)** {lim.color}")
    md.append(f"- остаток: **{lim.remain}** строк")
    md.append("")

    md.append("## 📉 Тренд")
    md.append(f"- среднее (7): **{trend.avg7}**")
    sign = "+" if trend.delta_prev >= 0 else ""
    md.append(f"- Δ к прошлой: **{sign}{trend.delta_prev}**")
    md.append(f"- {trend.label}")
    md.append("")

    if warn_lines:
        md.append("## ⚠️ Предупреждения")
        md.extend(warn_lines)
        md.append("")

    md.append("## 🔐 Контроль")
    md.append(f"- sha256(final): `{sha_s}`")

    return "\n".join(md).rstrip() + "\n"


def main() -> int:
    state = _load_json(STATE_PATH, {})
    stats = _load_json(STATS_PATH, [])

    repo = str(state.get("repo") or os.getenv("GITHUB_REPOSITORY", ""))

    try:
        # Generate report.md (always overwrite)
        _write_text(REPORT_MD_PATH, _format_report_md(state, stats))

        # Telegram messages
        tg_main, tg_alert, tg_failure = format_tg(state, stats, repo)
        _write_text(TG_MESSAGE_PATH, tg_main)
        if tg_alert:
            _write_text(TG_ALERT_PATH, tg_alert)
        else:
            if TG_ALERT_PATH.exists():
                TG_ALERT_PATH.unlink()
        if tg_failure:
            _write_text(TG_FAILURE_PATH, tg_failure)
        else:
            if TG_FAILURE_PATH.exists():
                TG_FAILURE_PATH.unlink()

        return 0
    except Exception as e:
        # Never crash: emit CRITICAL telegram message
        repo2 = repo or os.getenv("GITHUB_REPOSITORY", "")
        run_url = _github_actions_run_url(repo2)
        dt = datetime.now()
        d, t = _fmt_date_time_msk(dt)
        msg = (
            "📦 BUILD SYSTEM\n"
            "🔴 GitHub Actions\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚨 CRITICAL\n\n"
            "❌ Ошибка формирования отчёта\n"
            "🔴 Критический статус\n\n"
            f"🗓 {d}\n"
            f"🕒 {t} МСК\n\n"
            f"⚠ Причина: {type(e).__name__}: {e}\n"
        )
        if run_url:
            msg += f"\n⚠ Логи: GitHub Actions (run)\n{run_url}\n"
        _write_text(TG_MESSAGE_PATH, msg)
        _write_text(TG_FAILURE_PATH, msg)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
