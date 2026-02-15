#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KVAS report + Telegram generator (visual redesign).

Inputs:
- dist/state.json   (produced by src/build.py)
- dist/stats.json   (run history, appended here)

Outputs:
- dist/report.md    (regenerated every run)
- dist/tg_message.txt
- dist/tg_alert.txt (only if WARNING/ERROR; removed when OK)

Notes:
- Uses GitHub Markdown typography: # / ## / ### plus quotes and <details>.
- Telegram follows approved templates (OK / WARNING / ERROR) + report link.
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
            pass

    # ISO-ish
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
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
        return "🟢 OK"
    if s == "EMPTY":
        return "🟡 ПУСТО"
    if s == "FAIL":
        return "🔴 ОШИБКА"
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


# ---------------- report.md (redesign) ----------------

def format_report_md(state: Dict, stats: List[Dict], prev_rec: Optional[Dict]) -> str:
    build_time = fmt_build_time_msk(str(state.get("build_time_utc", "")))
    repo = str(state.get("repo", "unknown/unknown"))
    output = str(state.get("output", "dist/inside-kvas.lst"))

    max_lines = int(state.get("max_lines", 3000))
    threshold = int(state.get("near_limit_threshold", 2900))

    itdog_total = int(state.get("itdog_total", 0))
    v2_total = int(state.get("v2fly_total", 0))
    final_total = int(state.get("final_total", 0))

    trunc = int(state.get("truncated", 0))
    bad = int(state.get("bad_output_lines", 0))

    v2_ok = int(state.get("v2fly_ok", 0))
    v2_fail = int(state.get("v2fly_fail", 0))
    cats = state.get("v2fly_categories") or []
    empty_cats = state.get("empty_categories") or []
    failed_cats = state.get("failed_categories") or []
    warns = state.get("warnings") or []

    # diffs (top 20 shown in <details>)
    prev = state.get("prev") if isinstance(state.get("prev"), dict) else {}
    it_added, it_removed = diff_lists(prev.get("itdog_domains", []), state.get("itdog_domains", []))
    v2_added, v2_removed = diff_lists(prev.get("v2fly_extras", []), state.get("v2fly_extras", []))
    f_added, f_removed = diff_lists(prev.get("final_domains", []), state.get("final_domains", []))

    p = pct(final_total, max_lines)
    badge = limit_badge(p)
    near = final_total >= threshold or p >= 96.0

    sha = short_hash(str(state.get("sha256_final", "")))
    url = repo_report_url(repo)

    # Severity / warnings
    sev = classify_severity(state)
    if sev == "ОШИБКА":
        status_lines = ["### 🚨 Сборка завершена с ошибками"]
    elif sev == "ПРЕДУПРЕЖДЕНИЕ":
        status_lines = ["### ⚠️ Сборка завершена с предупреждениями"]
    else:
        status_lines = ["### ✅ Сборка завершена"]

    if failed_cats or empty_cats or warns or trunc or bad or near:
        # keep the high-level line consistent
        if sev == "ОК":
            status_lines.append("### 🟡 Требует внимания")
        elif sev == "ПРЕДУПРЕЖДЕНИЕ":
            status_lines.append("### 🟡 Требует внимания")
        else:
            status_lines.append("### 🔴 Критический статус")
    else:
        status_lines.append("### 🟢 Предупреждений нет")

    # v2fly categories table
    per_cat = state.get("v2fly_per_category") if isinstance(state.get("v2fly_per_category"), dict) else {}
    table_rows = []
    for c in cats:
        meta = per_cat.get(c, {}) if isinstance(per_cat.get(c, {}), dict) else {}
        table_rows.append(
            f"| {c} | {int(meta.get('valid_domains',0))} | {int(meta.get('extras_added',0))} | "
            f"{int(meta.get('invalid_lines',0))} | {int(meta.get('skipped_directives',0))} | {status_emoji(str(meta.get('status','')))} |"
        )
    if not table_rows:
        table_rows.append("| — | 0 | 0 | 0 | 0 | — |")

    # Diagnostics
    reserve = max_lines - final_total
    risk = "низкий 🟢" if p < 85.0 else ("средний 🟡" if p < 96.0 else "высокий 🔴")
    avg7, delta, deviation, eval_line = trend_eval(stats, prev_rec, final_total)

    # Problems list (for report)
    problems: List[str] = []
    if failed_cats:
        problems.append("🔴 Категории не скачались/не распарсились: " + ", ".join(failed_cats))
    if empty_cats:
        problems.append("🟡 Пустые категории (0 доменов): " + ", ".join(empty_cats))
    if near:
        problems.append("🟠 Почти лимит")
    if trunc > 0:
        problems.append(f"🔴 Обрезка по лимиту: {trunc} строк")
    if bad > 0:
        problems.append(f"🔴 Некорректные строки в выводе: {bad}")

    # Build the markdown (3 typography levels)
    L: List[str] = []
    L.append("# 📊 Отчёт сборки доменов KVAS")
    L.append("")
    L.append("## 🧭 Общая информация")
    L.append("")
    L.append(f"> 🕒 **Сборка:** {build_time}  ")
    L.append(f"> 📦 **Репозиторий:** {repo}  ")
    L.append(f"> 📄 **Выходной файл:** `{output}`  ")
    L.append(f"> 📏 Лимит строк: **{max_lines}**")
    if url:
        L.append(f"> 🔗 Отчёт: {url}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🧮 Итог сборки")
    L.append("")
    L.append(f"> ### 📊 {final_total} / {max_lines} ({p}%) {badge}")
    L.append(f"> **Запас:** {reserve} строк  ")
    L.append(f"> **Обрезка:** {'ДА' if trunc else 'НЕТ'}  ")
    L.append(f"> **Некорректных строк:** {bad}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🚦 Статус")
    L.append("")
    L.extend(status_lines)
    L.append("")
    if problems:
        L.append("### ⚠️ Замечания")
        for x in problems:
            L.append(f"- {x}")
        L.append("")
    else:
        L.append("### ✅ Замечаний нет")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## 📌 Сводка источников")
    L.append("")
    L.append("### 🗂 itdog")
    L.append("")
    L.append(f"- Всего доменов: **{itdog_total}**")
    L.append(f"- Изменение: **+{len(it_added)} / -{len(it_removed)}**")
    L.append("")
    L.append("### 🌐 v2fly (extras)")
    L.append("")
    L.append(f"- Всего extras: **{v2_total}**")
    L.append(f"- Изменение: **+{len(v2_added)} / -{len(v2_removed)}**")
    L.append(f"- Категорий: **{len(cats)}**")
    L.append("")
    L.append(f"🟢 OK: {v2_ok}  ")
    L.append(f"🔴 ОШИБКА: {v2_fail}  ")
    L.append(f"🟡 ПУСТО: {len(empty_cats)}")
    L.append("")
    L.append("### 📦 Итоговый список")
    L.append("")
    L.append(f"- Всего: **{final_total}**")
    L.append(f"- Изменение: **+{len(f_added)} / -{len(f_removed)}**")
    L.append(f"- Обрезано: **{trunc}**")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 📈 Использование лимита")
    L.append("")
    L.append(f"### 📊 {final_total} / {max_lines} ({p}%) {badge}")
    L.append("")
    L.append("🟢 до 85% — нормально  ")
    L.append("🟡 85–96% — внимание  ")
    L.append("🔴 ≥ 96% — критично")
    L.append("")
    L.append(f"Близко к лимиту: **{'ДА' if near else 'НЕТ'}** (порог {threshold})")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 📂 v2fly — категории")
    L.append("")
    L.append("| Категория | Валидных | Добавлено | Некорректных | Пропущено | Статус |")
    L.append("|---|---:|---:|---:|---:|---|")
    L.extend(table_rows)
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🔐 Хеш")
    L.append("")
    L.append(f"> sha256(final): **{sha}**")
    L.append("")
    L.append("---")
    L.append("")
    L.append("<details>")
    L.append("<summary>🔄 Изменения (топ 20)</summary>")
    L.append("")
    L.append("### itdog")
    L.append("**➕ Добавлено**")
    L.extend([f"- {x}" for x in it_added[:20]] or ["- —"])
    L.append("")
    L.append("**➖ Удалено**")
    L.extend([f"- {x}" for x in it_removed[:20]] or ["- —"])
    L.append("")
    L.append("---")
    L.append("")
    L.append("### v2fly extras")
    L.append("**➕ Добавлено**")
    L.extend([f"- {x}" for x in v2_added[:20]] or ["- —"])
    L.append("")
    L.append("**➖ Удалено**")
    L.extend([f"- {x}" for x in v2_removed[:20]] or ["- —"])
    L.append("")
    L.append("---")
    L.append("")
    L.append("### итоговый список")
    L.append("**➕ Добавлено**")
    L.extend([f"- {x}" for x in f_added[:20]] or ["- —"])
    L.append("")
    L.append("**➖ Удалено**")
    L.extend([f"- {x}" for x in f_removed[:20]] or ["- —"])
    L.append("")
    L.append("</details>")
    L.append("")
    L.append("<details>")
    L.append("<summary>🧪 Диагностика</summary>")
    L.append("")
    L.append(f"- источник itdog: **{itdog_total}** домена (уник.)")
    L.append(f"- v2fly extras: **{v2_total}** доменов (после вычитания пересечений)")
    L.append(f"- итог до лимита: **{final_total}** строк")
    L.append(f"- запас до лимита: **{reserve}** строк")
    L.append(f"- риск переполнения лимита: **{risk}**")
    L.append("")
    L.append("### 📈 Тренд")
    L.append(f"- Среднее (7): **{avg7}**")
    L.append(f"- Δ к прошлой: **{delta:+d}**")
    L.append(f"- Отклонение: **{deviation:+d}**")
    L.append(f"- {eval_line}")
    L.append("")
    L.append("### 🧠 v2fly здоровье")
    L.append(f"- fail={max(len(failed_cats), v2_fail)} 🔴")
    L.append(f"- empty={len(empty_cats)} 🟡")
    if failed_cats or empty_cats:
        L.append("")
        recs = []
        if failed_cats:
            recs.append("проверить: " + ", ".join([x.split("(", 1)[0].strip() for x in failed_cats]))
        if empty_cats:
            recs.append("проверить: " + ", ".join(empty_cats))
        L.append("### ✅ Рекомендации")
        for r in recs:
            L.append(f"- {r}")
    else:
        L.append("")
        L.append("### ✅ Рекомендации")
        L.append("- отсутствуют")
    L.append("")
    L.append("</details>")
    L.append("")
    return "\n".join(L).rstrip() + "\n"


# ---------------- Telegram ----------------

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


def format_tg(state: dict, report_url: str) -> Tuple[str, str]:
    """
    Telegram message (approved unified standard):
      - Always starts with a 3-line header + severity tag line.
      - No file attachment; only a link to report.md.
      - Returns: (tg_message_text, tg_alert_text_or_empty)
    """
    # --------- helpers ----------
    def short_hash(h: str) -> str:
        h = (h or "").strip()
        if len(h) <= 10:
            return h
        return f"{h[:4]}…{h[-4:]}"

    def ratio_color(used: int, limit_: int) -> str:
        if limit_ <= 0:
            return "🟢"
        p = (used / limit_) * 100.0
        if p >= 96.0:
            return "🔴"
        if p >= 85.0:
            return "🟠"
        return "🟢"

    def level_label(run_ok_: bool, has_warn_: bool, has_crit_: bool) -> Tuple[str, str]:
        # (color+source line, severity line)
        if has_crit_ or not run_ok_:
            return ("🔴 GitHub Actions", "🚨 CRITICAL")
        if has_warn_:
            return ("🟡 GitHub Actions", "⚠️ WARNING")
        return ("🟢 GitHub Actions", "ℹ️ INFO")

    # --------- pick core fields ----------
    dt_run = state.get("run_dt_msk") or now_msk_dt()
    if isinstance(dt_run, str):
        # tolerate old formats
        try:
            dt_run = datetime.fromisoformat(dt_run)
        except Exception:
            dt_run = now_msk_dt()

    d_s, t_s = fmt_tg_date_time(dt_run)

    final_count = int((state.get("final") or {}).get("total", 0) or 0)
    limit_ = int(state.get("limit", 3000) or 3000)
    rest = max(0, limit_ - final_count)
    pct = (final_count / limit_ * 100.0) if limit_ else 0.0

    sha_final = (state.get("hashes") or {}).get("sha256_final", "")
    sha_short = short_hash(sha_final)

    # Trend (already computed by report.py earlier; keep tolerant defaults)
    trend = state.get("trend", {}) if isinstance(state.get("trend", {}), dict) else {}
    avg7 = int(trend.get("avg7", 0) or 0)
    delta_prev = int(trend.get("delta_prev", 0) or 0)
    trend_label = str(trend.get("label", "➡ Стабильно") or "➡ Стабильно").strip()

    # Warnings / criticals aggregated by report.py
    alerts = state.get("alerts", []) if isinstance(state.get("alerts", []), list) else []
    critical_alert = state.get("critical_alert", "") or ""
    run_ok = bool(state.get("run_ok", True))
    has_warn = bool(alerts)
    has_crit = bool(critical_alert) or (not run_ok)

    source_line, sev_line = level_label(run_ok, has_warn, has_crit)

    header = [
        "📦 BUILD SYSTEM",
        source_line,
        "━━━━━━━━━━━━━━━━━━",
        sev_line,
        "",
    ]

    # --------- body ----------
    lines: List[str] = []

    if has_crit:
        lines += [
            "❌ Сборка завершена с ошибками",
            "🔴 Критический статус",
            "",
            f"🗓 {d_s}",
            f"🕒 {t_s} МСК",
        ]
        # For critical we often don't have stable numbers; include if present.
        if final_count and limit_:
            lines += [
                "",
                f"📊 {final_count} / {limit_} ({pct:.1f}%) {ratio_color(final_count, limit_)}",
                f"🧮 Остаток: {rest} строк",
            ]
        if critical_alert:
            lines += ["", f"⚠ Логи: {critical_alert}"]
    elif has_warn:
        # WARNING
        lines += [
            "✅ Сборка завершена",
        ]
        # Build a compact warning summary
        # state may carry 'warn_summary' if you generate it; otherwise show counts.
        warn_summary = state.get("warn_summary", "")
        if warn_summary:
            lines += [f"⚠️ Есть предупреждения: {warn_summary}"]
        else:
            lines += [f"⚠️ Есть предупреждения: {len(alerts)}"]
        lines += [
            "",
            f"🗓 {d_s}",
            f"🕒 {t_s} МСК",
            "",
            f"📊 {final_count} / {limit_} ({pct:.1f}%) {ratio_color(final_count, limit_)}",
            f"🧮 Остаток: {rest} строк",
            "",
            "⚠ ПРОБЛЕМЫ",
        ]
        # Show up to 8 issues
        for a in alerts[:8]:
            # expected format: {"sev":"warn"/"error","title":"...", "detail":"..."}
            sev = str(a.get("sev", "warn")).lower()
            title = str(a.get("title", "")).strip()
            detail = str(a.get("detail", "")).strip()
            if not title and detail:
                title = detail
                detail = ""
            icon = "🟡"
            if sev in ("error", "fail", "critical"):
                icon = "🔴"
            elif sev in ("near_limit", "orange", "warning"):
                icon = "🟠"
            if detail:
                lines.append(f"{icon} {title} — {detail}")
            else:
                lines.append(f"{icon} {title}")
    else:
        # INFO / OK
        lines += [
            "🚀 Сборка завершена",
            "🟢 Система стабильна",
            "",
            f"🗓 {d_s}",
            f"🕒 {t_s} МСК",
            "",
            f"📊 {final_count} / {limit_} ({pct:.1f}%) {ratio_color(final_count, limit_)}",
            f"🧮 Остаток: {rest} строк",
            "",
            "📈 ТРЕНД",
            f"Среднее (7): {avg7}",
            f"Δ к прошлой: {delta_prev:+d}",
            f"{trend_label}",
            "",
            "✅ Замечаний нет",
        ]

    # footer: hash + report link (always)
    if sha_short:
        lines += ["", f"🔐 sha256: {sha_short}"]
    if report_url:
        lines += [f"🔗 Отчёт: {report_url}"]

    tg_text = "\n".join(header + lines).rstrip() + "\n"

    # Separate alert message: only when warnings/critical
    tg_alert = ""
    if has_crit or has_warn:
        tg_alert = tg_text

    return tg_text, tg_alert


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict) or not state:
        # minimal fallback, don't crash workflow
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

    stats, prev_rec = append_stats(state)

    REPORT_MD.write_text(format_report_md(state, stats, prev_rec), encoding="utf-8")

    tg_msg, tg_alert = format_tg(state, stats, prev_rec)
    TG_MESSAGE.write_text(tg_msg, encoding="utf-8")
    if tg_alert.strip():
        TG_ALERT.write_text(tg_alert, encoding="utf-8")
    else:
        TG_ALERT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
