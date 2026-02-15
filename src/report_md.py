#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Dict, List, Optional

from report_common import (
    STATE_JSON,
    REPORT_MD,
    load_json,
    pct,
    limit_badge,
    short_hash,
    status_emoji,
    diff_lists,
    fmt_build_time_msk,
    trend_eval,
    repo_report_url,
)


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
    itd_prev = prev.get("itdog_domains") or []
    v2_prev = prev.get("v2fly_extras") or []
    fin_prev = prev.get("final_domains") or []

    itd_curr = state.get("itdog_domains") or []
    v2_curr = state.get("v2fly_extras") or []
    fin_curr = state.get("final_domains") or []

    itd_add, itd_del = diff_lists(itd_prev, itd_curr)
    v2_add, v2_del = diff_lists(v2_prev, v2_curr)
    fin_add, fin_del = diff_lists(fin_prev, fin_curr)

    def top20(items: List[str]) -> List[str]:
        return items[:20]

    # Metrics
    p = pct(final_total, max_lines)
    badge = limit_badge(p)
    reserve = max_lines - final_total
    near = (final_total >= threshold)
    url = repo_report_url(repo)
    sha = short_hash(str(state.get("sha256_final", "")))

    # Diagnostics
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
        problems.append(f"🔴 Обрезка по лимиту — {trunc} строк")
    if bad > 0:
        problems.append(f"🔴 Некорректные строки — {bad}")
    if warns:
        problems.append("⚠️ " + " / ".join(warns))

    # Title block
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
    L.append(f"> ### 📊 {final_total} / {max_lines} ({p:.1f}%) {badge}")
    L.append(f"> **Запас:** {reserve} строк  ")
    L.append(f"> **Обрезка:** {'ДА' if trunc > 0 else 'НЕТ'}  ")
    L.append(f"> **Некорректных строк:** {bad}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🚦 Статус")
    L.append("")
    if not problems:
        L.append("### ✅ Сборка завершена")
        L.append("✅ Замечаний нет")
    else:
        L.append("### ⚠️ Есть замечания")
        for p_line in problems:
            L.append(f"- {p_line}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 🧩 V2Fly категории")
    L.append("")
    if cats:
        L.append("| Категория | Вход | Итог | uniq | пересеч. | Статус |")
        L.append("|---|---:|---:|---:|---:|---|")
        per = state.get("v2fly_per_category") or {}
        for c in cats:
            rec = per.get(c) if isinstance(per, dict) else None
            if not isinstance(rec, dict):
                rec = {}
            src = int(rec.get("source", 0))
            outn = int(rec.get("output", 0))
            uniq = int(rec.get("uniq", 0))
            inter = int(rec.get("intersect", 0))
            st = status_emoji(str(rec.get("status", "")))
            L.append(f"| {c} | {src} | {outn} | {uniq} | {inter} | {st} |")
    else:
        L.append("> нет данных по категориям")
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
    L.append("### itd")
    L.append("**➕ Добавлено**")
    if itd_add:
        for x in top20(itd_add):
            L.append(f"- {x}")
    else:
        L.append("- —")
    L.append("")
    L.append("**➖ Удалено**")
    if itd_del:
        for x in top20(itd_del):
            L.append(f"- {x}")
    else:
        L.append("- —")
    L.append("")
    L.append("---")
    L.append("")
    L.append("### v2fly extras")
    L.append("**➕ Добавлено**")
    if v2_add:
        for x in top20(v2_add):
            L.append(f"- {x}")
    else:
        L.append("- —")
    L.append("")
    L.append("**➖ Удалено**")
    if v2_del:
        for x in top20(v2_del):
            L.append(f"- {x}")
    else:
        L.append("- —")
    L.append("")
    L.append("---")
    L.append("")
    L.append("### final")
    L.append("**➕ Добавлено**")
    if fin_add:
        for x in top20(fin_add):
            L.append(f"- {x}")
    else:
        L.append("- —")
    L.append("")
    L.append("**➖ Удалено**")
    if fin_del:
        for x in top20(fin_del):
            L.append(f"- {x}")
    else:
        L.append("- —")
    L.append("")
    L.append("---")
    L.append("")
    L.append("### 🧪 Диагностика")
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
    L.append(f"- fail={v2_fail} 🔴")
    L.append(f"- empty={len(empty_cats)} 🟡")
    L.append("")
    L.append("### ✅ Рекомендации")
    if problems:
        for p_line in problems:
            L.append(f"- {p_line}")
    else:
        L.append("- отсутствуют")
    L.append("")
    L.append("</details>")
    L.append("")
    return "\n".join(L).rstrip() + "\n"


def main() -> int:
    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict):
        state = {}
    stats = load_json(Path("dist/stats.json"), [])
    if not isinstance(stats, list):
        stats = []
    prev_rec = stats[-2] if len(stats) >= 2 and isinstance(stats[-2], dict) else None
    REPORT_MD.write_text(format_report_md(state, stats, prev_rec), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
