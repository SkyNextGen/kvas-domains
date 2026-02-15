#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"

STATE_JSON = DIST_DIR / "state.json"
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATS_JSON = DIST_DIR / "stats.json"


# ------------------------- helpers -------------------------

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def short_hash(h: str) -> str:
    h = (h or "").strip()
    if len(h) < 10:
        return h
    return f"{h[:4]}…{h[-4:]}"


def now_msk_dt() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))


def format_date_msk(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")


def format_time_msk(d: datetime) -> str:
    return d.strftime("%H:%M:%S МСК")


def format_build_time_msk_from_state(build_time_utc_raw: str) -> str:
    """
    state.json хранит build_time_utc как 'YYYY-MM-DD HH:MM:SS UTC'
    или 'YYYY-MM-DD HH:MM:SS'
    """
    s = (build_time_utc_raw or "").replace("UTC", "").strip()
    try:
        dt_utc = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_msk = dt_utc.astimezone(timezone(timedelta(hours=3)))
    except Exception:
        return s or "—"

    months = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    m = months[dt_msk.month - 1]
    return f"{dt_msk.day:02d} {m} {dt_msk.year}, {dt_msk:%H:%M} МСК"


def diff_counts(prev_list: List[str], curr_list: List[str]) -> Tuple[int, int]:
    prev = set(prev_list or [])
    curr = set(curr_list or [])
    added = len(curr - prev)
    removed = len(prev - curr)
    return added, removed


def format_change(added: int, removed: int) -> str:
    return f"+{added} / −{removed}"


def usage_badge(pct: float) -> str:
    # 🟢 <85, 🟡 85–96, 🔴 ≥96
    if pct >= 96.0:
        return "🔴"
    if pct >= 85.0:
        return "🟡"
    return "🟢"


def near_limit_flag(total: int, threshold: int) -> bool:
    return total >= threshold


def status_text_table(status: str) -> str:
    s = (status or "").strip()
    if s.startswith("OK"):
        return "🟢 ОК"
    if s.startswith("EMPTY"):
        return "🟡 ПУСТО"
    if s.startswith("FAIL"):
        return "🔴 ОШИБКА"
    # fallback
    return s or "—"


def build_run_url() -> Optional[str]:
    server = os.getenv("GITHUB_SERVER_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


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
    data = data[-400:]
    STATS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if isinstance(prev_total, int):
        return total - prev_total
    return None


def last_totals_from_stats(n: int = 7) -> List[int]:
    data = load_json(STATS_JSON, [])
    if not isinstance(data, list) or not data:
        return []
    totals: List[int] = []
    for row in data[-n:]:
        if isinstance(row, dict) and isinstance(row.get("total"), int):
            totals.append(int(row["total"]))
    return totals


def avg(nums: List[int]) -> Optional[float]:
    if not nums:
        return None
    return sum(nums) / len(nums)


def ascii_trend_block(values: List[int]) -> str:
    """
    Однострочный мини-график на 7 значений.
    """
    if len(values) < 2:
        return "—"

    vmin = min(values)
    vmax = max(values)
    span = max(1, vmax - vmin)

    bars = "▁▂▃▄▅▆▇█"
    line = []
    for v in values:
        idx = int(round((v - vmin) / span * (len(bars) - 1)))
        idx = max(0, min(len(bars) - 1, idx))
        line.append(bars[idx])

    return f"{vmin} {''.join(line)} {vmax}"


def trend_label(curr_delta: Optional[int], avg_delta: Optional[float]) -> Tuple[str, str]:
    """
    Возвращает (стрелка/лейбл, оценка)
    """
    if curr_delta is None:
        return "➡", "недостаточно данных"

    if curr_delta > 0:
        arrow = "📈"
    elif curr_delta < 0:
        arrow = "📉"
    else:
        arrow = "➡"

    if avg_delta is None or avg_delta == 0:
        return arrow, "—"

    ratio = abs(curr_delta) / abs(avg_delta) if avg_delta != 0 else None
    if ratio is None:
        return arrow, "—"

    if ratio >= 2.0 and abs(curr_delta) >= 10:
        return arrow, "⚠ выше среднего ×2"
    return arrow, "норма"


def build_completion_line(has_errors: bool, has_warnings: bool) -> str:
    if has_errors:
        return "🚨 Сборка завершена с ошибками"
    if has_warnings:
        return "⚠️ Сборка завершена с предупреждениями"
    return "🚀 Сборка завершена"


def build_system_line(system_level: str) -> str:
    if system_level == "critical":
        return "🔴 Критический статус"
    if system_level == "attention":
        return "🟡 Система требует внимания"
    return "🟢 Система стабильна"


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
    if not isinstance(itdog_domains, list): itdog_domains = []
    if not isinstance(v2fly_extras, list): v2fly_extras = []
    if not isinstance(final_domains, list): final_domains = []

    itdog_total = len(set(itdog_domains))
    v2fly_total = len(set(v2fly_extras))
    final_total = len(set(final_domains))

    it_add, it_rem = diff_counts(prev.get("itdog_domains", []) or [], itdog_domains)
    v2_add, v2_rem = diff_counts(prev.get("v2fly_extras", []) or [], v2fly_extras)
    f_add, f_rem = diff_counts(prev.get("final_domains", []) or [], final_domains)

    it_change = format_change(it_add, it_rem)
    v2_change = format_change(v2_add, v2_rem)
    f_change = format_change(f_add, f_rem)

    v2fly_ok = int(state.get("v2fly_ok", 0))
    v2fly_fail = int(state.get("v2fly_fail", 0))
    truncated_count = int(state.get("truncated", 0))
    bad_output_lines = int(state.get("bad_output_lines", 0))

    warnings = state.get("warnings", []) or []
    failed_categories = state.get("failed_categories", []) or []
    empty_categories = state.get("empty_categories", []) or []
    if not isinstance(warnings, list): warnings = []
    if not isinstance(failed_categories, list): failed_categories = []
    if not isinstance(empty_categories, list): empty_categories = []

    usage_pct = round((final_total / max_lines) * 100, 1) if max_lines else 0.0
    badge = usage_badge(usage_pct)
    near_limit = near_limit_flag(final_total, threshold)

    has_errors = (v2fly_fail > 0) or (bad_output_lines > 0)
    has_warnings = bool(warnings) or bool(empty_categories) or near_limit or (truncated_count > 0)

    if has_errors or usage_pct >= 96.0:
        system_level = "critical"
    elif has_warnings or usage_pct >= 85.0:
        system_level = "attention"
    else:
        system_level = "stable"

    completion_line = build_completion_line(has_errors, has_warnings)
    system_line = build_system_line(system_level)

    build_time_utc = str(state.get("build_time_utc", "")).replace(" UTC", "")
    build_time_msk = format_build_time_msk_from_state(build_time_utc)

    sha = short_hash(str(state.get("sha256_final", "")))

    # trend
    delta_total = append_stats(final_total, itdog_total, v2fly_total, warnings)
    totals7_after = last_totals_from_stats(7)
    avg7 = avg(totals7_after)
    avg7_int = int(round(avg7)) if avg7 is not None else None
    deviation = (final_total - avg7_int) if avg7_int is not None else None

    deltas: List[int] = []
    if len(totals7_after) >= 2:
        for i in range(1, len(totals7_after)):
            deltas.append(totals7_after[i] - totals7_after[i - 1])
    avg_delta = avg(deltas) if deltas else None

    arrow, growth_eval = trend_label(delta_total, avg_delta)
    trend_ascii = ascii_trend_block(totals7_after) if totals7_after else "—"

    # intersection
    intersection = len(set(itdog_domains) & set(v2fly_extras))

    # v2fly per-category table (translated status)
    cats = state.get("v2fly_categories", []) or []
    per_cat = state.get("v2fly_per_category", {}) or {}
    if not isinstance(cats, list): cats = []
    if not isinstance(per_cat, dict): per_cat = {}
    cats_total = len(cats)

    table_rows: List[str] = []
    for cat in cats:
        d = per_cat.get(cat, {}) if isinstance(per_cat.get(cat, {}), dict) else {}
        table_rows.append(
            f"| {cat} | {int(d.get('valid_domains', 0))} | {int(d.get('extras_added', 0))} | "
            f"{int(d.get('invalid_lines', 0))} | {int(d.get('skipped_directives', 0))} | {status_text_table(str(d.get('status', '')))} |"
        )
    table_block = "\n".join(table_rows) if table_rows else "| — | 0 | 0 | 0 | 0 | — |"

    failed_inline = "none" if not failed_categories else ", ".join(failed_categories)
    empty_inline = "none" if not empty_categories else ", ".join(empty_categories)

    # report.md
    deviation_txt = "—" if deviation is None else (f"+{deviation}" if deviation >= 0 else str(deviation))
    delta_txt = "—" if delta_total is None else f"{delta_total:+d}"
    avg_delta_txt = "—" if avg_delta is None else f"{avg_delta:+.1f}"

    report = f"""# 📊 Отчёт сборки доменов KVAS

{completion_line}
{system_line}

**Сборка:** {build_time_msk}
**Репозиторий:** {repo}
**Файл:** {output}
**Лимит:** {max_lines} строк

---

## 📦 Результат

| Показатель | Значение |
|---|---:|
| Итоговых строк | **{final_total}** |
| Использование | **{usage_pct}%** {badge} |
| Запас до лимита | **{max_lines - final_total}** строк |
| Близко к лимиту (≥ {threshold}) | **{"ДА" if near_limit else "НЕТ"}** |
| Обрезка по лимиту | **{"ДА" if truncated_count > 0 else "НЕТ"}** |
| Некорректные строки в выводе | **{bad_output_lines}** |

---

## 📈 Тренд (последние 7 сборок)

- Среднее за 7: **{avg7_int if avg7_int is not None else "—"}**
- Текущий результат: **{final_total}**
- Отклонение от среднего: **{deviation_txt}**
- Изменение к прошлой сборке: **{delta_txt}**
- Средний прирост за 7: **{avg_delta_txt}**
- Динамика: {arrow} ({growth_eval})

Мини-график:
```
{trend_ascii}
```

---

## 🔄 Изменения (относительно прошлой сборки)

| Источник | Δ | Всего |
|---|---:|---:|
| 🟦 itdog | {it_change} | {itdog_total} |
| 🟩 v2fly extras | {v2_change} | {v2fly_total} |
| 🧩 итоговый файл | {f_change} | {final_total} |

---

## 📂 Статистика v2fly по категориям

| category | valid_domains | extras_added | invalid_lines | skipped_directives | status |
|---|---:|---:|---:|---:|---|
{table_block}

Примечания:
- `valid_domains` = домены, извлечённые из категории (full:/domain:/голые домены)
- `extras_added` = домены, реально попавшие в хвост (не пересекаются с itdog)
- `skipped_directives` = include:/regexp:/keyword:/etc (не разворачиваются)

---

## ⚠ Предупреждения

- Не удалось получить категории (скачивание/парсинг): {failed_inline}
- Пустые категории (0 доменов): {empty_inline}
- Почти достигнут лимит (≥ {threshold} строк): {"ДА" if near_limit else "НЕТ"}
- Некорректные строки в выводе: {bad_output_lines}
- Обрезка по лимиту: {"ДА" if truncated_count > 0 else "НЕТ"}

---

## 🧪 Диагностика

- itdog уникальных: **{itdog_total}**
- v2fly extras: **{v2fly_total}**
- Пересечение itdog ∩ v2fly: **{intersection}**
- Запас до лимита: **{max_lines - final_total}** строк
- v2fly категорий: **{cats_total}** (ok={v2fly_ok}, fail={v2fly_fail}, пусто={len(empty_categories)})

---

## 🔐 Хеш

`sha256: {sha}`
"""
    REPORT_OUT.write_text(report, encoding="utf-8")

    # Telegram caption (боевой формат)
    msk_now = now_msk_dt()
    tg_date = format_date_msk(msk_now)
    tg_time = format_time_msk(msk_now)
    run_url = build_run_url()

    if usage_pct >= 96.0:
        limit_state = "🔴 КРИТИЧЕСКОЕ приближение к лимиту"
    elif usage_pct >= 85.0:
        limit_state = "🟡 Требует внимания (лимит)"
    else:
        limit_state = "🟢 Лимит в норме"

    rest_line = f"🧮 Остаток: {max_lines - final_total} строк" if usage_pct >= 85.0 else None

    avg7_txt = str(avg7_int) if avg7_int is not None else "—"
    tg_delta_txt = "—" if delta_total is None else f"{delta_total:+d}"
    dev_txt = "—" if deviation is None else (f"+{deviation}" if deviation >= 0 else str(deviation))
    trend_eval_line = f"{arrow} {('Рост' if arrow=='📈' else ('Падение' if arrow=='📉' else 'Стабильно'))}"
    if growth_eval.startswith("⚠"):
        trend_eval_line += f" ({growth_eval})"

    problems: List[str] = []
    if failed_categories:
        problems.append("🔴 Ошибка загрузки: " + ", ".join(failed_categories[:3]))
    if empty_categories:
        problems.append("🟡 Пустые категории: " + ", ".join(empty_categories[:6]))
    if near_limit:
        problems.append(f"🟠 Почти достигнут лимит (≥ {threshold})")

    tg_lines: List[str] = [
        completion_line,
        system_line,
        "",
        f"🗓 {tg_date}",
        f"🕒 {tg_time}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📦 РЕЗУЛЬТАТ",
        "━━━━━━━━━━━━━━━━━━",
        "📄 inside-kvas.lst",
        f"📊 {final_total} / {max_lines} ({usage_pct}%)",
        limit_state,
    ]
    if rest_line:
        tg_lines.append(rest_line)

    tg_lines += [
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🔄 ИЗМЕНЕНИЯ",
        "━━━━━━━━━━━━━━━━━━",
        f"🟦 itdog         {it_change}   ({itdog_total})",
        f"🟩 v2fly extras  {v2_change}   ({v2fly_total})",
        f"🧩 итоговый файл {f_change}   ({final_total})",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📈 ТРЕНД",
        "━━━━━━━━━━━━━━━━━━",
        f"Среднее (7): {avg7_txt}",
        f"Δ к прошлой: {tg_delta_txt}",
        f"Отклонение: {dev_txt}",
        trend_eval_line,
    ]

    if has_errors or has_warnings:
        tg_lines += [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "⚠ ТРЕБУЕТСЯ ВМЕШАТЕЛЬСТВО" if (has_errors or usage_pct >= 96.0) else "⚠ ПРОБЛЕМЫ",
            "━━━━━━━━━━━━━━━━━━",
        ]
        if problems:
            tg_lines.extend(problems)
        else:
            tg_lines.append("⚠ Есть предупреждения (детали в отчёте)")
    else:
        tg_lines += ["", "✅ Замечаний нет"]

    tg_lines += ["", f"🔐 sha256: {sha}"]

    if run_url:
        tg_lines += ["", "🔎 Run:", run_url]

    tg_lines += ["", "📎 Полный отчёт во вложении"]

    TG_MESSAGE_OUT.write_text("\n".join(tg_lines).strip() + "\n", encoding="utf-8")

    # Telegram alert (отдельно) — только если реально есть предупреждения/ошибки
    if has_errors or has_warnings:
        alert_lines: List[str] = [
            "⚠️ KVAS Domains — предупреждения",
            f"🕒 {tg_date} {tg_time}",
            "",
        ]

        if failed_categories:
            alert_lines.append("🔴 Ошибки загрузки категорий:")
            for x in failed_categories[:20]:
                alert_lines.append(f"- {x}")
            alert_lines.append("")

        if near_limit:
            alert_lines.append(f"🟠 Почти достигнут лимит (≥ {threshold} строк)")
            alert_lines.append("")

        if empty_categories:
            alert_lines.append("🟡 Пустые категории:")
            for x in empty_categories[:30]:
                alert_lines.append(f"- {x}")
            alert_lines.append("")

        if warnings:
            alert_lines.append("ℹ️ Прочие предупреждения:")
            for w in warnings[:30]:
                alert_lines.append(f"- {w}")

        TG_ALERT_OUT.write_text("\n".join(alert_lines).strip() + "\n", encoding="utf-8")
    else:
        TG_ALERT_OUT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
