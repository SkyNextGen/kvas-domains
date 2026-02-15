#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DIST_DIR = ROOT / "dist"
HISTORY_DIR = DIST_DIR / "history"

# ------------------------- config -------------------------

# itdog (база)
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"

# v2fly (категории -> data/<category>)
V2FLY_DATA_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
V2FLY_CATEGORIES_FILE = SRC_DIR / "v2fly_allow.txt"

# outputs
FINAL_OUT = DIST_DIR / "inside-kvas.lst"
DEBUG_V2FLY = DIST_DIR / "debug_v2fly.txt"
STATE_JSON = DIST_DIR / "state.json"

# limits
MAX_LINES = 3000
NEAR_LIMIT_THRESHOLD = 2900

# history
MAX_HISTORY = 12

DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)

# В v2fly берём только домены (plain / domain: / full:)
V2FLY_PREFIXES = ("full:", "domain:")

# Директивы v2fly, которые не разворачиваем в домены
V2FLY_DIRECTIVE_PREFIXES = (
    "include:",
    "regexp:",
    "keyword:",
    "ext:",
    "full-regexp:",
    "domain-regexp:",
    "suffix:",
)


@dataclass
class FetchResult:
    ok: bool
    text: str
    error: Optional[str] = None
    status: Optional[int] = None


# ------------------------- helpers -------------------------

def ensure_dirs() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def now_utc_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def build_time_utc_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


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


def parse_v2fly_file_with_stats(text: str) -> Tuple[List[str], int, int]:
    """Возвращает (домены, invalid_lines, skipped_directives)."""
    out: List[str] = []
    invalid_lines = 0
    skipped_directives = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if any(line.startswith(p) for p in V2FLY_PREFIXES):
            _, val = line.split(":", 1)
            dom = normalize_domain(val)
            if dom:
                out.append(dom)
            else:
                invalid_lines += 1
            continue

        if any(line.startswith(p) for p in V2FLY_DIRECTIVE_PREFIXES):
            skipped_directives += 1
            continue

        # Некоторые директивы выглядят как "something:..."
        if ":" in line and not is_domain(line):
            skipped_directives += 1
            continue

        dom = normalize_domain(line)
        if dom:
            out.append(dom)
        else:
            invalid_lines += 1

    return out, invalid_lines, skipped_directives


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rotate_history(history_dir: Path, max_items: int) -> None:
    snaps = sorted(history_dir.glob("snapshot-*.lst"))
    for p in snaps[:-max_items]:
        p.unlink(missing_ok=True)

    diffs = sorted(history_dir.glob("diff-*.txt"))
    for p in diffs[:-max_items]:
        p.unlink(missing_ok=True)


def diff_lists(prev: Iterable[str], curr: Iterable[str]) -> Tuple[List[str], List[str]]:
    prev_set = set(prev)
    curr_set = set(curr)
    added = sorted(curr_set - prev_set)
    removed = sorted(prev_set - curr_set)
    return added, removed


def now_stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%d-%H%M%S")


# ------------------------- main -------------------------

def main() -> int:
    ensure_dirs()

    dt_utc = now_utc_dt()
    ts_utc = dt_utc.isoformat()
    bt_utc = build_time_utc_str(dt_utc)

    # load previous state (для диффов в report.py)
    old_state = load_json(STATE_JSON, {})
    if not isinstance(old_state, dict):
        old_state = {}

    prev_block = {
        "itdog_domains": old_state.get("itdog_domains", []) if isinstance(old_state.get("itdog_domains"), list) else [],
        "v2fly_extras": old_state.get("v2fly_extras", []) if isinstance(old_state.get("v2fly_extras"), list) else [],
        "final_domains": old_state.get("final_domains", []) if isinstance(old_state.get("final_domains"), list) else [],
    }

    warnings: List[str] = []

    # ---------------- itdog ----------------
    itdog_fetch = http_get_text(ITDOG_URL)
    if not itdog_fetch.ok:
        warnings.append(f"🔴 itdog: не удалось скачать ({itdog_fetch.error})")
        itdog_list: List[str] = []
    else:
        itdog_list = parse_itdog(itdog_fetch.text)

    # уникализация, но с сохранением порядка
    itdog_unique = list(dict.fromkeys(itdog_list))
    itdog_set = set(itdog_unique)

    # ---------------- v2fly ----------------
    cats = read_v2fly_categories(V2FLY_CATEGORIES_FILE)
    v2fly_all: List[str] = []
    v2fly_per_category: Dict[str, Dict] = {}
    failed_categories: List[str] = []
    empty_categories: List[str] = []
    ok_count = 0
    fail_count = 0

    debug_lines: List[str] = []
    debug_lines.append(f"UTC: {ts_utc}")
    debug_lines.append(f"build_time_utc: {bt_utc}")
    debug_lines.append(f"Categories file: {V2FLY_CATEGORIES_FILE.as_posix()}")
    debug_lines.append(f"Categories count: {len(cats)}")
    debug_lines.append("")

    if not V2FLY_CATEGORIES_FILE.exists():
        warnings.append("⚠️ v2fly: нет файла src/v2fly_allow.txt (v2fly пропущен)")
    elif len(cats) == 0:
        warnings.append("⚠️ v2fly: файл категорий пустой (v2fly пропущен)")
    else:
        for cat in cats:
            url = f"{V2FLY_DATA_BASE}/{cat}"
            res = http_get_text(url)

            if not res.ok:
                fail_count += 1
                failed_categories.append(cat)
                v2fly_per_category[cat] = {
                    "valid_domains": 0,
                    "extras_added": 0,
                    "invalid_lines": 0,
                    "skipped_directives": 0,
                    "status": "FAIL",
                }
                debug_lines.append(f"[FAIL] {cat} -> {res.error}")
                continue

            parsed, invalid_lines, skipped_directives = parse_v2fly_file_with_stats(res.text)
            valid_domains = len(parsed)

            status = "OK"
            if valid_domains == 0:
                status = "EMPTY"
                empty_categories.append(cat)

            if status == "OK":
                ok_count += 1

            v2fly_all.extend(parsed)
            v2fly_per_category[cat] = {
                "valid_domains": valid_domains,
                "extras_added": 0,  # посчитаем ниже, после вычитания itdog
                "invalid_lines": invalid_lines,
                "skipped_directives": skipped_directives,
                "status": status,
            }
            debug_lines.append(
                f"[{status}] {cat} -> lines={len(res.text.splitlines())}, domains={valid_domains}, invalid={invalid_lines}, skipped={skipped_directives}"
            )

        if fail_count:
            warnings.append(f"🔴 v2fly: не скачались/не распарсились категории: {fail_count}/{len(cats)}")
        if empty_categories:
            warnings.append(f"🟡 v2fly: пустые категории (0 доменов): {', '.join(empty_categories)}")
        if len(v2fly_all) == 0 and cats:
            warnings.append("🟡 v2fly: категории указаны, но доменов не получено")

    # v2fly extras: в хвост, без дублей относительно itdog
    v2fly_unique_sorted = sorted({d for d in v2fly_all if d not in itdog_set})

    # extras_added per category (сколько реально попало в extras, а не пересечение с itdog)
    v2fly_extras_set = set(v2fly_unique_sorted)
    for cat, st in v2fly_per_category.items():
        if not isinstance(st, dict):
            continue
        # мы не знаем какие домены из каких строк попали (после сортировки),
        # поэтому считаем по пересечению: домены категории ∩ extras
        # Для этого нужно восстановить список доменов категории — мы его не храним.
        # Поэтому считаем приблизительно: extras_added = min(valid_domains, |extras|) для OK/EMPTY
        # Чтобы было строго, лучше хранить doms_by_cat, но это увеличит state.json.
        # Делает минимальный, но стабильный показатель:
        st["extras_added"] = 0

    # Строгий подсчёт extras_added без роста state.json: пересчитаем второй раз,
    # но только множества категорий (без хранения списка): тяжело без doms_by_cat.
    # Поэтому храним doms_by_cat временно и считаем.
    # (Это добавит немного памяти, но не попадёт в state.json.)
    # ---
    if cats and V2FLY_CATEGORIES_FILE.exists():
        doms_by_cat: Dict[str, set] = {}
        for cat in cats:
            url = f"{V2FLY_DATA_BASE}/{cat}"
            res = http_get_text(url)
            if not res.ok:
                continue
            parsed, _, _ = parse_v2fly_file_with_stats(res.text)
            doms_by_cat[cat] = set(parsed)
        for cat, doms in doms_by_cat.items():
            st = v2fly_per_category.get(cat)
            if isinstance(st, dict):
                st["extras_added"] = len(doms & v2fly_extras_set)

    final_raw = itdog_unique + v2fly_unique_sorted
    truncated = max(0, len(final_raw) - MAX_LINES)
    final_list = final_raw[:MAX_LINES]

    # качество вывода: все ли строки валидные домены
    bad_output_lines = sum(1 for x in final_list if not is_domain(x))

    FINAL_OUT.write_text("\n".join(final_list) + "\n", encoding="utf-8")
    sha_final = sha256_file(FINAL_OUT)

    # debug
    debug_lines.append("")
    debug_lines.append(f"itdog: {len(itdog_unique)}")
    debug_lines.append(f"v2fly extras: {len(v2fly_unique_sorted)}")
    debug_lines.append(f"final_raw: {len(final_raw)}")
    debug_lines.append(f"final_saved: {len(final_list)}")
    debug_lines.append(f"truncated: {truncated}")
    debug_lines.append(f"bad_output_lines: {bad_output_lines}")
    debug_lines.append(f"sha256_final: {sha_final}")

    DEBUG_V2FLY.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

    # history (снапшот только если реально изменилось)
    prev_final_list = prev_block.get("final_domains", []) if isinstance(prev_block.get("final_domains"), list) else []
    if prev_final_list and (set(prev_final_list) != set(final_list)):
        stamp = now_stamp(dt_utc)
        snap_prev = HISTORY_DIR / f"snapshot-{stamp}-prev.lst"
        snap_new = HISTORY_DIR / f"snapshot-{stamp}-new.lst"
        diff_file = HISTORY_DIR / f"diff-{stamp}.txt"

        snap_prev.write_text("\n".join(prev_final_list) + "\n", encoding="utf-8")
        snap_new.write_text("\n".join(final_list) + "\n", encoding="utf-8")

        added, removed = diff_lists(prev_final_list, final_list)
        diff_lines: List[str] = []
        diff_lines.append(f"UTC: {ts_utc}")
        diff_lines.append(f"added: {len(added)}")
        diff_lines.append(f"removed: {len(removed)}")
        diff_lines.append("")
        diff_lines.append("ADDED (top 200):")
        diff_lines.extend(added[:200] if added else ["—"])
        diff_lines.append("")
        diff_lines.append("REMOVED (top 200):")
        diff_lines.extend(removed[:200] if removed else ["—"])
        diff_file.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")

        rotate_history(HISTORY_DIR, MAX_HISTORY)

    # state.json (источник правды для report.py)
    state = {
        "build_time_utc": bt_utc,
        "repo": "SkyNextGen/kvas-domains",
        "output": "dist/inside-kvas.lst",
        "max_lines": MAX_LINES,
        "near_limit_threshold": NEAR_LIMIT_THRESHOLD,
        "sha256_final": sha_final,
        "itdog_domains": itdog_unique,
        "v2fly_extras": v2fly_unique_sorted,
        "final_domains": final_list,
        "itdog_total": len(set(itdog_unique)),
        "v2fly_total": len(set(v2fly_unique_sorted)),
        "final_total": len(set(final_list)),
        "truncated": truncated,
        "truncated_yesno": "YES" if truncated > 0 else "NO",
        "bad_output_lines": bad_output_lines,
        "v2fly_ok": ok_count,
        "v2fly_fail": fail_count,
        "v2fly_categories": cats,
        "v2fly_per_category": v2fly_per_category,
        "warnings": warnings,
        "failed_categories": failed_categories,
        "empty_categories": empty_categories,
        "prev": prev_block,
    }
    dump_json(STATE_JSON, state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
