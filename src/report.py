#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KVAS report + Telegram message generator.

Inputs:
- dist/state.json (produced by src/build.py)
- dist/stats.json (history; appended here)

Outputs:
- dist/report.md
- dist/tg_message.txt
- dist/tg_alert.txt (only when WARNING/ERROR; otherwise deleted)

Guarantees:
- from __future__ import annotations is at the top (no syntax traps)
- report.md is regenerated every run
- Telegram follows approved templates (ERROR / WARNING / OK)
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

STATE_JSON = DIST / "state.json"
REPORT_MD = DIST / "report.md"
TG_MESSAGE = DIST / "tg_message.txt"
TG_ALERT = DIST / "tg_alert.txt"
STATS_JSON = DIST / "stats.json"

MSK = timezone(timedelta(hours=3))
MONTHS_RU = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]


def load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fmt_build_time_msk(build_time_utc: str) -> str:
    # build_time_utc is ISO Z
    try:
        dt_utc = datetime.fromisoformat(build_time_utc.replace("Z", "+00:00")).astimezone(MSK)
    except Exception:
        dt_utc = datetime.now(timezone.utc).astimezone(MSK)
    m = MONTHS_RU[dt_utc.month - 1]
    return f"{dt_utc.day:02d} {m} {dt_utc.year}, {dt_utc:%H:%M} МСК"


def fmt_tg_date_time(build_time_utc: str) -> Tuple[str, str]:
    try:
        dt = datetime.fromisoformat(build_time_utc.replace("Z", "+00:00")).astimezone(MSK)
    except Exception:
        dt = datetime.now(timezone.utc).astimezone(MSK)
    return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M:%S МСК")


def diff_lists(prev: List[str], curr: List[str]) -> Tuple[List[str], List[str]]:
    p = set(prev or [])
    c = set(curr or [])
    added = sorted(c - p)
    removed = sorted(p - c)
    return added, removed


def short_hash(h: str) -> str:
    h = (h or "").strip()
    if len(h) < 10:
        return h or "—"
    return f"{h[:4]}…{h[-4:]}"


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


def status_emoji(status: str) -> str:
    s = (status or "").upper()
    if s == "OK":
        return "🟢 ОК"
    if s == "EMPTY":
        return "🟡 ПУСТО"
    if s == "FAIL":
        return "🔴 ОШИБКА"
    return "—"


def classify_severity(state: Dict) -> str:
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
    """
    Append stats record and return (stats_list, prev_record).
    """
    stats = load_json(STATS_JSON, [])
    if not isinstance(stats, list):
        stats = []

    prev = stats[-1] if stats and isinstance(stats[-1], dict) else None

    rec = {
        "ts_utc": state.get("build_time_utc"),
        "total": int(state.get("final_total", 0)),
        "itdog": int(state.get("itdog_total", 0)),
        "v2fly": int(state.get("v2fly_total", 0)),
        "severity": classify_severity(state),
        "warnings": state.get("warnings", []),
        "failed_categories": state.get("failed_categories", []),
        "empty_categories": state.get("empty_categories", []),
    }
    stats.append(rec)
    stats = stats[-400:]
    dump_json(STATS_JSON, stats)
    return stats, prev


def trend_block(stats: List[Dict], prev: Optional[Dict], curr_total: int) -> Tuple[int, int, int, str]:
    """
    Returns: avg7, delta, deviation, eval_line
    """
    totals = [int(x.get("total", 0)) for x in stats[-7:] if isinstance(x, dict)]
    if not totals:
        avg7 = curr_total
    else:
        avg7 = int(round(sum(totals) / len(totals)))

    prev_total = int(prev.get("total", 0)) if isinstance(prev, dict) else None
    delta = (curr_total - prev_total) if prev_total is not None else 0
    deviation = curr_total - avg7

    # Eval line per approved wording
    if avg7 > 0 and curr_total >= avg7 * 2:
        eval_line = "📈 Рост (выше среднего ×2)"
    else:
        # stable if abs deviation small relative to avg
        tol = max(10, int(round(avg7 * 0.01)))
        if abs(deviation) <= tol:
            eval_line = "➡ Стабильно"
        elif deviation > 0:
            eval_line = "📈 Рост"
        else:
            eval_line = "📉 Падение"

    return avg7, delta, deviation, eval_line


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

    # diffs
    prev = state.get("prev") if isinstance(state.get("prev"), dict) else {}
    it_added, it_removed = diff_lists(prev.get("itdog_domains", []), state.get("itdog_domains", []))
    v2_added, v2_removed = diff_lists(prev.get("v2fly_extras", []), state.get("v2fly_extras", []))
    f_added, f_removed = diff_lists(prev.get("final_domains", []), state.get("final_domains", []))

    # limit
    p = pct(final_total, max_lines)
    near = "НЕТ"
    near_mark = "✅"
    if final_total >= threshold:
        near = "ДА"
        near_mark = "⚠️"

    # warnings line
    warn_parts = []
    if len(failed_cats) > 0 or v2_fail > 0:
        warn_parts.append(f"{max(len(failed_cats), v2_fail)} ошибка загрузки")
    if len(empty_cats) > 0:
        warn_parts.append(f"{len(empty_cats)} пустая категория")
    if trunc > 0:
        warn_parts.append("есть обрезка по лимиту")
    if len(warns) > 0 and not warn_parts:
        warn_parts.append(f"{len(warns)} предупреждение")

    if warn_parts:
        warn_line = "⚠️ Есть предупреждения: " + ", ".join(warn_parts)
    else:
        warn_line = "✅ Предупреждений нет"

    # critical problems
    critical = []
    if failed_cats:
        critical.append("🔴 Категории не скачались/не распарсились: " + ", ".join(failed_cats))
    if trunc > 0:
        critical.append(f"🔴 Обрезка по лимиту: ДА (обрезано строк: {trunc})")
    if bad > 0:
        critical.append(f"🔴 Некорректные строки в выводе: {bad}")
    if p >= 96.0 or final_total >= threshold:
        critical.append(f"🔴 Почти лимит: {final_total} / {max_lines} ({p}%)")

    # v2fly table
    per_cat = state.get("v2fly_per_category") if isinstance(state.get("v2fly_per_category"), dict) else {}
    table_rows = []
    for c in cats:
        meta = per_cat.get(c, {}) if isinstance(per_cat.get(c, {}), dict) else {}
        table_rows.append(
            f"{c} | {int(meta.get('valid_domains',0))} | {int(meta.get('extras_added',0))} | "
            f"{int(meta.get('invalid_lines',0))} | {int(meta.get('skipped_directives',0))} | {status_emoji(str(meta.get('status','')))}"
        )
    if not table_rows:
        table_rows.append("— | 0 | 0 | 0 | 0 | —")

    sha = short_hash(str(state.get("sha256_final", "")))

    # diagnostics
    intersection = len(set(state.get("itdog_domains", [])) & set(state.get("v2fly_extras", [])))
    reserve = max_lines - final_total
    risk = "низкий 🟢" if p < 85.0 else ("средний 🟡" if p < 96.0 else "высокий 🔴")

    lines: List[str] = []
    lines.append("# 📊 Отчёт сборки доменов KVAS")
    lines.append("")
    lines.append(f"Сборка: {build_time}")
    lines.append(f"Репозиторий: {repo}")
    lines.append(f"Выходной файл: {output}")
    lines.append(f"Лимит строк: {max_lines}")
    lines.append("")

    if critical:
        lines.append("🔥 Критичные проблемы")
        lines.extend(critical)
        lines.append("")

    lines.append("🚦 Статус сборки")
    lines.append("")
    lines.append("✅ Сборка завершена" if classify_severity(state) != "ОШИБКА" else "🚨 Сборка завершена с ошибками")
    lines.append(warn_line)
    lines.append(f"🧾 Некорректных строк в итоговом выводе: {bad}")
    lines.append(f"✂️ Обрезка по лимиту: {'НЕТ' if trunc == 0 else 'ДА'}")
    lines.append("")

    lines.append("📌 Сводка")
    lines.append("")
    lines.append("itdog")
    lines.append("")
    lines.append(f"всего: {itdog_total}")
    lines.append(f"изменение к прошлому запуску: +{len(it_added)} / -{len(it_removed)}")
    lines.append("")
    lines.append("v2fly (только extras — отсутствуют в itdog)")
    lines.append("")
    lines.append(f"всего extras: {v2_total}")
    lines.append(f"изменение к прошлому запуску: +{len(v2_added)} / -{len(v2_removed)}")
    lines.append(f"категории: {len(cats)} (🟢 ok={v2_ok} / 🔴 fail={v2_fail} / 🟡 пусто={len(empty_cats)})")
    lines.append("")
    lines.append("итоговый список")
    lines.append("")
    lines.append(f"всего: {final_total}")
    lines.append(f"изменение к прошлому запуску: +{len(f_added)} / -{len(f_removed)}")
    lines.append(f"обрезано строк: {trunc}")
    lines.append("")

    lines.append("📈 Лимит")
    lines.append("")
    lines.append(f"использование: {final_total} / {max_lines} ({p}% занято) {limit_badge(p)}")
    lines.append(f"близко к лимиту: {near} (порог: {threshold}) {near_mark}")
    lines.append("")
    lines.append("Правило подсветки:")
    lines.append("🟢 до 85% — нормально | 🟡 85–96% — внимание | 🔴 ≥ 96% — критично")
    lines.append("")

    def block_changes(title: str, added: List[str], removed: List[str]) -> None:
        lines.append(title)
        lines.append("➕ Добавлено")
        if added:
            lines.extend(added[:20])
        else:
            lines.append("—")
        lines.append("")
        lines.append("➖ Удалено")
        if removed:
            lines.extend(removed[:20])
        else:
            lines.append("—")
        lines.append("")

    block_changes("🔄 Изменения itdog (топ 20)", it_added, it_removed)
    block_changes("🔄 Изменения v2fly extras (топ 20)", v2_added, v2_removed)
    block_changes("🔄 Изменения итогового списка (топ 20)", f_added, f_removed)

    lines.append("📂 Статистика v2fly по категориям")
    lines.append("")
    lines.append("Категория | Валидных доменов | Добавлено в extras | Некорректных строк | Пропущено директив | Статус")
    lines.append("---|---:|---:|---:|---:|---")
    lines.extend(table_rows)
    lines.append("")
    lines.append("Легенда статусов: 🟢 ОК | 🟡 ПУСТО (0 валидных доменов) | 🔴 ОШИБКА (скачивание/парсинг)")
    lines.append("")
    lines.append("Примечания")
    lines.append("- Валидных доменов — извлечённые из категории после фильтра (full:/domain:/голые домены)")
    lines.append("- Добавлено в extras — реально попали в хвост (не пересекаются с itdog)")
    lines.append("- Пропущено директив — include:/regexp:/keyword:/etc (не разворачиваются)")
    lines.append("")

    lines.append("⚠️ Предупреждения")
    lines.append("")
    if failed_cats:
        lines.append("🔴 Ошибки (требуют внимания)")
        lines.append("Категории не скачались/не распарсились: " + ", ".join(failed_cats))
        lines.append("")
    if empty_cats:
        lines.append("🟡 Аномалии (не критично, но полезно знать)")
        lines.append("Пустые категории (0 доменов): " + ", ".join(empty_cats))
        lines.append("")
    if not failed_cats and not empty_cats and not warns and trunc == 0 and bad == 0:
        lines.append("✅ Замечаний нет")
        lines.append("")

    lines.append("✅ Проверки качества")
    lines.append("")
    lines.append(f"Некорректные строки в выводе: {bad}")
    lines.append(f"Обрезка по лимиту: {'НЕТ' if trunc == 0 else 'ДА'}")
    lines.append("")

    lines.append("🔐 Хеши")
    lines.append("")
    lines.append(f"sha256(final): {sha}")
    lines.append("")

    lines.append("🧪 Диагностика сборки")
    lines.append("")
    lines.append(f"источник itdog: {itdog_total} домена (уник.)")
    lines.append(f"v2fly extras: {v2_total} доменов (после вычитания пересечений)")
    lines.append("пересечения itdog ∩ v2fly: (скрыто / можно добавить при желании)")
    lines.append("")
    lines.append(f"итог до лимита: {final_total} строк")
    lines.append(f"запас до лимита: {reserve} строк")
    lines.append(f"риск переполнения лимита: {risk}")
    lines.append("")
    lines.append(f"здоровье v2fly: fail={max(len(failed_cats), v2_fail)} 🔴 / empty={len(empty_cats)} 🟡")
    if failed_cats or empty_cats:
        recs = []
        if failed_cats:
            recs.append("проверить " + ", ".join([x.split(" ",1)[0] for x in failed_cats]))
        if empty_cats:
            recs.append("проверить " + ", ".join(empty_cats))
        lines.append("рекомендация: " + ", ".join(recs))
    return "\n".join(lines).rstrip() + "\n"


def tg_problems_lines(state: Dict) -> List[str]:
    lines: List[str] = []
    failed = state.get("failed_categories") or []
    empty = state.get("empty_categories") or []
    warns = state.get("warnings") or []

    # failed categories: already include "(HTTP ...)" when possible
    for f in failed:
        # "tiktok (HTTP 404)" -> "🔴 tiktok — 404"
        name = str(f)
        m = None
        if "HTTP" in name:
            m = name.split("HTTP", 1)[1].strip().strip("()")
            code = m.split()[0]
            cat = name.split("(", 1)[0].strip()
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
        lines.append(f"🔴 обрезка — {trunc}")

    bad = int(state.get("bad_output_lines", 0))
    if bad > 0:
        lines.append(f"🔴 некорректные строки — {bad}")

    # If we have generic warnings that are not categories, keep compact
    # (Do not spam; main problems above are enough.)
    return lines


def format_tg(state: Dict, stats: List[Dict], prev_rec: Optional[Dict]) -> Tuple[str, str]:
    """
    Returns (tg_message, tg_alert).
    """
    sev = classify_severity(state)
    date_s, time_s = fmt_tg_date_time(str(state.get("build_time_utc", "")))

    max_lines = int(state.get("max_lines", 3000))
    total = int(state.get("final_total", 0))
    p = pct(total, max_lines)
    rest = max_lines - total

    sha = short_hash(str(state.get("sha256_final", "")))

    avg7, delta, deviation, eval_line = trend_block(stats, prev_rec, total)

    problems = tg_problems_lines(state)

    # alert text (only when not OK)
    tg_alert = ""
    if sev != "ОК" and problems:
        tg_alert = "\n".join(problems) + "\n"

    if sev == "ОШИБКА":
        msg_lines = [
            "🚨 Сборка завершена с ошибками",
            "🔴 Критический статус",
            "",
            f"🗓 {date_s}",
            f"🕒 {time_s}",
            "",
            "━━━━━━━━━━━━━━━━━━",
            "📦 РЕЗУЛЬТАТ",
            "━━━━━━━━━━━━━━━━━━",
            f"📊 {total} / {max_lines} ({p}%)",
            f"🧮 Остаток: {rest} строк",
            "",
            "━━━━━━━━━━━━━━━━━━",
            "📈 ТРЕНД",
            "━━━━━━━━━━━━━━━━━━",
            f"Среднее (7): {avg7}",
            f"Δ к прошлой: {delta:+d}",
            f"Отклонение: {deviation:+d}",
            eval_line,
            "",
            "━━━━━━━━━━━━━━━━━━",
            "⚠ ПРОБЛЕМЫ",
            "━━━━━━━━━━━━━━━━━━",
        ]
        msg_lines += (problems if problems else ["—"])
        msg_lines += ["", f"🔐 sha256: {sha}"]
        return "\n".join(msg_lines).rstrip() + "\n", tg_alert

    if sev == "ПРЕДУПРЕЖДЕНИЕ":
        msg_lines = [
            "⚠️ Сборка завершена с предупреждениями",
            "🟡 Требует внимания",
            "",
            f"🗓 {date_s}",
            f"🕒 {time_s}",
            "",
            "━━━━━━━━━━━━━━━━━━",
            "📦 РЕЗУЛЬТАТ",
            "━━━━━━━━━━━━━━━━━━",
            f"📊 {total} / {max_lines} ({p}%)",
            f"🧮 Остаток: {rest} строк",
            "",
            "━━━━━━━━━━━━━━━━━━",
            "📈 ТРЕНД",
            "━━━━━━━━━━━━━━━━━━",
            f"Среднее (7): {avg7}",
            f"Δ к прошлой: {delta:+d}",
            f"Отклонение: {deviation:+d}",
            eval_line,
            "",
            "━━━━━━━━━━━━━━━━━━",
            "⚠ ПРОБЛЕМЫ",
            "━━━━━━━━━━━━━━━━━━",
        ]
        msg_lines += (problems if problems else ["—"])
        msg_lines += ["", f"🔐 sha256: {sha}"]
        return "\n".join(msg_lines).rstrip() + "\n", tg_alert

    # OK (short template)
    msg_lines = [
        "🚀 Сборка завершена",
        "🟢 Система стабильна",
        "",
        f"🗓 {date_s}",
        f"🕒 {time_s}",
        "",
        f"📊 {total} / {max_lines} ({p}%)",
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
    return "\n".join(msg_lines).rstrip() + "\n", tg_alert


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict) or not state:
        # Fallback: create minimal artifacts, do not crash workflow
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
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

    # report.md
    REPORT_MD.write_text(format_report_md(state, stats, prev_rec), encoding="utf-8")

    # telegram
    tg_msg, tg_alert = format_tg(state, stats, prev_rec)
    TG_MESSAGE.write_text(tg_msg, encoding="utf-8")
    if tg_alert.strip():
        TG_ALERT.write_text(tg_alert, encoding="utf-8")
    else:
        TG_ALERT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
