#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone

from report_common import (
    DIST,
    STATE_JSON,
    STATS_JSON,
    REPORT_MD,
    TG_MESSAGE,
    TG_ALERT,
    load_json,
    dump_json,
    append_stats,
)

from report_md import format_report_md
from report_tg import format_tg


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict) or not state:
        # minimal fallback, don't crash workflow (STRICT as original)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        state = {
            "build_time_utc": now,
            "repo": "unknown/unknown",
            "output": "dist/inside-kvas.lst",
            "max_lines": 3000,
            "near_limit_threshold": 2900,
            "sha256_final": "",
            "itdog_domains": [],
            "v2fly_extras": [],
            "final_domains": [],
            "itdog_total": 0,
            "v2fly_total": 0,
            "final_total": 0,
            "truncated": 0,
            "bad_output_lines": 0,
            "v2fly_ok": 0,
            "v2fly_fail": 0,
            "v2fly_categories": [],
            "v2fly_per_category": {},
            "warnings": ["state.json отсутствует/повреждён"],
            "failed_categories": [],
            "empty_categories": [],
            "prev": {"itdog_domains": [], "v2fly_extras": [], "final_domains": []},
        }
        dump_json(STATE_JSON, state)

    stats, prev_rec = append_stats(state)

    REPORT_MD.write_text(format_report_md(state, stats, prev_rec), encoding="utf-8")

    tg_msg, tg_alert = format_tg(state, stats, prev_rec)
    TG_MESSAGE.write_text(tg_msg, encoding="utf-8")
    if tg_alert.strip():
        TG_ALERT.write_text(tg_alert, encoding="utf-8")
    else:
        TG_ALERT.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
