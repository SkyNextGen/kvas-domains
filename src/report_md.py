#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from report_common import (
    DIST,
    STATE_JSON,
    STATS_JSON,
    REPORT_MD,
    load_json,
    dump_json,
    pct,
    limit_badge,
    short_hash,
    status_emoji,
    diff_lists,
    fmt_build_time_msk,
    trend_eval,
    repo_report_url,
    classify_severity,
)


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


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict) or not state:
        # fallback must be handled in orchestrator (report.py), but keep safe
        state = {}

    stats = load_json(STATS_JSON, [])
    if not isinstance(stats, list):
        stats = []
    prev_rec = stats[-2] if len(stats) >= 2 and isinstance(stats[-2], dict) else None

    REPORT_MD.write_text(format_report_md(state, stats, prev_rec), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
