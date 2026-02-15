#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DIST_DIR = ROOT / "dist"
HISTORY_DIR = DIST_DIR / "history"

# itdog (база)
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"

# v2fly (категории -> data/<category>)
V2FLY_DATA_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
V2FLY_CATEGORIES_FILE = SRC_DIR / "v2fly_allow.txt"

# Выходы
FINAL_OUT = DIST_DIR / "inside-kvas.lst"
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATS_JSON = DIST_DIR / "stats.json"
STATE_JSON = DIST_DIR / "state.json"
DEBUG_V2FLY = DIST_DIR / "debug_v2fly.txt"

MAX_HISTORY = 12
MAX_LINES = 3000
NEAR_LIMIT_THRESHOLD = 2900

DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)

# В v2fly извлекаем домены только из:
# - голых доменов
# - domain:
# - full:
V2FLY_EXTRACT_PREFIXES = ("full:", "domain:")

# Директивы v2fly, которые не разворачиваем — считаем "skipped_directives"
# (список не исчерпывающий, но покрывает типовые)
V2FLY_DIRECTIVE_PREFIXES = (
    "include:",
    "regexp:",
    "keyword:",
    "suffix:",
    "prefix:",
    "geosite:",
    "ext:",
    "tag:",
    "and:",
    "or:",
    "not:",
    "port:",
    "ipcidr:",
    "ip:",
    "payload:",
    "cidr:",
)

@dataclass
class FetchResult:
    ok: bool
    text: str
    error: Optional[str] = None
    status: Optional[int] = None


@dataclass
class V2FlyParseStats:
    domains: List[str]
    invalid_lines: int
    skipped_directives: int


def ensure_dirs() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_utc_report_str() -> str:
    # "2026-02-14 09:31:12"
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def now_msk_str() -> str:
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    return msk.strftime("%Y-%m-%d %H:%M МСК")


def http_get_text(url: str, timeout: int = 30) -> FetchResult:
    req = Request(url, headers={"User-Agent": "kvas-domains-builder/2.0"})
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


def parse_v2fly_with_stats(text: str) -> V2FlyParseStats:
    domains: List[str] = []
    invalid_lines = 0
    skipped_directives = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # domain:/full:
        if any(line.startswith(p) for p in V2FLY_EXTRACT_PREFIXES):
            _, val = line.split(":", 1)
            dom = normalize_domain(val)
            if dom:
                domains.append(dom)
            else:
                invalid_lines += 1
            continue

        # директивы (include:/regexp:/keyword: и т.п.) — пропускаем
        if ":" in line and any(line.startswith(p) for p in V2FLY_DIRECTIVE_PREFIXES):
            skipped_directives += 1
            continue

        # попытка как "голый домен"
        dom = normalize_domain(line)
        if dom:
            domains.append(dom)
        else:
            # не директива и не домен => мусор
            invalid_lines += 1

    return V2FlyParseStats(domains=domains, invalid_lines=invalid_lines, skipped_directives=skipped_directives)


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


def diff_sets(prev: Set[str], curr: Set[str]) -> Tuple[List[str], List[str]]:
    added = sorted(curr - prev)
    removed = sorted(prev - curr)
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


def read_prev_state() -> Dict:
    if not STATE_JSON.exists():
        return {}
    try:
        data = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state(state: Dict) -> None:
    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(h: str) -> str:
    if not h or len(h) < 8:
        return h
    return f"{h[:4]}...{h[-4:]}"


def format_change(added: int, removed: int) -> str:
    return f"+{added} / -{removed}"


def format_top_list(items: List[str], limit: int = 20) -> str:
    if not items:
        return "- none"
    out = []
    for i, x in enumerate(items[:limit], 1):
        out.append(f"{i}. {x}")
    return "\n".join(out)


def make_v2fly_table_rows(per_cat: Dict[str, Dict]) -> str:
    # стабильный порядок: как в файле категорий
    rows: List[str] = []
    for cat, d in per_cat.items():
        rows.append(
            f"| {cat} | {d['valid_domains']} | {d['extras_added']} | {d['invalid_lines']} | {d['skipped_directives']} | {d['status']} |"
        )
    return "\n".join(rows)


def format_report_new(
    build_time_utc: str,
    repo: str,
    output: str,
    max_lines: int,
    itdog_total: int,
    itdog_change: str,
    v2fly_total: int,
    v2fly_change: str,
    v2fly_ok: int,
    v2fly_fail: int,
    final_total: int,
    final_change: str,
    truncated_count: int,
    itdog_added: List[str],
    itdog_removed: List[str],
    v2fly_added: List[str],
    v2fly_removed: List[str],
    final_added: List[str],
    final_removed: List[str],
    v2fly_table_rows: str,
    failed_cats: List[str],
    empty_cats: List[str],
    bad_output_lines: int,
    truncated_yesno: str,
    sha256_final: str,
) -> str:
    usage_pct = round((final_total / max_lines) * 100, 1) if max_lines else 0.0
    near_limit = "YES" if final_total >= NEAR_LIMIT_THRESHOLD else "NO"

    failed_block = "- none" if not failed_cats else "\n".join([f"  - {x}" for x in failed_cats])
    empty_block = "- none" if not empty_cats else "\n".join([f"  - {x}" for x in empty_cats])

    return f"""# KVAS domains build report

Build time (UTC): {build_time_utc}
Repo: {repo}
Output: {output}
Max lines: {max_lines}

## Summary
- itdog:
  - total: {itdog_total}
  - change vs prev: {itdog_change}
- v2fly (extras only: not in itdog):
  - total: {v2fly_total}
  - change vs prev: {v2fly_change}
  - lists: ok={v2fly_ok}, fail={v2fly_fail}
- final output:
  - total: {final_total}
  - change vs prev: {final_change}
  - truncated: {truncated_count}

## Limit status
- usage: {final_total} / {max_lines} ({usage_pct}%)
- near limit: {near_limit} (threshold: {NEAR_LIMIT_THRESHOLD})

## itdog changes vs prev (top 20)
### Added
{format_top_list(itdog_added, 20)}
### Removed
{format_top_list(itdog_removed, 20)}

## v2fly extras changes vs prev (top 20)
### Added
{format_top_list(v2fly_added, 20)}
### Removed
{format_top_list(v2fly_removed, 20)}

## final output changes vs prev (top 20)
### Added
{format_top_list(final_added, 20)}
### Removed
{format_top_list(final_removed, 20)}

## v2fly per-category stats
| category | valid_domains | extras_added | invalid_lines | skipped_directives | status |
|---|---:|---:|---:|---:|---|
{v2fly_table_rows}

Notes:
- `valid_domains` = домены, извлечённые из категории после фильтра (full:/domain:/голые домены)
- `extras_added` = домены, которые реально попали в хвост (не пересекаются с itdog)
- `skipped_directives` = include:/regexp:/keyword:/etc (мы их не разворачиваем)

## Warnings
- Failed categories (download/parse errors):
{failed_block}
- Empty categories (0 valid domains):
{empty_block}
- Bad output lines: {bad_output_lines}
- Truncated output: {truncated_yesno}

## Hashes
- sha256(final): {short_hash(sha256_final)}
"""


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

    ts_utc_iso = now_utc_iso()
    ts_utc_report = now_utc_report_str()
    ts_msk = now_msk_str()

    repo = os.getenv("GITHUB_REPOSITORY", "unknown/unknown")

    # prev state (для корректного +X/-Y по компонентам)
    prev_state = read_prev_state()
    prev_itdog_set = set(prev_state.get("itdog_domains", []) or [])
    prev_v2fly_set = set(prev_state.get("v2fly_extras", []) or [])
    prev_final_set = set(prev_state.get("final_domains", []) or [])

    warnings: List[str] = []
    failed_categories: List[str] = []
    empty_categories: List[str] = []

    # itdog
    itdog_fetch = http_get_text(ITDOG_URL)
    if not itdog_fetch.ok:
        warnings.append(f"itdog: не удалось скачать ({itdog_fetch.error})")
        itdog_list: List[str] = []
    else:
        itdog_list = parse_itdog(itdog_fetch.text)
        if len(itdog_list) == 0:
            warnings.append("itdog: список скачался, но пустой")

    itdog_unique = list(dict.fromkeys(itdog_list))
    itdog_set = set(itdog_unique)

    # v2fly
    cats = read_v2fly_categories(V2FLY_CATEGORIES_FILE)
    v2fly_domains_all: List[str] = []
    per_cat_stats: Dict[str, Dict] = {}

    debug_lines: List[str] = []
    debug_lines.append(f"UTC: {ts_utc_iso}")
    debug_lines.append(f"Categories file: {V2FLY_CATEGORIES_FILE.as_posix()}")
    debug_lines.append(f"Categories count: {len(cats)}")
    debug_lines.append("")

    if not V2FLY_CATEGORIES_FILE.exists():
        warnings.append("v2fly: нет файла src/v2fly_allow.txt (v2fly пропущен)")
    elif len(cats) == 0:
        warnings.append("v2fly: файл категорий пустой (v2fly пропущен)")
    else:
        for cat in cats:
            url = f"{V2FLY_DATA_BASE}/{cat}"
            res = http_get_text(url)

            if not res.ok:
                failed_categories.append(f"{cat} ({res.error})")
                per_cat_stats[cat] = {
                    "valid_domains": 0,
                    "extras_added": 0,
                    "invalid_lines": 0,
                    "skipped_directives": 0,
                    "status": "FAIL",
                }
                debug_lines.append(f"[FAIL] {cat} -> {res.error}")
                continue

            parsed = parse_v2fly_with_stats(res.text)
            valid = list(dict.fromkeys(parsed.domains))
            v2fly_domains_all.extend(valid)

            # extras vs itdog по конкретной категории
            extras = sorted({d for d in valid if d not in itdog_set})
            status = "OK"
            if len(valid) == 0:
                status = "EMPTY ⚠"
                empty_categories.append(cat)

            per_cat_stats[cat] = {
                "valid_domains": len(valid),
                "extras_added": len(extras),
                "invalid_lines": parsed.invalid_lines,
                "skipped_directives": parsed.skipped_directives,
                "status": status,
            }

            debug_lines.append(
                f"[OK]   {cat} -> lines={len(res.text.splitlines())}, domains={len(valid)}"
            )

        if failed_categories:
            warnings.append(f"v2fly: не скачались категории: {len(failed_categories)}/{len(cats)}")

        if len(v2fly_domains_all) == 0 and len(cats) > 0 and not failed_categories:
            warnings.append("v2fly: категории указаны, но доменов не получено")

    DEBUG_V2FLY.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

    # v2fly extras-only (не пересекаются с itdog)
    v2fly_extras_sorted = sorted({d for d in v2fly_domains_all if d not in itdog_set})
    v2fly_set = set(v2fly_extras_sorted)

    # финальная сборка: itdog + v2fly extras
    final_list_full = itdog_unique + v2fly_extras_sorted

    # валидация выходных строк (bad output lines)
    bad_output_lines = 0
    for x in final_list_full:
        if not is_domain(x):
            bad_output_lines += 1

    # лимит MAX_LINES (если нужно — режем хвост, но сохраняем порядок)
    truncated_count = 0
    if len(final_list_full) > MAX_LINES:
        truncated_count = len(final_list_full) - MAX_LINES
        final_list = final_list_full[:MAX_LINES]
    else:
        final_list = final_list_full

    final_set = set(final_list)
    truncated_yesno = "YES" if truncated_count > 0 else "NO"

    # запись финального файла
    FINAL_OUT.write_text("\n".join(final_list) + "\n", encoding="utf-8")

    # diffs (по состоянию из state.json; если state отсутствовал — diffs будут относительно пустого)
    itdog_added, itdog_removed = diff_sets(prev_itdog_set, itdog_set)
    v2fly_added, v2fly_removed = diff_sets(prev_v2fly_set, v2fly_set)
    final_added, final_removed = diff_sets(prev_final_set, final_set)

    itdog_change = format_change(len(itdog_added), len(itdog_removed))
    v2fly_change = format_change(len(v2fly_added), len(v2fly_removed))
    final_change = format_change(len(final_added), len(final_removed))

    # history (снапшот только если реально изменилось)
    if prev_final_set and (prev_final_set != final_set):
        stamp = now_stamp()
        snap_prev = HISTORY_DIR / f"snapshot-{stamp}-prev.lst"
        snap_new = HISTORY_DIR / f"snapshot-{stamp}-new.lst"
        diff_file = HISTORY_DIR / f"diff-{stamp}.txt"

        snap_prev.write_text("\n".join(sorted(prev_final_set)) + "\n", encoding="utf-8")
        snap_new.write_text("\n".join(sorted(final_set)) + "\n", encoding="utf-8")

        diff_lines: List[str] = []
        diff_lines.append(f"Added: {len(final_added)}")
        diff_lines.extend([f"+ {x}" for x in final_added[:200]])
        diff_lines.append("")
        diff_lines.append(f"Removed: {len(final_removed)}")
        diff_lines.extend([f"- {x}" for x in final_removed[:200]])
        diff_file.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")

        rotate_history(HISTORY_DIR, MAX_HISTORY)

    # stats.json (как и раньше, агрегат)
    stats_info = append_stats(
        total=len(final_set),
        itdog_count=len(itdog_set),
        v2fly_count=len(v2fly_set),
        warnings=warnings,
    )
    prev_total_from_stats = stats_info["prev"]["total"] if stats_info.get("prev") else None
    delta_total = (len(final_set) - prev_total_from_stats) if prev_total_from_stats is not None else None

    # v2fly ok/fail
    v2fly_ok = 0
    v2fly_fail = 0
    for _cat, d in per_cat_stats.items():
        if d["status"].startswith("FAIL"):
            v2fly_fail += 1
        else:
            v2fly_ok += 1

    # таблица per-category (в порядке, как в файле категорий)
    ordered_per_cat: Dict[str, Dict] = {cat: per_cat_stats.get(cat, {
        "valid_domains": 0,
        "extras_added": 0,
        "invalid_lines": 0,
        "skipped_directives": 0,
        "status": "FAIL",
    }) for cat in cats}
    v2fly_table_rows = make_v2fly_table_rows(ordered_per_cat)

    # хеши
    sha_final = sha256_file(FINAL_OUT)

    # report.md (новый формат)
    REPORT_OUT.write_text(
        format_report_new(
            build_time_utc=ts_utc_report,
            repo=repo,
            output="dist/inside-kvas.lst",
            max_lines=MAX_LINES,
            itdog_total=len(itdog_set),
            itdog_change=itdog_change,
            v2fly_total=len(v2fly_set),
            v2fly_change=v2fly_change,
            v2fly_ok=v2fly_ok,
            v2fly_fail=v2fly_fail,
            final_total=len(final_set),
            final_change=final_change,
            truncated_count=truncated_count,
            itdog_added=itdog_added,
            itdog_removed=itdog_removed,
            v2fly_added=v2fly_added,
            v2fly_removed=v2fly_removed,
            final_added=final_added,
            final_removed=final_removed,
            v2fly_table_rows=v2fly_table_rows,
            failed_cats=failed_categories,
            empty_cats=empty_categories,
            bad_output_lines=bad_output_lines,
            truncated_yesno=truncated_yesno,
            sha256_final=sha_final,
        ),
        encoding="utf-8",
    )

    # state.json (для следующего запуска)
    state = {
        "build_time_utc": f"{ts_utc_report} UTC",
        "sha256_final": sha_final,
        "itdog_domains": sorted(itdog_set),
        "v2fly_extras": sorted(v2fly_set),
        "final_domains": sorted(final_set),
        "v2fly_per_category": ordered_per_cat,
        "v2fly_categories": cats,
        "warnings": warnings,
    }
    write_state(state)

    # tg message / alert
    TG_MESSAGE_OUT.write_text(build_tg_message(ts_msk, len(final_set), delta_total, warnings), encoding="utf-8")
    alert_text = build_tg_alert(ts_msk, warnings)
    if alert_text:
        TG_ALERT_OUT.write_text(alert_text, encoding="utf-8")
    else:
        TG_ALERT_OUT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
