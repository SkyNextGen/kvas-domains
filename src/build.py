#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, List, Tuple, Dict, Set, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DIST_DIR = ROOT / "dist"
HISTORY_DIR = DIST_DIR / "history"

# itdog (база)
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"

# v2fly (категории -> data/<category>)
V2FLY_DATA_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
V2FLY_CATEGORIES_FILE = SRC_DIR / "v2fly_allow.txt"

# Итог и отчёты
FINAL_OUT = DIST_DIR / "inside-kvas.lst"
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATS_JSON = DIST_DIR / "stats.json"
DEBUG_V2FLY = DIST_DIR / "debug_v2fly.txt"

MAX_HISTORY = 12


DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)

# В v2fly берём только домены (plain / domain: / full:)
V2FLY_PREFIXES = ("full:", "domain:")


@dataclass
class FetchResult:
    ok: bool
    text: str
    error: Optional[str] = None
    status: Optional[int] = None


def ensure_dirs() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def now_msk_str() -> str:
    # МСК фиксированно UTC+3 (нам timezone-база не нужна)
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    return msk.strftime("%Y-%m-%d %H:%M МСК")


def http_get_text(url: str, timeout: int = 30) -> FetchResult:
    req = Request(url, headers={"User-Agent": "kvas-domains-builder/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            data = resp.read().decode(charset, errors="replace")
            return FetchResult(ok=True, text=data, status=getattr(resp, "status", None))
    except HTTPError as e:
        return FetchResult(ok=False, text="", error=f"HTTP {e.code}: {e.reason}", status=e.code)
    except URLError as e:
        return FetchResult(ok=False, text="", error=str(e), status=None)
    except Exception as e:
        return FetchResult(ok=False, text="", error=str(e), status=None)


def is_domain(s: str) -> bool:
    return bool(DOMAIN_RE.match(s.strip().lower()))


def normalize_domain(s: str) -> Optional[str]:
    s = s.strip().lower().replace("\r", "")
    if not s:
        return None
    if s.endswith("."):
        s = s[:-1]
    return s if is_domain(s) else None


def parse_itdog(text: str) -> List[str]:
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

        if any(line.startswith(p) for p in V2FLY_PREFIXES):
            _, val = line.split(":", 1)
            dom = normalize_domain(val)
            if dom:
                out.append(dom)
            continue

        dom = normalize_domain(line)
        if dom:
            out.append(dom)

        # include/regexp/keyword и т.п. не тащим — только домены
    return out


def read_v2fly_categories(path: Path) -> List[str]:
    if not path.exists():
        return []
    cats: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cats.append(line)
    return cats


def load_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def diff_lists(prev: Iterable[str], curr: Iterable[str]) -> Tuple[List[str], List[str]]:
    prev_set = set(prev)
    curr_set = set(curr)
    added = sorted(curr_set - prev_set)
    removed = sorted(prev_set - curr_set)
    return added, removed


def rotate_history(history_dir: Path, max_items: int) -> None:
    snaps = sorted(history_dir.glob("snapshot-*.lst"))
    for p in snaps[:-max_items]:
        p.unlink(missing_ok=True)

    diffs = sorted(history_dir.glob("diff-*.txt"))
    for p in diffs[:-max_items]:
        p.unlink(missing_ok=True)


def append_stats(total: int, itdog_count: int, v2fly_count: int, warnings: List[str]) -> Dict:
    rec = {
        "ts_utc": now_utc_iso(),
        "total": total,
        "itdog": itdog_count,
        "v2fly": v2fly_count,
        "warnings": warnings,
    }

    if STATS_JSON.exists():
        try:
            data = json.loads(STATS_JSON.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
    else:
        data = []

    data.append(rec)
    data = data[-200:]

    STATS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    prev = data[-2] if len(data) >= 2 else None
    return {
        "first": data[0],
        "prev": prev,
        "count": len(data),
        "min_total": min(x["total"] for x in data),
        "max_total": max(x["total"] for x in data),
    }


def format_report(
    ts_utc: str,
    total_domains: int,
    prev_total: Optional[int],
    itdog_new_vs_prev: int,
    v2fly_new_vs_prev: int,
    warnings: List[str],
    added: List[str],
    removed: List[str],
    stats_info: Dict,
) -> str:
    delta = (total_domains - prev_total) if prev_total is not None else None
    delta_str = f"{delta:+d}" if delta is not None else "—"

    lines: List[str] = []
    lines.append(f"UTC: {ts_utc}\n")
    lines.append(f"- Итог: {total_domains} (Δ {delta_str})")
    lines.append(f"- itdog новых: {itdog_new_vs_prev}")
    lines.append(f"- v2fly новых: {v2fly_new_vs_prev}\n")

    lines.append("## Предупреждения\n")
    lines.append("\n".join(warnings) if warnings else "нет")
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

    return "\n".join(lines)


def build_tg_message(ts_msk: str, total: int, delta_total: Optional[int], warnings: List[str]) -> str:
    delta_str = f"{delta_total:+d}" if delta_total is not None else "—"
    warn_line = "⚠️ Есть предупреждения" if warnings else "✅ Без предупреждений"
    return (
        f"📦 KVAS Domains — сборка завершена\n"
        f"🕒 {ts_msk}\n\n"
        f"📌 Итоговых доменов: {total} (Δ {delta_str})\n"
        f"{warn_line}\n"
    )


def build_tg_alert(ts_msk: str, warnings: List[str]) -> str:
    if not warnings:
        return ""
    body = "\n".join([f"- {w}" for w in warnings])
    return (
        f"⚠️ KVAS Domains — предупреждения\n"
        f"🕒 {ts_msk}\n\n"
        f"{body}\n"
    )


def main() -> int:
    ensure_dirs()

    ts_utc = now_utc_iso()
    ts_msk = now_msk_str()

    prev_final = load_lines(FINAL_OUT)
    prev_total = len(set(prev_final)) if prev_final else None
    prev_set = set(prev_final)

    warnings: List[str] = []

    # itdog
    itdog_fetch = http_get_text(ITDOG_URL)
    if not itdog_fetch.ok:
        warnings.append(f"itdog: не удалось скачать ({itdog_fetch.error})")
        itdog_list: List[str] = []
    else:
        itdog_list = parse_itdog(itdog_fetch.text)
        if len(itdog_list) == 0:
            warnings.append("itdog: список скачался, но пустой")

    # v2fly
    cats = read_v2fly_categories(V2FLY_CATEGORIES_FILE)
    v2fly_all: List[str] = []
    v2fly_fail: List[str] = []

    debug_lines: List[str] = []
    debug_lines.append(f"UTC: {ts_utc}")
    debug_lines.append(f"Categories file: {V2FLY_CATEGORIES_FILE.as_posix()}")
    debug_lines.append(f"Categories count: {len(cats)}")
    debug_lines.append("")

    if not V2FLY_CATEGORIES_FILE.exists():
        warnings.append("v2fly: нет файла src/v2fly_categories.txt (v2fly пропущен)")
    elif len(cats) == 0:
        warnings.append("v2fly: файл категорий пустой (v2fly пропущен)")
    else:
        for cat in cats:
            url = f"{V2FLY_DATA_BASE}/{cat}"
            res = http_get_text(url)
            if not res.ok:
                v2fly_fail.append(f"{cat}: {res.error}")
                debug_lines.append(f"[FAIL] {cat} -> {res.error}")
                continue

            parsed = parse_v2fly_file(res.text)
            v2fly_all.extend(parsed)
            debug_lines.append(f"[OK]   {cat} -> lines={len(res.text.splitlines())}, domains={len(parsed)}")

        if v2fly_fail:
            warnings.append(f"v2fly: не скачались категории: {len(v2fly_fail)}/{len(cats)}")
        if len(v2fly_all) == 0:
            warnings.append("v2fly: категории указаны, но доменов не получено")

    DEBUG_V2FLY.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

    # Сборка финала
    itdog_unique = list(dict.fromkeys(itdog_list))
    itdog_set = set(itdog_unique)

    # v2fly в хвост, без дублей относительно itdog
    v2fly_unique_sorted = sorted({d for d in v2fly_all if d not in itdog_set})

    final_list = itdog_unique + v2fly_unique_sorted
    FINAL_OUT.write_text("\n".join(final_list) + "\n", encoding="utf-8")

    added, removed = diff_lists(prev_final, final_list)

    itdog_new_vs_prev = len(set(itdog_unique) - prev_set) if prev_final else len(set(itdog_unique))
    v2fly_new_vs_prev = len(set(v2fly_unique_sorted) - prev_set) if prev_final else len(set(v2fly_unique_sorted))

    total_domains = len(set(final_list))

    # history (снапшот только если реально изменилось)
    if prev_final and (set(prev_final) != set(final_list)):
        stamp = now_stamp()
        snap_prev = HISTORY_DIR / f"snapshot-{stamp}-prev.lst"
        snap_new = HISTORY_DIR / f"snapshot-{stamp}-new.lst"
        diff_file = HISTORY_DIR / f"diff-{stamp}.txt"

        snap_prev.write_text("\n".join(prev_final) + "\n", encoding="utf-8")
        snap_new.write_text("\n".join(final_list) + "\n", encoding="utf-8")

        diff_lines: List[str] = []
        diff_lines.append(f"Added: {len(added)}")
        diff_lines.extend([f"+ {x}" for x in added[:200]])
        diff_lines.append("")
        diff_lines.append(f"Removed: {len(removed)}")
        diff_lines.extend([f"- {x}" for x in removed[:200]])
        diff_file.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")

        rotate_history(HISTORY_DIR, MAX_HISTORY)

    # stats
    stats_info = append_stats(
        total=total_domains,
        itdog_count=len(itdog_unique),
        v2fly_count=len(v2fly_unique_sorted),
        warnings=warnings,
    )
    prev_total_from_stats = stats_info["prev"]["total"] if stats_info.get("prev") else None
    delta_total = (total_domains - prev_total_from_stats) if prev_total_from_stats is not None else None

    # report.md
    REPORT_OUT.write_text(
        format_report(
            ts_utc=ts_utc,
            total_domains=total_domains,
            prev_total=prev_total,
            itdog_new_vs_prev=itdog_new_vs_prev,
            v2fly_new_vs_prev=v2fly_new_vs_prev,
            warnings=warnings,
            added=added,
            removed=removed,
            stats_info=stats_info,
        ),
        encoding="utf-8",
    )

    # tg message / alert
    TG_MESSAGE_OUT.write_text(build_tg_message(ts_msk, total_domains, delta_total, warnings), encoding="utf-8")

    alert_text = build_tg_alert(ts_msk, warnings)
    if alert_text:
        TG_ALERT_OUT.write_text(alert_text, encoding="utf-8")
    else:
        TG_ALERT_OUT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
