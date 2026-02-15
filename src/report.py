#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KVAS domains build reporter

Inputs:
  - dist/state.json (produced by build pipeline)

Outputs:
  - dist/report.md
  - dist/tg_message.txt   (Telegram message in approved format: ОК/ПРЕДУПРЕЖДЕНИЕ/ОШИБКА)
  - dist/tg_alert.txt     (Only for ПРЕДУПРЕЖДЕНИЕ/ОШИБКА; optional)
  - dist/stats.json       (rolling telemetry for trend)

This file is meant to be committed as scripts/report.py (or similar).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ------------------------- paths -------------------------

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"

STATE_JSON = DIST_DIR / "state.json"
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATS_JSON = DIST_DIR / "stats.json"


# ------------------------- time/locale -------------------------

MSK_TZ = timezone(timedelta(hours=3))
MONTHS_RU = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def now_msk_dt() -> datetime:
    return datetime.now(timezone.utc).astimezone(MSK_TZ)


def format_build_time_msk_from_state(build_time_utc_raw: str) -> str:
    """
    state.json typically stores build_time_utc like:
      - 'YYYY-MM-DD HH:MM:SS UTC'
      - 'YYYY-MM-DD HH:MM:SS'
      - ISO-8601 (best effort)
    """
    raw = (build_time_utc_raw or "").strip()
    if not raw:
        # fallback: now
        dt_msk = now_msk_dt()
        m = MONTHS_RU[dt_msk.month - 1]
        return f"{dt_msk.day:02d} {m} {dt_msk.year}, {dt_msk:%H:%M} МСК"

    s = raw.replace("UTC", "").strip()

    # Try common formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt_utc = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            dt_msk = dt_utc.astimezone(MSK_TZ)
            m = MONTHS_RU[dt_msk.month - 1]
            return f"{dt_msk.day:02d} {m} {dt_msk.year}, {dt_msk:%H:%M} МСК"
        except Exception:
            pass

    # Try ISO
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_msk = dt.astimezone(MSK_TZ)
        m = MONTHS_RU[dt_msk.month - 1]
        return f"{dt_msk.day:02d} {m} {dt_msk.year}, {dt_msk:%H:%M} МСК"
    except Exception:
        return raw


def format_tg_date_time(dt_msk: datetime) -> Tuple[str, str]:
    return dt_msk.strftime("%d.%m.%Y"), dt_msk.strftime("%H:%M:%S МСК")


# ------------------------- json helpers -------------------------

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------- domain set helpers -------------------------

def diff_sets(prev_list: List[str], curr_list: List[str]) -> Tuple[List[str], List[str]]:
    prev = set(prev_list or [])
    curr = set(curr_list or [])
    added = sorted(curr - prev)
    removed = sorted(prev - curr)
    return added, removed


def topn(items: List[str], n: int = 20) -> List[str]:
    return items[:n]


def block_list(items: List[str], indent: str = "") -> str:
    if not items:
        return f"{indent}—"
    return "\n".join(f"{indent}{x}" for x in items)


# ------------------------- formatting helpers -------------------------

def short_hash(h: str) -> str:
    h = (h or "").strip()
    if len(h) < 10:
        return h or "—"
    return f"{h[:4]}…{h[-4:]}"


def format_change(added: int, removed: int) -> str:
    # note: use "−" (U+2212) for consistent typography
    return f"+{added} / −{removed}"


def usage_badge(pct: float) -> str:
    # 🟢 <85, 🟡 85–96, 🔴 ≥96
    if pct >= 96.0:
        return "🔴"
    if pct >= 85.0:
        return "🟡"
    return "🟢"


def status_text_table(status: str) -> str:
    s = (status or "").strip()
    if s.startswith("OK"):
        return "🟢 ОК"
    if s.startswith("EMPTY"):
        return "🟡 ПУСТО"
    if s.startswith("FAIL"):
        return "🔴 ОШИБКА"
    return s or "—"


def build_run_url() -> Optional[str]:
    server = os.getenv("GITHUB_SERVER_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


# ------------------------- trend telemetry -------------------------

def append_stats(total: int, itdog: int, v2fly: int, warn_level: str, warn_count: int, error_count: int) -> None:
    data = load_json(STATS_JSON, [])
    if not isinstance(data, list):
        data = []

    rec = {
        "ts_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "total": int(total),
        "itdog": int(itdog),
        "v2fly": int(v2fly),
        "level": warn_level,     # ОК/ПРЕДУПРЕЖДЕНИЕ/ОШИБКА
        "warn_count": int(warn_count),
        "error_count": int(error_count),
    }
    data.append(rec)
    data = data[-400:]
    dump_json(STATS_JSON, data)


def last_stats(n: int = 7) -> List[Dict]:
    data = load_json(STATS_JSON, [])
    if not isinstance(data, list):
        return []
    out: List[Dict] = []
    for row in data[-n:]:
        if isinstance(row, dict) and isinstance(row.get("total"), int):
            out.append(row)
    return out


def avg(nums: List[int]) -> Optional[float]:
    if not nums:
        return None
    return sum(nums) / len(nums)


def trend_label(curr: int, avg7: Optional[int], delta_prev: Optional[int]) -> str:
    """
    Produces a short verdict line, aligned to your examples.
    """
    if avg7 is None or delta_prev is None:
        return "➡ Стабильно"

    dev = curr - avg7

    # if movement is small, stable
    if abs(delta_prev) <= 5 and abs(dev) <= 30:
        return "➡ Стабильно"

    if delta_prev > 0:
        # "Рост (выше среднего ×2)" heuristic:
        # if deviation is at least double the absolute delta and above some floor.
        if dev > 0 and dev >= max(120, abs(delta_prev) * 2):
            return "📈 Рост (выше среднего ×2)"
        return "📈 Рост"
    if delta_prev < 0:
        return "📉 Падение"
    return "➡ Стабильно"


# ------------------------- severity model -------------------------

@dataclass
class Severity:
    level: str          # ОК/ПРЕДУПРЕЖДЕНИЕ/ОШИБКА
    headline: str       # first line
    status_line: str    # second line
    emoji: str          # 🟢🟡🔴


def classify_severity(
    *,
    v2fly_fail: int,
    failed_categories: List[str],
    bad_output_lines: int,
    truncated_count: int,
    usage_pct: float,
    max_lines: int,
    threshold: int,
    empty_categories: List[str],
    warnings: List[str],
) -> Severity:
    # Условия ОШИБКА
    is_error = (
        v2fly_fail > 0
        or bool(failed_categories)
        or bad_output_lines > 0
        or truncated_count > 0
        or usage_pct >= 96.0
    )

    # Условия ПРЕДУПРЕЖДЕНИЕ (если не ошибка)
    is_warn = (
        (not is_error)
        and (
            bool(empty_categories)
            or bool(warnings)
            or usage_pct >= 85.0
            or (max_lines > 0 and int(round((usage_pct/100.0) * max_lines)) >= threshold)  # compatibility
        )
    )

    if is_error:
        return Severity(
            level="ОШИБКА",
            headline="🚨 Сборка завершена с ошибками",
            status_line="🔴 Критический статус",
            emoji="🔴",
        )
    if is_warn:
        return Severity(
            level="ПРЕДУПРЕЖДЕНИЕ",
            headline="⚠️ Сборка завершена с предупреждениями",
            status_line="🟡 Требует внимания",
            emoji="🟡",
        )
    return Severity(
        level="ОК",
        headline="🚀 Сборка завершена",
        status_line="🟢 Система стабильна",
        emoji="🟢",
    )


# ------------------------- main -------------------------

def main() -> int:
    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict):
        raise SystemExit("Bad dist/state.json")

    prev = state.get("prev", {}) if isinstance(state.get("prev"), dict) else {}

    repo = str(state.get("repo", "unknown/unknown"))
    output = str(state.get("output", "dist/inside-kvas.lst"))
    max_lines = int(state.get("max_lines", 3000))
    threshold = int(state.get("near_limit_threshold", 2900))

    itdog_domains = state.get("itdog_domains", []) or []
    v2fly_extras = state.get("v2fly_extras", []) or []
    final_domains = state.get("final_domains", []) or []
    if not isinstance(itdog_domains, list):
        itdog_domains = []
    if not isinstance(v2fly_extras, list):
        v2fly_extras = []
    if not isinstance(final_domains, list):
        final_domains = []

    itdog_set = set(itdog_domains)
    v2fly_set = set(v2fly_extras)
    final_set = set(final_domains)

    itdog_total = len(itdog_set)
    v2fly_total = len(v2fly_set)
    final_total = len(final_set)

    it_added, it_removed = diff_sets(prev.get("itdog_domains", []) or [], itdog_domains)
    v2_added, v2_removed = diff_sets(prev.get("v2fly_extras", []) or [], v2fly_extras)
    f_added, f_removed = diff_sets(prev.get("final_domains", []) or [], final_domains)

    it_change = format_change(len(it_added), len(it_removed))
    v2_change = format_change(len(v2_added), len(v2_removed))
    f_change = format_change(len(f_added), len(f_removed))

    v2fly_ok = int(state.get("v2fly_ok", 0))
    v2fly_fail = int(state.get("v2fly_fail", 0))
    truncated_count = int(state.get("truncated", 0))
    bad_output_lines = int(state.get("bad_output_lines", 0))

    warnings = state.get("warnings", []) or []
    failed_categories = state.get("failed_categories", []) or []
    empty_categories = state.get("empty_categories", []) or []
    if not isinstance(warnings, list):
        warnings = []
    if not isinstance(failed_categories, list):
        failed_categories = []
    if not isinstance(empty_categories, list):
        empty_categories = []

    build_time_utc = str(state.get("build_time_utc", "")).replace(" UTC", "")
    build_time_msk = format_build_time_msk_from_state(build_time_utc)

    sha = short_hash(str(state.get("sha256_final", "")))

    usage_pct = round((final_total / max_lines) * 100, 1) if max_lines else 0.0
    badge = usage_badge(usage_pct)
    remaining = max(0, max_lines - final_total)
    near_limit = final_total >= threshold

    # v2fly per-category
    cats = state.get("v2fly_categories", []) or []
    per_cat = state.get("v2fly_per_category", {}) or {}
    if not isinstance(cats, list):
        cats = []
    if not isinstance(per_cat, dict):
        per_cat = {}
    cats_total = len(cats)
    empty_count = len(empty_categories)

    # classify severity
    sev = classify_severity(
        v2fly_fail=v2fly_fail,
        failed_categories=failed_categories,
        bad_output_lines=bad_output_lines,
        truncated_count=truncated_count,
        usage_pct=usage_pct,
        max_lines=max_lines,
        threshold=threshold,
        empty_categories=empty_categories,
        warnings=warnings,
    )

    # trend stats
    stats7 = last_stats(7)
    totals7 = [int(x["total"]) for x in stats7 if isinstance(x.get("total"), int)]
    avg7 = avg(totals7)
    avg7_int = int(round(avg7)) if avg7 is not None else None

    prev_total = None
    if len(stats7) >= 2 and isinstance(stats7[-2].get("total"), int):
        prev_total = int(stats7[-2]["total"])
    delta_prev = (final_total - prev_total) if prev_total is not None else None

    deviation = (final_total - avg7_int) if avg7_int is not None else None
    trend_verdict = trend_label(final_total, avg7_int, delta_prev) if (avg7_int is not None and delta_prev is not None) else "➡ Стабильно"

    # write telemetry AFTER computing delta from previous telemetry entry
    error_count = 0
    warn_count = 0
    if failed_categories:
        error_count += len(failed_categories)
    if v2fly_fail:
        error_count += v2fly_fail
    if bad_output_lines:
        error_count += 1
    if truncated_count:
        error_count += 1
    if usage_pct >= 96.0:
        error_count += 1

    if empty_categories:
        warn_count += len(empty_categories)
    if warnings:
        warn_count += len(warnings)
    if near_limit and usage_pct < 96.0:
        warn_count += 1
    if usage_pct >= 85.0 and usage_pct < 96.0:
        warn_count += 1

    append_stats(final_total, itdog_total, v2fly_total, sev.level, warn_count, error_count)

    # ------------------------- REPORT.MD -------------------------

    critical_lines: List[str] = []
    if failed_categories:
        critical_lines.append(f"🔴 Категории не скачались/не распарсились: {', '.join(failed_categories)}")
    if bad_output_lines > 0:
        critical_lines.append(f"🔴 Некорректных строк в итоговом выводе: {bad_output_lines}")
    if truncated_count > 0:
        critical_lines.append(f"🔴 Обрезка по лимиту: ДА (обрезано строк: {truncated_count})")
    if usage_pct >= 96.0:
        critical_lines.append(f"🔴 Почти лимит: {final_total}/{max_lines} ({usage_pct}%)")

    warn_lines: List[str] = []
    if empty_categories:
        warn_lines.append(f"🟡 Пустые категории (0 доменов): {', '.join(empty_categories)}")
    if warnings:
        # avoid noise: show only first 10
        warn_lines.extend([f"🟡 {w}" for w in warnings[:10]])
        if len(warnings) > 10:
            warn_lines.append(f"🟡 …ещё {len(warnings) - 10}")

    report: List[str] = []
    report.append("# 📊 Отчёт сборки доменов KVAS")
    report.append("")
    report.append(f"Сборка: {build_time_msk}")
    report.append(f"Репозиторий: {repo}")
    report.append(f"Выходной файл: {output}")
    report.append(f"Лимит строк: {max_lines}")
    report.append("")

    # top severity header
    report.append("🚦 Статус сборки")
    report.append("")
    report.append(sev.headline)
    report.append(sev.status_line)
    report.append(f"🧾 Некорректных строк в итоговом выводе: {bad_output_lines}")
    report.append(f"✂️ Обрезка по лимиту: {'ДА' if truncated_count > 0 else 'НЕТ'}")
    report.append("")

    if critical_lines:
        report.append("🔥 Критичные проблемы")
        report.extend(critical_lines)
        report.append("")

    report.append("📌 Сводка")
    report.append("")
    report.append("itdog")
    report.append("")
    report.append(f"всего: {itdog_total}")
    report.append(f"изменение к прошлому запуску: {it_change}")
    report.append("")
    report.append("v2fly (только extras — отсутствуют в itdog)")
    report.append("")
    report.append(f"всего extras: {v2fly_total}")
    report.append(f"изменение к прошлому запуску: {v2_change}")
    report.append("")
    report.append(f"категории: {cats_total} (🟢 ok={v2fly_ok} / 🔴 fail={v2fly_fail} / 🟡 пусто={empty_count})")
    report.append("")
    report.append("итоговый список")
    report.append("")
    report.append(f"всего: {final_total}")
    report.append(f"изменение к прошлому запуску: {f_change}")
    report.append(f"обрезано строк: {truncated_count}")
    report.append("")

    report.append("📈 Лимит")
    report.append("")
    report.append(f"использование: {final_total} / {max_lines} ({usage_pct}% занято) {badge}")
    report.append(f"остаток: {remaining} строк")
    report.append(f"порог предупреждения: {threshold} | почти лимит: {'ДА' if near_limit else 'НЕТ'}")
    report.append("")
    report.append("Правило подсветки:")
    report.append("🟢 до 85% — нормально | 🟡 85–96% — внимание | 🔴 ≥ 96% — критично")
    report.append("")

    report.append("📈 Тренд")
    report.append("")
    if avg7_int is not None:
        report.append(f"Среднее (7): {avg7_int}")
    else:
        report.append("Среднее (7): —")
    if delta_prev is not None:
        report.append(f"Δ к прошлой: {delta_prev:+d}")
    else:
        report.append("Δ к прошлой: —")
    if deviation is not None:
        report.append(f"Отклонение: {deviation:+d}")
    else:
        report.append("Отклонение: —")
    report.append(trend_verdict)
    report.append("")

    report.append("🔄 Изменения itdog (топ 20)")
    report.append("➕ Добавлено")
    report.append(block_list(topn(it_added, 20)))
    report.append("")
    report.append("➖ Удалено")
    report.append(block_list(topn(it_removed, 20)))
    report.append("")

    report.append("🔄 Изменения v2fly extras (топ 20)")
    report.append("➕ Добавлено")
    report.append(block_list(topn(v2_added, 20)))
    report.append("")
    report.append("➖ Удалено")
    report.append(block_list(topn(v2_removed, 20)))
    report.append("")

    report.append("🔄 Изменения итогового списка (топ 20)")
    report.append("➕ Добавлено")
    report.append(block_list(topn(f_added, 20)))
    report.append("")
    report.append("➖ Удалено")
    report.append(block_list(topn(f_removed, 20)))
    report.append("")

    report.append("📂 Статистика v2fly по категориям")
    report.append("")
    report.append("| Категория | Валидных доменов | Добавлено в extras | Некорректных строк | Пропущено директив | Статус |")
    report.append("|---|---:|---:|---:|---:|---|")
    if cats:
        for cat in cats:
            d = per_cat.get(cat, {}) if isinstance(per_cat.get(cat, {}), dict) else {}
            report.append(
                f"| {cat} | {int(d.get('valid_domains', 0))} | {int(d.get('extras_added', 0))} | "
                f"{int(d.get('invalid_lines', 0))} | {int(d.get('skipped_directives', 0))} | {status_text_table(str(d.get('status', '')))} |"
            )
    else:
        report.append("| — | 0 | 0 | 0 | 0 | — |")
    report.append("")
    report.append("Легенда статусов: 🟢 ОК | 🟡 ПУСТО (0 валидных доменов) | 🔴 ОШИБКА (скачивание/парсинг)")
    report.append("")
    report.append("Примечания")
    report.append("")
    report.append("- Валидных доменов — извлечённые из категории после фильтра (full:/domain:/голые домены)")
    report.append("- Добавлено в extras — реально попали в хвост (не пересекаются с itdog)")
    report.append("- Пропущено директив — include:/regexp:/keyword:/etc (не разворачиваются)")
    report.append("")

    report.append("⚠️ Предупреждения")
    report.append("")
    if not critical_lines and not warn_lines and not near_limit and truncated_count == 0 and bad_output_lines == 0 and v2fly_fail == 0:
        report.append("✅ Замечаний нет")
    else:
        if critical_lines:
            report.append("🔴 Ошибки")
            report.append("")
            report.extend(critical_lines)
            report.append("")
        if warn_lines or (near_limit and usage_pct < 96.0) or (usage_pct >= 85.0 and usage_pct < 96.0):
            report.append("🟡 Предупреждения")
            report.append("")
            if near_limit and usage_pct < 96.0:
                report.append(f"🟠 Почти лимит (≥ {threshold})")
            if usage_pct >= 85.0 and usage_pct < 96.0:
                report.append("🟡 Высокая загрузка лимита (≥ 85%)")
            if warn_lines:
                report.extend(warn_lines)
            report.append("")

    report.append("🔐 Хеши")
    report.append("")
    report.append(f"sha256(final): {sha}")
    report.append("")

    # Diagnostics tail
    intersection = len(itdog_set & v2fly_set)
    reserve = max_lines - final_total
    report.append("🧪 Диагностика сборки")
    report.append("")
    report.append(f"источник itdog: {itdog_total} домена (уник.)")
    report.append(f"v2fly extras: {v2fly_total} доменов (после вычитания пересечений)")
    report.append(f"пересечения itdog ∩ v2fly: {intersection}")
    report.append(f"итог до лимита: {final_total} строк")
    report.append(f"запас до лимита: {reserve} строк")
    report.append(f"здоровье v2fly: fail={v2fly_fail} 🔴 / empty={empty_count} 🟡")
    report.append(f"уровень: {sev.level}")
    report.append("")

    REPORT_OUT.write_text("\n".join(report).rstrip() + "\n", encoding="utf-8")

    # ------------------------- TELEGRAM -------------------------

    dt_msk = now_msk_dt()
    tg_date, tg_time = format_tg_date_time(dt_msk)

    run_url = build_run_url()

    # Build problems list with required icon scheme
    problems: List[str] = []

    # category failures are always red
    for c in failed_categories[:20]:
        problems.append(f"🔴 {c} — fail")

    # empty categories are yellow
    for c in empty_categories[:30]:
        problems.append(f"🟡 {c} — пусто")

    # near limit warning / error
    if usage_pct >= 96.0:
        problems.append("🔴 Почти лимит (критично)")
    elif usage_pct >= 85.0:
        problems.append("🟠 Почти лимит")

    # parse warnings (keep concise)
    for w in warnings[:10]:
        problems.append(f"🟡 {w}")

    if truncated_count > 0:
        problems.append(f"🔴 Обрезка по лимиту: {truncated_count}")

    if bad_output_lines > 0:
        problems.append(f"🔴 Некорректных строк: {bad_output_lines}")

    # Trend block (as approved)
    trend_lines: List[str] = []
    trend_lines.append("━━━━━━━━━━━━━━━━━━")
    trend_lines.append("📈 ТРЕНД")
    trend_lines.append("━━━━━━━━━━━━━━━━━━")
    if avg7_int is not None:
        trend_lines.append(f"Среднее (7): {avg7_int}")
    else:
        trend_lines.append("Среднее (7): —")
    if delta_prev is not None:
        trend_lines.append(f"Δ к прошлой: {delta_prev:+d}")
    else:
        trend_lines.append("Δ к прошлой: —")
    if deviation is not None:
        trend_lines.append(f"Отклонение: {deviation:+d}")
    else:
        trend_lines.append("Отклонение: —")
    trend_lines.append(trend_verdict)

    # Message header differs by severity
    tg: List[str] = []
        if sev.level == "ОШИБКА":
        tg.append("🚨 При ошибках")
        tg.append(sev.headline)
        tg.append(sev.status_line)
        tg.append("")
        tg.append(f"🗓 {tg_date}")
        tg.append(f"🕒 {tg_time}")
        tg.append("")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.append("📦 РЕЗУЛЬТАТ")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.append(f"📊 {final_total} / {max_lines} ({usage_pct}%)")
        tg.append(f"🧮 Остаток: {remaining} строк")
        tg.append("")
        tg.extend(trend_lines)
        tg.append("")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.append("⚠ ПРОБЛЕМЫ")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.extend(problems or ["—"])
        tg.append("")
        tg.append(f"🔐 sha256: {sha}")

    elif sev.level == "ПРЕДУПРЕЖДЕНИЕ":
        tg.append("🟡 При предупреждениях")
        tg.append(sev.headline)
        tg.append(sev.status_line)
        tg.append("")
        tg.append(f"🗓 {tg_date}")
        tg.append(f"🕒 {tg_time}")
        tg.append("")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.append("📦 РЕЗУЛЬТАТ")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.append(f"📊 {final_total} / {max_lines} ({usage_pct}%)")
        tg.append(f"🧮 Остаток: {remaining} строк")
        tg.append("")
        tg.extend(trend_lines)
        tg.append("")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.append("⚠ ПРОБЛЕМЫ")
        tg.append("━━━━━━━━━━━━━━━━━━")
        tg.extend(problems or ["—"])
        tg.append("")
        tg.append(f"🔐 sha256: {sha}")

    else:
        tg.append("🟢 При нормальной работе")
        tg.append(sev.headline)
        tg.append(sev.status_line)
        tg.append("")
        tg.append(f"🗓 {tg_date}")
        tg.append(f"🕒 {tg_time}")
        tg.append("")
        tg.append(f"📊 {final_total} / {max_lines} ({usage_pct}%)")
        tg.append("")
        tg.append("📈 ТРЕНД")
        if avg7_int is not None:
            tg.append(f"Среднее (7): {avg7_int}")
        if delta_prev is not None:
            tg.append(f"Δ к прошлой: {delta_prev:+d}")
        tg.append(trend_verdict)
        tg.append("")
        tg.append("✅ Замечаний нет")
        tg.append("")
        tg.append(f"🔐 sha256: {sha}")

    if run_url:
        tg.append("")
        tg.append("🔎 Run:")
        tg.append(run_url)

    tg.append("")
    tg.append("📎 Полный отчёт: dist/report.md")

    TG_MESSAGE_OUT.write_text("\n".join(tg).strip() + "\n", encoding="utf-8")

    # Alerts: only ПРЕДУПРЕЖДЕНИЕ/ОШИБКА
    if sev.level in ("ПРЕДУПРЕЖДЕНИЕ", "ОШИБКА"):
        alert: List[str] = []
        alert.append(f"{sev.emoji} KVAS Domains — {sev.level}")
        alert.append(f"🕒 {tg_date} {tg_time}")
        alert.append("")
        alert.append(f"📊 {final_total} / {max_lines} ({usage_pct}%) | остаток: {remaining}")
        if problems:
            alert.append("")
            alert.extend(problems[:25])
        alert.append("")
        alert.append(f"🔐 {sha}")
        TG_ALERT_OUT.write_text("\n".join(alert).strip() + "\n", encoding="utf-8")
    else:
        TG_ALERT_OUT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
