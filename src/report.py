#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from report_common import (
    DIST,
    STATE_JSON,
    load_json,
    append_stats,
    REPORT_MD,
    TG_MESSAGE,
    TG_ALERT,
)
from report_md import format_report_md
from report_tg import format_tg


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = load_json(STATE_JSON, {})
    if not isinstance(state, dict):
        state = {}

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
