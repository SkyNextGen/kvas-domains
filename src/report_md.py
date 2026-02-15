#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KVAS Markdown report generator (dist/report.md)."""

from __future__ import annotations

from typing import Dict, List, Optional

from report_common import *  # noqa: F401,F403


def format_report_md(state: Dict, stats: List[Dict], prev_rec: Optional[Dict]) -> str:
    repo = str(state.get("repo", "unknown/unknown"))
    build_time = fmt_build_time_msk(str(state.get("build_time_utc", "")))
    out = str(state.get("output", "dist/inside-kvas.lst"))

    final_total = int(state.get("final_total", 0) or 0)
    max_lines = int(state.get("max_lines", 0) or 0)
    threshold = int(state.get("near_limit_threshold", 0) or 0)

    itdog_total = int(state.get("itdog_total", 0) or 0)
    v2fly_total = int(state.get("v2fly_total", 0) or 0)
    trunc = int(state.get("truncated", 0) or 0)
    bad = int(state.get("bad_output_lines", 0) or 0)

    v2_ok = int(state.get("v2fly_ok", 0) or 0)
    v2_fail = int(state.get("v2fly_fail", 0) or 0)

    warns = state.get("warnings", []) or []
    failed = state.get("failed_categories", []) or []
    empty = state.get("empty_categories", []) or []

    sha = short_hash(str(state.get("sha256_final", "")))
    sev = classify_severity(state)

    trend = trend_eval(prev_rec, state)

    report_url = repo_report_url(repo)
    report_link = report_url if report_url else "—"

    # delta formatting
    def fdelta(x):
        if x is None:
            return "—"
        if x > 0:
            return f"+{x}"
        return str(x)

    lines = []
    lines.append(f"# KVAS report — {build_time}")
    lines.append("")
    lines.append(f"**Repo:** `{repo}`  ")
    lines.append(f"**Output:** `{out}`  ")
    lines.append(f"**Report link:** {report_link}")
    lines.append("")
    lines.append("## Статус")
    if sev == "ОК":
        lines.append("✅ **ОК**")
    elif sev == "ПРЕДУПРЕЖДЕНИЕ":
        lines.append("⚠️ **ПРЕДУПРЕЖДЕНИЕ**")
    else:
        lines.append("🧨 **ОШИБКА**")
    lines.append("")
    lines.append("## Итоги")
    lines.append(f"- **Итого доменов:** `{final_total}` (Δ {fdelta(trend.get('final_delta'))})")
    lines.append(f"- itdog: `{itdog_total}` (Δ {fdelta(trend.get('itdog_delta'))})")
    lines.append(f"- v2fly extras: `{v2fly_total}` (Δ {fdelta(trend.get('v2fly_delta'))})")
    lines.append(f"- лимит: {limit_badge(final_total, max_lines, threshold)}")
    lines.append(f"- sha256: `{sha}`")
    lines.append("")
    lines.append("## Проверки")
    lines.append(f"- v2fly categories: ✅ `{v2_ok}` / ❌ `{v2_fail}`")
    lines.append(f"- bad lines: `{bad}`")
    lines.append(f"- truncated: `{trunc}`")
    lines.append("")

    if warns:
        lines.append("## Warnings")
        for w in warns:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    if failed:
        lines.append("## Failed categories")
        for c in failed:
            lines.append(f"- ❌ `{c}`")
        lines.append("")

    if empty:
        lines.append("## Empty categories")
        for c in empty:
            lines.append(f"- 🟡 `{c}`")
        lines.append("")

    # details blocks for lists (optional)
    itdog_list = state.get("itdog_domains", []) or []
    v2fly_list = state.get("v2fly_extras", []) or []
    final_list = state.get("final_domains", []) or []

    lines.append("## Списки")
    lines.append("")
    lines.append("<details><summary>itdog domains</summary>\n")
    lines.append("\n".join([f"- {d}" for d in itdog_list[:2000]] or ["- —"]))
    if len(itdog_list) > 2000:
        lines.append(f"\n- …ещё {len(itdog_list) - 2000}")
    lines.append("\n</details>\n")

    lines.append("<details><summary>v2fly extras</summary>\n")
    lines.append("\n".join([f"- {d}" for d in v2fly_list[:2000]] or ["- —"]))
    if len(v2fly_list) > 2000:
        lines.append(f"\n- …ещё {len(v2fly_list) - 2000}")
    lines.append("\n</details>\n")

    lines.append("<details><summary>final domains</summary>\n")
    lines.append("\n".join([f"- {d}" for d in final_list[:2000]] or ["- —"]))
    if len(final_list) > 2000:
        lines.append(f"\n- …ещё {len(final_list) - 2000}")
    lines.append("\n</details>\n")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)

    state = ensure_state()

    # Standalone mode: no append (to avoid двойной append in workflow).
    stats = load_json(STATS_JSON, [])
    if not isinstance(stats, list):
        stats = []
    prev_rec = stats[-2] if len(stats) >= 2 and isinstance(stats[-2], dict) else None

    REPORT_MD.write_text(format_report_md(state, stats, prev_rec), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
