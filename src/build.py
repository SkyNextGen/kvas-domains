#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# -------------------------------------------------------------------
# Пути/файлы проекта
# -------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
DIST_DIR = ROOT_DIR / "dist"
HISTORY_DIR = DIST_DIR / "history"

# Источники
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"
V2FLY_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
V2FLY_CATEGORIES_FILE = SRC_DIR / "v2fly_allow.txt"

# Итоговые артефакты
FINAL_OUT = DIST_DIR / "inside-kvas.lst"
V2FLY_ONLY_OUT = DIST_DIR / "v2fly-only.lst"
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATE_JSON = DIST_DIR / "state.json"
STATS_JSON = DIST_DIR / "stats.json"
DEBUG_V2FLY = DIST_DIR / "debug_v2fly.txt"

MAX_HISTORY = 12

# Лимиты (под Kvas)
LIST_LIMIT = 3000
NEAR_LIMIT_AT = 2800  # “почти упёрлись”


# -------------------------------------------------------------------
# Валидация доменов
# -------------------------------------------------------------------

DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)

# В v2fly иногда попадаются записи с префиксами.
V2FLY_PREFIXES = ("full:", "domain:")


@dataclass
class FetchResult:
    ok: bool
    text: str
    error: Optional[str] = None
    status: Optional[int] = None


@dataclass
class V2FlyRow:
    category: str
    ok: bool
    domains: int
    note: str


# -------------------------------------------------------------------
# Время
# -------------------------------------------------------------------

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def now_msk_str() -> str:
    # Москва: UTC+3 (без DST)
    msk = timezone(timedelta(hours=3))
    return datetime.now(msk).replace(microsecond=0).isoformat()


# -------------------------------------------------------------------
# Сеть/скачивание
# -------------------------------------------------------------------

def fetch_text(url: str, timeout: int = 25) -> FetchResult:
    try:
        req = Request(url, headers={"User-Agent": "kvas-domains-builder/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return FetchResult(ok=True, text=data.decode("utf-8", errors="replace"), status=getattr(resp, "status", 200))
    except HTTPError as e:
        return FetchResult(ok=False, text="", error=f"HTTP {e.code}", status=e.code)
    except URLError as e:
        return FetchResult(ok=False, text="", error=str(e), status=None)
    except Exception as e:
        return FetchResult(ok=False, text="", error=str(e), status=None)


# -------------------------------------------------------------------
# Парсинг
# -------------------------------------------------------------------

def normalize_domain(s: str) -> Optional[str]:
    s = s.strip()
    if not s:
        return None

    # на всякий случай убираем пробелы/табуляции/комменты хвоста
    s = s.split("#", 1)[0].strip()
    if not s:
        return None

    # иногда встречается "domain:example.com" / "full:example.com"
    if any(s.startswith(p) for p in V2FLY_PREFIXES):
        _, s = s.split(":", 1)
        s = s.strip()

    s = s.lower().strip(".")
    if DOMAIN_RE.match(s):
        return s
    return None


def parse_plain_domains(text: str) -> List[str]:
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        dom = normalize_domain(line)
        if dom:
            out.append(dom)
    return out


def parse_v2fly_file(text: str) -> List[str]:
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # v2fly форматы:
        #   full:xxx
        #   domain:xxx
        #   xxx
        # + есть мусор типа regexp/ipcidr — оно нам не нужно
        if any(line.startswith(p) for p in V2FLY_PREFIXES):
            dom = normalize_domain(line)
            if dom:
                out.append(dom)
            continue

        dom = normalize_domain(line)
        if dom:
            out.append(dom)

    return out


def read_categories_file(path: Path) -> List[str]:
    if not path.exists():
        return []
    cats: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cats.append(line)
    return cats


# -------------------------------------------------------------------
# Состояние (prev build) и diff
# -------------------------------------------------------------------

def load_prev_final() -> List[str]:
    if not STATE_JSON.exists():
        return []
    try:
        data = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        prev = data.get("prev_final", [])
        if isinstance(prev, list):
            return [str(x) for x in prev]
    except Exception:
        pass
    return []


def save_state(prev_final: List[str]) -> None:
    payload = {
        "ts_utc": now_utc_iso(),
        "prev_final": prev_final,
    }
    STATE_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def diff_lists(prev: List[str], curr: List[str]) -> Tuple[List[str], List[str]]:
    prev_set = set(prev)
    curr_set = set(curr)
    added = sorted(curr_set - prev_set)
    removed = sorted(prev_set - curr_set)
    return added, removed


def rotate_history(history_dir: Path, keep: int) -> None:
    if not history_dir.exists():
        return
    items = sorted(history_dir.glob("*.lst"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in items[keep:]:
        p.unlink(missing_ok=True)


# -------------------------------------------------------------------
# Stats (рост за всё время)
# -------------------------------------------------------------------

def append_stats(total: int, itdog_count: int, v2fly_count: int, warnings: List[str]) -> Dict:
    rec = {
        "ts_utc": now_utc_iso(),
        "total": total,
        "itdog": itdog_count,
        "v2fly": v2fly_count,
        "warnings": warnings,
    }

    data = {"history": []}
    if STATS_JSON.exists():
        try:
            data = json.loads(STATS_JSON.read_text(encoding="utf-8"))
            if "history" not in data or not isinstance(data["history"], list):
                data = {"history": []}
        except Exception:
            data = {"history": []}

    data["history"].append(rec)
    STATS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    hist = data["history"]
    totals = [x.get("total", 0) for x in hist if isinstance(x, dict)]
    first = hist[0] if hist else None
    prev = hist[-2] if len(hist) >= 2 else None

    return {
        "count": len(hist),
        "min_total": min(totals) if totals else total,
        "max_total": max(totals) if totals else total,
        "first": first or rec,
        "prev": prev,
    }


# -------------------------------------------------------------------
# Отчёт/Telegram
# -------------------------------------------------------------------

def build_v2fly_table(rows: List[V2FlyRow]) -> str:
    if not rows:
        return "нет"

    lines = []
    lines.append("| Категория | Статус | Доменов | Примечание |")
    lines.append("|---|---:|---:|---|")
    for r in rows:
        status = "OK" if r.ok else "FAIL"
        note = r.note.replace("\n", " ").strip()
        lines.append(f"| `{r.category}` | {status} | {r.domains} | {note} |")
    return "\n".join(lines)


def build_report_md(
    ts_utc: str,
    ts_msk: str,
    total_domains: int,
    prev_total: Optional[int],
    itdog_new_vs_prev: int,
    v2fly_new_vs_prev: int,
    warnings: List[str],
    added: List[str],
    removed: List[str],
    stats_info: Dict,
    v2fly_rows: List[V2FlyRow],
) -> str:
    delta = (total_domains - prev_total) if prev_total is not None else None
    delta_str = f"{delta:+d}" if delta is not None else "—"

    lines: List[str] = []
    lines.append(f"MSK: {ts_msk}")
    lines.append(f"UTC: {ts_utc}\n")

    lines.append(f"- Итог: {total_domains} (Δ {delta_str})")
    lines.append(f"- itdog новых: {itdog_new_vs_prev}")
    lines.append(f"- v2fly новых: {v2fly_new_vs_prev}\n")

    lines.append("## v2fly (по категориям)\n")
    lines.append(build_v2fly_table(v2fly_rows))
    lines.append("")

    lines.append("## Предупреждения\n")
    lines.append("\n".join([f"- {w}" for w in warnings]) if warnings else "нет")
    lines.append("")

    lines.append("## Топ добавленных\n")
    lines.append("\n".join(added[:20]) if added else "нет")
    lines.append("")

    lines.append("## Топ удалённых\n")
    lines.append("\n".join(removed[:20]) if removed else "нет")
    lines.append("")

    lines.append("## Рост за всё время\n")
    lines.append(f"- Билдов: {stats_info['count']}")
    lines.append(f"- Минимум: {stats_info['min_total']}")
    lines.append(f"- Максимум: {stats_info['max_total']}")
    lines.append(f"- Рост с первого: {total_domains - stats_info['first']['total']:+d}")

    return "\n".join(lines) + "\n"


def build_tg_message(ts_msk: str, total: int, delta_total: Optional[int], warnings: List[str]) -> str:
    delta_str = f"{delta_total:+d}" if delta_total is not None else "—"
    warn_line = "⚠️ Есть предупреждения" if warnings else "✅ Предупреждений нет"
    return f"📦 KVAS Domains\n🕒 {ts_msk}\n📄 Итог: {total} (Δ {delta_str})\n{warn_line}\n"


def build_tg_alert(ts_msk: str, warnings: List[str]) -> str:
    if not warnings:
        return ""
    lines = []
    lines.append("🚨 KVAS Domains — предупреждения")
    lines.append(f"🕒 {ts_msk}\n")
    for w in warnings:
        lines.append(f"• {w}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def ensure_dirs() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    ensure_dirs()

    ts_utc = now_utc_iso()
    ts_msk = now_msk_str()

    prev_final = load_prev_final()
    prev_set = set(prev_final)
    prev_total = len(prev_final) if prev_final else None

    warnings: List[str] = []

    # 1) itdog
    itdog_res = fetch_text(ITDOG_URL)
    if not itdog_res.ok:
        warnings.append(f"itdog: не скачался список ({itdog_res.error})")
        itdog_list: List[str] = []
    else:
        itdog_list = parse_plain_domains(itdog_res.text)

    if len(itdog_list) == 0:
        warnings.append("itdog: список пустой (0 доменов)")

    itdog_unique = list(dict.fromkeys(itdog_list))  # сохраняем порядок
    itdog_set = set(itdog_unique)

    # 2) v2fly
    cats = read_categories_file(V2FLY_CATEGORIES_FILE)
    v2fly_all: List[str] = []
    v2fly_fail: List[str] = []
    v2fly_rows: List[V2FlyRow] = []
    debug_lines: List[str] = []

    if cats:
        for cat in cats:
            url = f"{V2FLY_BASE}/{cat}"
            res = fetch_text(url)

            if not res.ok:
                v2fly_fail.append(cat)
                note = res.error or "ошибка"
                if res.status == 404:
                    note = "HTTP 404 (категория не найдена)"
                v2fly_rows.append(V2FlyRow(category=cat, ok=False, domains=0, note=note))
                debug_lines.append(f"[FAIL] {cat} -> {note}")
                continue

            parsed = parse_v2fly_file(res.text)
            v2fly_all.extend(parsed)

            v2fly_rows.append(V2FlyRow(category=cat, ok=True, domains=len(parsed), note=""))
            debug_lines.append(f"[OK]   {cat} -> lines={len(res.text.splitlines())}, domains={len(parsed)}")

        if v2fly_fail:
            warnings.append(f"v2fly: не скачались категории: {len(v2fly_fail)}/{len(cats)}")
        if len(v2fly_all) == 0:
            warnings.append("v2fly: категории указаны, но доменов не получено")
    else:
        debug_lines.append("[INFO] v2fly: categories file empty or missing")

    DEBUG_V2FLY.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

    # v2fly-only (чисто для проверки фильтра)
    v2fly_only = sorted(set(v2fly_all))
    V2FLY_ONLY_OUT.write_text("\n".join(v2fly_only) + "\n", encoding="utf-8")

    # v2fly в хвост inside-kvas: без дублей относительно itdog
    v2fly_unique_sorted = sorted({d for d in v2fly_all if d not in itdog_set})

    final_list = itdog_unique + v2fly_unique_sorted
    total_domains = len(final_list)

    # near-limit / overflow
    if total_domains >= LIST_LIMIT:
        warnings.append(f"лимит: превышение ({total_domains}/{LIST_LIMIT})")
    elif total_domains >= NEAR_LIMIT_AT:
        warnings.append(f"лимит: близко к пределу ({total_domains}/{LIST_LIMIT})")

    FINAL_OUT.write_text("\n".join(final_list) + "\n", encoding="utf-8")

    # history snapshot (для диффов руками)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    hist_file = HISTORY_DIR / f"inside-kvas.{stamp}.lst"
    hist_file.write_text("\n".join(final_list) + "\n", encoding="utf-8")
    rotate_history(HISTORY_DIR, MAX_HISTORY)

    # diff vs prev
    added, removed = diff_lists(prev_final, final_list)

    itdog_new_vs_prev = len(set(itdog_unique) - prev_set) if prev_final else len(set(itdog_unique))
    v2fly_new_vs_prev = len(set(v2fly_unique_sorted) - prev_set) if prev_final else len(set(v2fly_unique_sorted))

    # stats
    stats_info = append_stats(
        total=total_domains,
        itdog_count=len(itdog_unique),
        v2fly_count=len(v2fly_unique_sorted),
        warnings=warnings,
    )

    prev_total_from_stats = stats_info["prev"]["total"] if stats_info.get("prev") else None
    delta_total = (total_domains - prev_total_from_stats) if prev_total_from_stats is not None else None

    # report
    REPORT_OUT.write_text(
        build_report_md(
            ts_utc=ts_utc,
            ts_msk=ts_msk,
            total_domains=total_domains,
            prev_total=prev_total,
            itdog_new_vs_prev=itdog_new_vs_prev,
            v2fly_new_vs_prev=v2fly_new_vs_prev,
            warnings=warnings,
            added=added,
            removed=removed,
            stats_info=stats_info,
            v2fly_rows=v2fly_rows,
        ),
        encoding="utf-8",
    )

    # tg message / alert (файлы — actions уже отправляет как умеет)
    TG_MESSAGE_OUT.write_text(build_tg_message(ts_msk, total_domains, delta_total, warnings), encoding="utf-8")
    TG_ALERT_OUT.write_text(build_tg_alert(ts_msk, warnings), encoding="utf-8")

    # state (следующий прогон будет сравнивать с этим)
    save_state(final_list)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
