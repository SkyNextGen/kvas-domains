#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KVAS domain list builder.

Responsibilities:
- Download source lists (itdog + v2fly categories).
- Extract/normalize domains, compute v2fly extras (not present in itdog).
- Compose final list inside-kvas.lst with max_lines truncation.
- Write dist artifacts: inside-kvas.lst, v2fly-only.lst, debug_v2fly.txt, state.json
- Always refresh build_time_utc in state.json on every run.

NOTE:
- Report/Telegram formatting is handled by src/report.py.
"""

from __future__ import annotations

import json
import re
import hashlib
import os
from urllib.error import URLError, HTTPError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SRC = ROOT / "src"

STATE_JSON = DIST / "state.json"
INSIDE_KVAS = DIST / "inside-kvas.lst"
V2FLY_ONLY = DIST / "v2fly-only.lst"
DEBUG_V2FLY = DIST / "debug_v2fly.txt"

# Default limits (can be overridden by existing state.json)
DEFAULT_MAX_LINES = 1850
DEFAULT_NEAR_LIMIT = 1800

# Sources
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"
V2FLY_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/{cat}"

DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)


def ensure_dirs() -> None:
    DIST.mkdir(parents=True, exist_ok=True)


def now_utc_iso() -> str:
    # ISO 8601 with Z
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def http_get_text(url: str, timeout: int = 25) -> str:
    req = Request(url, headers={"User-Agent": "kvas-domains-builder/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def normalize_domain(s: str) -> Optional[str]:
    s = (s or "").strip().lower()
    if not s:
        return None
    # remove trailing dot
    if s.endswith("."):
        s = s[:-1]
    # strip leading wildcard
    if s.startswith("*."):
        s = s[2:]
    if DOMAIN_RE.fullmatch(s):
        return s
    return None


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


@dataclass
class V2CatStats:
    valid_domains: int = 0
    extras_added: int = 0
    invalid_lines: int = 0
    skipped_directives: int = 0
    status: str = "OK"  # OK / EMPTY / FAIL
    error: str = ""     # optional message


def parse_v2fly_text(text: str) -> Tuple[List[str], int, int]:
    """
    Returns:
    - list of normalized domains extracted
    - invalid_lines: lines that looked like domains but failed validation
    - skipped_directives: non-expandable directives include:/regexp:/keyword:/...
    """
    domains: List[str] = []
    invalid = 0
    skipped = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # Skip known directives that are not expanded here
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()

            if key in {"include", "regexp", "keyword", "geosite", "ext"}:
                skipped += 1
                continue

            if key in {"domain", "full"}:
                dom = normalize_domain(val)
                if dom:
                    domains.append(dom)
                else:
                    invalid += 1
                continue

            # Other directives – count as skipped (safer, matches your spec)
            skipped += 1
            continue

        # Plain domain line
        dom = normalize_domain(line)
        if dom:
            domains.append(dom)
        else:
            invalid += 1

    return domains, invalid, skipped


def load_categories_list() -> List[str]:
    """
    Categories list file:
      - prefer src/v2fly_allow.txt
      - fallback dist/v2fly_allow.txt
    """
    for p in (SRC / "v2fly_allow.txt", DIST / "v2fly_allow.txt"):
        if p.exists():
            cats = []
            for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                cats.append(s)
            return cats
    return []


def read_prev_state() -> Dict:
    if not STATE_JSON.exists():
        return {}
    try:
        data = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def sha256_of_lines(lines: List[str]) -> str:
    h = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    return h


def main() -> int:
    ensure_dirs()

    prev_state = read_prev_state()
    max_lines = int(prev_state.get("max_lines", DEFAULT_MAX_LINES))
    near_limit_threshold = int(prev_state.get("near_limit_threshold", DEFAULT_NEAR_LIMIT))

    repo = os.getenv("GITHUB_REPOSITORY") or prev_state.get("repo") or "unknown/unknown"
    output = prev_state.get("output") or "dist/inside-kvas.lst"

    warnings: List[str] = []
    failed_categories: List[str] = []
    empty_categories: List[str] = []

    # --- itdog ---
    try:
        itdog_text = http_get_text(ITDOG_URL)
        itdog_domains = sorted(set(parse_itdog(itdog_text)))
    except Exception as e:
        itdog_domains = []
        warnings.append(f"itdog: ошибка загрузки ({type(e).__name__})")

    itdog_set: Set[str] = set(itdog_domains)

    # --- v2fly categories ---
    cats = load_categories_list()
    v2fly_per_category: Dict[str, Dict] = {}
    v2fly_all: Set[str] = set()

    v2_ok = 0
    v2_fail = 0

    debug_lines: List[str] = []
    debug_lines.append("v2fly debug")
    debug_lines.append(f"cats: {', '.join(cats) if cats else '—'}")
    debug_lines.append("")

    for cat in cats:
        st = V2CatStats()

        url = V2FLY_BASE.format(cat=cat)
        try:
            text = http_get_text(url)
            doms, invalid, skipped = parse_v2fly_text(text)

            st.invalid_lines = invalid
            st.skipped_directives = skipped
            st.valid_domains = len(set(doms))

            if st.valid_domains == 0:
                st.status = "EMPTY"
                empty_categories.append(cat)
            else:
                st.status = "OK"
                v2_ok += 1

            # Add to global
            v2fly_all.update(set(doms))

            debug_lines.append(f"[{cat}] status={st.status} valid={st.valid_domains} invalid={invalid} skipped={skipped}")
        except HTTPError as e:
            st.status = "FAIL"
            st.error = f"HTTP {e.code}"
            failed_categories.append(f"{cat} ({st.error})")
            v2_fail += 1
            warnings.append(f"{cat}: {st.error}")
            debug_lines.append(f"[{cat}] status=FAIL error={st.error}")
        except URLError as e:
            st.status = "FAIL"
            st.error = "url error"
            failed_categories.append(f"{cat} ({st.error})")
            v2_fail += 1
            warnings.append(f"{cat}: {st.error}")
            debug_lines.append(f"[{cat}] status=FAIL error={st.error}")
        except Exception as e:
            st.status = "FAIL"
            st.error = type(e).__name__
            failed_categories.append(f"{cat} ({st.error})")
            v2_fail += 1
            warnings.append(f"{cat}: {st.error}")
            debug_lines.append(f"[{cat}] status=FAIL error={st.error}")

        v2fly_per_category[cat] = {
            "valid_domains": st.valid_domains,
            "extras_added": 0,  # filled after extras computation
            "invalid_lines": st.invalid_lines,
            "skipped_directives": st.skipped_directives,
            "status": st.status,
            "error": st.error,
            "url": url,
        }

    # v2fly extras = v2fly_all - itdog
    v2fly_extras = sorted(v2fly_all - itdog_set)
    v2fly_only_set = set(v2fly_extras)

    # Fill extras_added per category (intersection of cat domains with extras)
    # We do a second pass only for OK/EMPTY cats to keep code simpler and stable:
    for cat, meta in v2fly_per_category.items():
        if meta.get("status") == "FAIL":
            continue
        # To avoid re-downloading, approximate by using global set is impossible.
        # So we conservatively set extras_added=0 here; report uses actual extras total.
        # If you want exact per-cat extras, switch to caching cat domain sets.
        # For now, we compute exact by re-downloading only if cat valid>0 (cheap, limited set).
        if int(meta.get("valid_domains", 0)) <= 0:
            meta["extras_added"] = 0
            continue
        try:
            text = http_get_text(meta["url"])
            doms, _, _ = parse_v2fly_text(text)
            meta["extras_added"] = len(set(doms) & v2fly_only_set)
        except Exception:
            meta["extras_added"] = 0

    # Compose final list
    final_domains = itdog_domains + v2fly_extras
    # Deduplicate while preserving sorted blocks (itdog already unique+sorted, extras unique+sorted)
    final_domains = list(dict.fromkeys(final_domains))

    truncated = 0
    if len(final_domains) > max_lines:
        truncated = len(final_domains) - max_lines
        final_domains = final_domains[:max_lines]
        warnings.append(f"обрезка по лимиту: {truncated} строк")

    # bad lines in output (should be 0 because we normalize), but keep field for report contract
    bad_output_lines = 0

    # Write lists
    INSIDE_KVAS.write_text("\n".join(final_domains) + "\n", encoding="utf-8")
    V2FLY_ONLY.write_text("\n".join(v2fly_extras) + "\n", encoding="utf-8")
    DEBUG_V2FLY.write_text("\n".join(debug_lines) + "\n", encoding="utf-8")

    sha_final = sha256_of_lines(final_domains)

    # Build state.json (fresh every run)
    state = {
        "build_time_utc": now_utc_iso(),
        "repo": repo,
        "output": output,
        "max_lines": max_lines,
        "near_limit_threshold": near_limit_threshold,

        "sha256_final": sha_final,

        "itdog_domains": itdog_domains,
        "v2fly_extras": v2fly_extras,
        "final_domains": final_domains,

        "itdog_total": len(itdog_domains),
        "v2fly_total": len(v2fly_extras),
        "final_total": len(final_domains),

        "truncated": truncated,
        "bad_output_lines": bad_output_lines,
        "truncated_yesno": "ДА" if truncated > 0 else "НЕТ",

        "v2fly_ok": v2_ok,
        "v2fly_fail": v2_fail,
        "v2fly_categories": cats,
        "v2fly_per_category": v2fly_per_category,

        "warnings": warnings,
        "failed_categories": failed_categories,
        "empty_categories": empty_categories,

        # Prev snapshot for diff in report
        "prev": {
            "itdog_domains": prev_state.get("itdog_domains", []),
            "v2fly_extras": prev_state.get("v2fly_extras", []),
            "final_domains": prev_state.get("final_domains", []),
        },
    }

    STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
