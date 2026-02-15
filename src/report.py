#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional


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


def now_msk():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))


def format_build_time(raw: str) -> str:
    s = (raw or "").replace("UTC", "").strip()
    try:
        dt_utc = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_msk = dt_utc.astimezone(timezone(timedelta(hours=3)))
    except Exception:
        return s or "—"

    months = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]
    m = months[dt_msk.month - 1]
    return f"{dt_msk.day:02d} {m} {dt_msk.year}, {dt_msk:%H:%M} МСК"


def usage_badge(pct: float) -> str:
    if pct >= 96: return "🔴"
    if pct >= 85: return "🟡"
    return "🟢"


# ------------------------- main -------------------------

def main():

    state = load_json(STATE_JSON, {})
    prev = state.get("prev", {}) or {}

    repo = state.get("repo", "unknown/unknown")
    output = state.get("output", "dist/inside-kvas.lst")
    max_lines = int(state.get("max_lines", 3000))
    threshold = int(state.get("near_limit_threshold", 2900))

    itdog = state.get("itdog_domains", []) or []
    v2fly_extras = state.get("v2fly_extras", []) or []
    v2fly_all = state.get("v2fly_all_domains", []) or []
    final = state.get("final_domains", []) or []

    itdog_total = len(set(itdog))
    v2fly_total = len(set(v2fly_extras))
    v2fly_all_total = len(set(v2fly_all))
    final_total = len(set(final))

    overlap_total = len(set(itdog) & set(v2fly_all))
    overlap_pct = round((overlap_total / v2fly_all_total) * 100, 1) if v2fly_all_total else 0.0
    extras_pct = round((v2fly_total / v2fly_all_total) * 100, 1) if v2fly_all_total else 0.0

    usage = round((final_total / max_lines) * 100, 1)
    badge = usage_badge(usage)
    near_limit = final_total >= threshold

    failed_categories = state.get("failed_categories", []) or []
    empty_categories = state.get("empty_categories", []) or []
    bad_lines = int(state.get("bad_output_lines", 0))
    truncated = int(state.get("truncated", 0))

    has_errors = bool(failed_categories) or bad_lines > 0
    has_warnings = bool(empty_categories) or near_limit or truncated > 0

    if has_errors:
        completion = "🚨 Сборка завершена с ошибками"
    elif has_warnings:
        completion = "⚠️ Сборка завершена с предупреждениями"
    else:
        completion = "🚀 Сборка завершена"

    if has_errors or usage >= 96:
        system_line = "🔴 Критический статус"
    elif has_warnings or usage >= 85:
        system_line = "🟡 Система требует внимания"
    else:
        system_line = "🟢 Система стабильна"

    build_time = format_build_time(state.get("build_time_utc", ""))
    sha = short_hash(state.get("sha256_final", ""))

    # ---------------- warnings block ----------------

    active = 0
    if failed_categories: active += 1
    if empty_categories: active += 1
    if near_limit: active += 1
    if bad_lines > 0: active += 1
    if truncated > 0: active += 1

    if active == 0:
        warn_header = "🟢 Проблем не обнаружено"
    else:
        warn_header = "🔴 Обнаружены проблемы"

    failed_inline = "НЕТ" if not failed_categories else ", ".join(failed_categories)
    empty_inline = "НЕТ" if not empty_categories else ", ".join(empty_categories)

    warnings_block = f"""
## ⚠ Предупреждения

{warn_header}
Всего активных предупреждений: {active}

- Не удалось получить категории (скачивание/парсинг): {failed_inline}
- Пустые категории (0 доменов): {empty_inline}
- Почти достигнут лимит (≥ {threshold} строк): {"ДА" if near_limit else "НЕТ"}
- Некорректные строки в выводе: {bad_lines}
- Обрезка по лимиту: {"ДА" if truncated > 0 else "НЕТ"}
"""

    # ---------------- report ----------------

    report = f"""# 📊 Отчёт сборки доменов KVAS

{completion}
{system_line}

Сборка: {build_time}
Репозиторий: {repo}
Файл: {output}
Лимит: {max_lines} строк

---

## 📦 Результат

- Итоговых строк: **{final_total}**
- Использование: **{usage}%** {badge}
- Запас до лимита: **{max_lines - final_total}** строк

---

## 🧪 Диагностика

- itdog уникальных: **{itdog_total}**
- v2fly всего (до фильтрации itdog): **{v2fly_all_total}**
- v2fly extras (после вычитания itdog): **{v2fly_total}** ({extras_pct}%)
- Пересечение источников itdog ∩ v2fly: **{overlap_total}** ({overlap_pct}%)
- Запас до лимита: **{max_lines - final_total}** строк

---

{warnings_block}

---

## 📝 Примечания

- `invalid_lines` = строки, отброшенные при парсинге из‑за некорректного формата (не домен/неподдерживаемая запись)

---

## 🔐 Хеш

sha256: {sha}
"""

    REPORT_OUT.write_text(report, encoding="utf-8")

    return 0


if __name__ == "__main__":
    main()
