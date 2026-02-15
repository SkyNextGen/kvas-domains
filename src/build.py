#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DIST_DIR = ROOT / "dist"
HISTORY_DIR = DIST_DIR / "history"

ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"
V2FLY_DATA_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
V2FLY_CATEGORIES_FILE = SRC_DIR / "v2fly_allow.txt"

FINAL_OUT = DIST_DIR / "inside-kvas.lst"
STATE_JSON = DIST_DIR / "state.json"
DEBUG_V2FLY = DIST_DIR / "debug_v2fly.txt"

MAX_LINES = 3000
NEAR_LIMIT_THRESHOLD = 2900

DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)

V2FLY_EXTRACT_PREFIXES = ("full:", "domain:")
V2FLY_DIRECTIVE_PREFIXES = (
    "include:", "regexp:", "keyword:", "suffix:", "prefix:", "geosite:", "ext:", "tag:",
    "and:", "or:", "not:", "port:", "ipcidr:", "ip:", "payload:", "cidr:"
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
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def http_get_text(url: str, timeout: int = 30) -> FetchResult:
    req = Request(url, headers={"User-Agent": "kvas-domains-builder/2.1"})
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

        if any(line.startswith(p) for p in V2FLY_EXTRACT_PREFIXES):
            _, val = line.split(":", 1)
            dom = normalize_domain(val)
            if dom:
                domains.append(dom)
            else:
                invalid_lines += 1
            continue

        if ":" in line and any(line.startswith(p) for p in V2FLY_DIRECTIVE_PREFIXES):
            skipped_directives += 1
            continue

        dom = normalize_domain(line)
        if dom:
            domains.append(dom)
        else:
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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def read_prev_state() -> Dict:
    if not STATE_JSON.exists():
        return {}
    try:
        data = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main() -> int:
    ensure_dirs()

    ts_utc_iso = now_utc_iso()
    ts_utc_report = now_utc_report_str()
    repo = os.getenv("GITHUB_REPOSITORY", "unknown/unknown")

    prev_state = read_prev_state()
    prev_itdog = prev_state.get("itdog_domains", []) or []
    prev_v2fly = prev_state.get("v2fly_extras", []) or []
    prev_final = prev_state.get("final_domains", []) or []

    warnings: List[str] = []
    failed_categories: List[str] = []
    empty_categories: List[str] = []

    # ---- itdog
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

    # ---- v2fly
    cats = read_v2fly_categories(V2FLY_CATEGORIES_FILE)
    v2fly_domains_all: List[str] = []
    per_cat_stats: Dict[str, Dict] = {}

    debug_lines: List[str] = [
        f"UTC: {ts_utc_iso}",
        f"Categories file: {V2FLY_CATEGORIES_FILE.as_posix()}",
        f"Categories count: {len(cats)}",
        "",
    ]

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

            debug_lines.append(f"[OK]   {cat} -> lines={len(res.text.splitlines())}, domains={len(valid)}")

        if failed_categories:
            warnings.append(f"v2fly: не скачались категории: {len(failed_categories)}/{len(cats)}")

        if len(v2fly_domains_all) == 0 and len(cats) > 0 and not failed_categories:
            warnings.append("v2fly: категории указаны, но доменов не получено")

    DEBUG_V2FLY.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

    # ---- v2fly extras-only
    v2fly_extras_sorted = sorted({d for d in v2fly_domains_all if d not in itdog_set})
    v2fly_set = set(v2fly_extras_sorted)

    # ---- final
    final_list_full = itdog_unique + v2fly_extras_sorted

    bad_output_lines = sum(1 for x in final_list_full if not is_domain(x))

    truncated_count = 0
    if len(final_list_full) > MAX_LINES:
        truncated_count = len(final_list_full) - MAX_LINES
        final_list = final_list_full[:MAX_LINES]
    else:
        final_list = final_list_full

    final_set = set(final_list)
    truncated_yesno = "YES" if truncated_count > 0 else "NO"

    FINAL_OUT.write_text("\n".join(final_list) + "\n", encoding="utf-8")
    sha_final = sha256_file(FINAL_OUT)

    # v2fly ok/fail
    v2fly_ok = 0
    v2fly_fail = 0
    for _, d in per_cat_stats.items():
        if str(d.get("status", "")).startswith("FAIL"):
            v2fly_fail += 1
        else:
            v2fly_ok += 1

    # ordered per-cat in category file order
    ordered_per_cat: Dict[str, Dict] = {cat: per_cat_stats.get(cat, {
        "valid_domains": 0,
        "extras_added": 0,
        "invalid_lines": 0,
        "skipped_directives": 0,
        "status": "FAIL",
    }) for cat in cats}

    # ---- write state (curr + embedded prev)
    state = {
        "build_time_utc": f"{ts_utc_report} UTC",
        "repo": repo,
        "output": "dist/inside-kvas.lst",
        "max_lines": MAX_LINES,
        "near_limit_threshold": NEAR_LIMIT_THRESHOLD,

        "sha256_final": sha_final,

        "itdog_domains": sorted(itdog_set),
        "v2fly_extras": sorted(v2fly_set),
        "final_domains": sorted(final_set),

        "itdog_total": len(itdog_set),
        "v2fly_total": len(v2fly_set),
        "final_total": len(final_set),

        "truncated": truncated_count,
        "bad_output_lines": bad_output_lines,
        "truncated_yesno": truncated_yesno,

        "v2fly_ok": v2fly_ok,
        "v2fly_fail": v2fly_fail,
        "v2fly_categories": cats,
        "v2fly_per_category": ordered_per_cat,

        "warnings": warnings,
        "failed_categories": failed_categories,
        "empty_categories": empty_categories,

        "prev": {
            "itdog_domains": prev_itdog,
            "v2fly_extras": prev_v2fly,
            "final_domains": prev_final,
            "sha256_final": prev_state.get("sha256_final"),
            "build_time_utc": prev_state.get("build_time_utc"),
        },
    }

    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
