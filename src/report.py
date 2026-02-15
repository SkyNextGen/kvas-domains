#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

# -------------------- CONFIG --------------------

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
STATE_PATH = DIST / "state.json"
REPORT_PATH = DIST / "report.md"

MSK = timezone(timedelta(hours=3))

MONTHS_RU = [
    "янв", "фев", "мар", "апр", "мая", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек"
]

# -------------------- HELPERS --------------------

def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = load_json(STATE_PATH)
    if not isinstance(state, dict):
        state = {}

    # Build time from state.json
    build_time_utc = state.get("build_time_utc")
    if build_time_utc:
        try:
            dt_utc = datetime.fromisoformat(build_time_utc.replace("Z", "+00:00"))
        except Exception:
            dt_utc = datetime.now(timezone.utc)
    else:
        dt_utc = datetime.now(timezone.utc)

    dt_run_msk = dt_utc.astimezone(MSK)

    build_time_msk = f"{dt_run_msk.day:02d} {MONTHS_RU[dt_run_msk.month - 1]} {dt_run_msk.year}, {dt_run_msk:%H:%M} МСК"

    final_domains = state.get("final_domains", [])
    max_lines = state.get("max_lines", 3000)

    sha = hashlib.sha256("\n".join(final_domains).encode("utf-8")).hexdigest()[:8]

    report = f"""# 📊 Отчёт сборки доменов KVAS

Сборка: {build_time_msk}
Всего строк: {len(final_domains)} / {max_lines}

🔐 sha256: {sha}
"""

    REPORT_PATH.write_text(report, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
