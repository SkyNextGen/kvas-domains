import os
import re
import json
import hashlib
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

# =========================
# Источники
# =========================
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"
V2FLY_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"

# Перечисление категорий v2fly (по одной на строку)
V2FLY_ALLOW_FILE = "src/v2fly_allow.txt"

# =========================
# Артефакты
# =========================
DIST_DIR = "dist"
OUT_LIST = f"{DIST_DIR}/inside-kvas.lst"     # итоговый файл для kvas
OUT_REPORT = f"{DIST_DIR}/report.md"         # читаемый отчёт
OUT_STATE = f"{DIST_DIR}/state.json"         # состояние для дельт между сборками
OUT_TG = f"{DIST_DIR}/tg_message.txt"        # готовый текст для Telegram

# =========================
# Ограничения / параметры
# =========================
MAX_LINES = 3000
NEAR_LIMIT_THRESHOLD = 2900
TOP_N = 20

# =========================
# Валидация доменов
# =========================
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

# v2fly директивы, которые не тащим в kvas (include не разворачиваем)
SKIP_PREFIXES = (
    "include:",
    "keyword:",
    "regexp:",
    "geosite:",
    "ext:",
    "tcp:",
    "udp:",
    "ip:",
    "cidr:",
)


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fetch_text(url: str) -> str:
    with urlopen(url, timeout=45) as r:
        return r.read().decode("utf-8", errors="replace")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_domain(s: str) -> str | None:
    s = s.strip().lower().lstrip(".")
    if not s:
        return None
    if " " in s or "/" in s or "\\" in s:
        return None
    if "_" in s:
        return None
    return s if DOMAIN_RE.match(s) else None


# =========================
# itdog парсер
# =========================
def parse_itdog(text: str) -> tuple[list[str], int]:
    out = []
    invalid = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = norm_domain(line)
        if d:
            out.append(d)
        else:
            invalid += 1
    return out, invalid


# =========================
# v2fly парсер
# =========================
def read_v2fly_allow() -> list[str]:
    if not os.path.exists(V2FLY_ALLOW_FILE):
        return []
    with open(V2FLY_ALLOW_FILE, "r", encoding="utf-8") as f:
        return [x.strip() for x in f.read().splitlines() if x.strip() and not x.strip().startswith("#")]


def parse_v2fly(text: str) -> tuple[list[str], dict]:
    """
    Поддерживаем:
      - full:example.com
      - domain:example.com
      - голые домены (example.com)
    Остальное (include/regexp/keyword/прочие typed rules) пропускаем.
    """
    out = []
    invalid = 0
    skipped = 0

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        low = line.lower()

        if low.startswith(SKIP_PREFIXES):
            skipped += 1
            continue

        if low.startswith("full:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
            else:
                invalid += 1
            continue

        if low.startswith("domain:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
            else:
                invalid += 1
            continue

        if ":" in line:
            skipped += 1
            continue

        d = norm_domain(line)
        if d:
            out.append(d)
        else:
            invalid += 1

    stats = {
        "valid_domains": len(out),
        "invalid_lines": invalid,
        "skipped_directives": skipped,
    }
    return out, stats


# =========================
# Actions run URL (для предупреждений)
# =========================
def run_url_from_env() -> str | None:
    server = os.getenv("GITHUB_SERVER_URL")
    repo = os.getenv("GITHUB_REPOSITORY")
    run_id = os.getenv("GITHUB_RUN_ID")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


# =========================
# state.json (дельты)
# =========================
def load_prev_state() -> dict:
    if not os.path.exists(OUT_STATE):
        return {}
    try:
        with open(OUT_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def top_n_sorted(items: set[str], n: int = TOP_N) -> list[str]:
    return sorted(items)[:n]


def fmt_delta(added: int, removed: int) -> str:
    return f"+{added} / −{removed}"


def main():
    os.makedirs(DIST_DIR, exist_ok=True)
    build_time = utc_now_str()

    prev = load_prev_state()
    prev_itdog = set(prev.get("itdog_domains", []))
    prev_v2extras = set(prev.get("v2fly_extras", []))
    prev_final = set(prev.get("final_domains", []))

    # ---------- itdog ----------
    itdog_ok = True
    itdog_err = None
    try:
        itdog_text = fetch_text(ITDOG_URL)
        itdog_domains, itdog_invalid = parse_itdog(itdog_text)
    except Exception as e:
        itdog_ok = False
        itdog_err = str(e)
        itdog_domains, itdog_invalid = [], 0

    itdog_set = set(itdog_domains)

    # ---------- v2fly ----------
    v2_names = read_v2fly_allow()
    v2_ok = 0
    v2_fail = 0
    failed_categories: list[dict] = []
    category_stats: dict[str, dict] = {}
    v2_all_set: set[str] = set()

    for name in v2_names:
        url = f"{V2FLY_BASE}/{name}"
        try:
            text = fetch_text(url)
            domains, stats = parse_v2fly(text)
            v2_ok += 1

            before = len(v2_all_set)
            for d in domains:
                v2_all_set.add(d)
            unique_added_here = len(v2_all_set) - before

            category_stats[name] = {
                "valid_domains": stats["valid_domains"],
                "invalid_lines": stats["invalid_lines"],
                "skipped_directives": stats["skipped_directives"],
                "extras_added": 0,  # заполним после расчёта extras
                "status": "OK" if stats["valid_domains"] > 0 else "EMPTY ⚠",
                "unique_in_v2fly": unique_added_here,
            }

        except HTTPError as e:
            v2_fail += 1
            failed_categories.append({"category": name, "error": f"HTTP {e.code}"})
            category_stats[name] = {
                "valid_domains": 0, "invalid_lines": 0, "skipped_directives": 0,
                "extras_added": 0, "status": f"FAIL ❌ (HTTP {e.code})",
                "unique_in_v2fly": 0,
            }
        except URLError as e:
            v2_fail += 1
            failed_categories.append({"category": name, "error": f"URL error: {e.reason}"})
            category_stats[name] = {
                "valid_domains": 0, "invalid_lines": 0, "skipped_directives": 0,
                "extras_added": 0, "status": "FAIL ❌ (network)",
                "unique_in_v2fly": 0,
            }
        except Exception as e:
            v2_fail += 1
            failed_categories.append({"category": name, "error": str(e)})
            category_stats[name] = {
                "valid_domains": 0, "invalid_lines": 0, "skipped_directives": 0,
                "extras_added": 0, "status": "FAIL ❌",
                "unique_in_v2fly": 0,
            }

    # ---------- v2fly extras (только то, чего нет в itdog) ----------
    v2_extras_set = {d for d in v2_all_set if d not in itdog_set}

    # extras_added по категориям (второй проход по категориям)
    for name in v2_names:
        st = category_stats.get(name, {})
        if "FAIL" in st.get("status", ""):
            continue
        try:
            text = fetch_text(f"{V2FLY_BASE}/{name}")
            domains, _ = parse_v2fly(text)
            extras_here = {d for d in domains if d in v2_extras_set}
            category_stats[name]["extras_added"] = len(extras_here)
        except Exception:
            pass

    # ---------- итоговый список (вариант A) ----------
    final_list = itdog_domains + sorted(v2_extras_set)

    truncated = 0
    if len(final_list) > MAX_LINES:
        truncated = len(final_list) - MAX_LINES
        final_list = final_list[:MAX_LINES]

    bad_lines = [x for x in final_list if (":" in x) or (" " in x) or ("/" in x) or ("\t" in x)]
    bad_lines_count = len(bad_lines)

    with open(OUT_LIST, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(final_list) + "\n")

    final_sha = sha256_file(OUT_LIST)
    final_set = set(final_list)

    # ---------- дельты ----------
    itdog_added = itdog_set - prev_itdog
    itdog_removed = prev_itdog - itdog_set

    v2extras_added = v2_extras_set - prev_v2extras
    v2extras_removed = prev_v2extras - v2_extras_set

    final_added = final_set - prev_final
    final_removed = prev_final - final_set

    # ---------- предупреждения ----------
    usage_pct = (len(final_list) / MAX_LINES) * 100 if MAX_LINES else 0.0
    near_limit = len(final_list) >= NEAR_LIMIT_THRESHOLD

    empty_categories = sorted([c for c, st in category_stats.items() if st.get("status") == "EMPTY ⚠"])

    warnings: list[str] = []
    if not itdog_ok:
        warnings.append(f"🔴 itdog: ошибка загрузки ({itdog_err})")
    if near_limit:
        warnings.append(f"🟠 Почти достигнут лимит (≥ {NEAR_LIMIT_THRESHOLD} строк)")
    if truncated > 0:
        warnings.append(f"🔴 Итоговый файл обрезан по лимиту: −{truncated} строк")
    if failed_categories:
        failed_str = ", ".join([f'{x["category"]} ({x["error"]})' for x in failed_categories][:10])
        warnings.append(f"🔴 Ошибка загрузки категорий: {failed_str}")
    if empty_categories:
        warnings.append(f"🟡 Пустые категории: {', '.join(empty_categories)}")
    if bad_lines_count > 0:
        warnings.append(f"🔴 Мусорные строки в output: {bad_lines_count}")

    run_url = run_url_from_env()

    # ---------- report.md ----------
    def list_block(title: str, items: list[str]) -> str:
        if not items:
            return f"### {title}\n- (нет)\n"
        s = f"### {title}\n"
        for i, d in enumerate(items, 1):
            s += f"{i}. {d}\n"
        return s

    itdog_added_top = top_n_sorted(itdog_added, TOP_N)
    itdog_removed_top = top_n_sorted(itdog_removed, TOP_N)
    v2_added_top = top_n_sorted(v2extras_added, TOP_N)
    v2_removed_top = top_n_sorted(v2extras_removed, TOP_N)
    final_added_top = top_n_sorted(final_added, TOP_N)
    final_removed_top = top_n_sorted(final_removed, TOP_N)

    cat_rows = []
    for cat in sorted(category_stats.keys()):
        st = category_stats[cat]
        cat_rows.append(
            f"| {cat} | {st.get('valid_domains', 0)} | {st.get('extras_added', 0)} | "
            f"{st.get('invalid_lines', 0)} | {st.get('skipped_directives', 0)} | {st.get('status', '')} |"
        )

    report = []
    report.append("# KVAS domains build report\n\n")
    report.append(f"Build time (UTC): {build_time}\n")
    report.append(f"Output: `{OUT_LIST}`\n")
    report.append(f"Max lines: {MAX_LINES}\n\n")

    report.append("## Summary\n")
    report.append("- itdog:\n")
    report.append(f"  - total: {len(itdog_set)}\n")
    report.append(f"  - change vs prev: {fmt_delta(len(itdog_added), len(itdog_removed))}\n")
    report.append("- v2fly (extras only: not in itdog):\n")
    report.append(f"  - total: {len(v2_extras_set)}\n")
    report.append(f"  - change vs prev: {fmt_delta(len(v2extras_added), len(v2extras_removed))}\n")
    report.append(f"  - lists: ok={v2_ok}, fail={v2_fail}\n")
    report.append("- final output:\n")
    report.append(f"  - total: {len(final_list)}\n")
    report.append(f"  - change vs prev: {fmt_delta(len(final_added), len(final_removed))}\n")
    report.append(f"  - truncated: {truncated}\n\n")

    report.append("## Limit status\n")
    report.append(f"- usage: {len(final_list)} / {MAX_LINES} ({usage_pct:.1f}%)\n")
    report.append(f"- near limit: {'YES' if near_limit else 'NO'} (threshold: {NEAR_LIMIT_THRESHOLD})\n\n")

    report.append("## itdog changes vs prev (top 20)\n")
    report.append(list_block("Added", itdog_added_top))
    report.append(list_block("Removed", itdog_removed_top))
    report.append("\n")

    report.append("## v2fly extras changes vs prev (top 20)\n")
    report.append(list_block("Added", v2_added_top))
    report.append(list_block("Removed", v2_removed_top))
    report.append("\n")

    report.append("## final output changes vs prev (top 20)\n")
    report.append(list_block("Added", final_added_top))
    report.append(list_block("Removed", final_removed_top))
    report.append("\n")

    report.append("## v2fly per-category stats\n")
    report.append("| category | valid_domains | extras_added | invalid_lines | skipped_directives | status |\n")
    report.append("|---|---:|---:|---:|---:|---|\n")
    report.extend([r + "\n" for r in cat_rows])

    report.append("\nNotes:\n")
    report.append("- `valid_domains` = домены из категории после фильтра (full:/domain:/голые домены)\n")
    report.append("- `extras_added` = домены, которые реально попали в хвост (не пересекаются с itdog)\n")
    report.append("- `skipped_directives` = include:/regexp:/keyword:/etc (не разворачиваем)\n\n")

    report.append("## Warnings\n")
    if warnings:
        for w in warnings:
            report.append(f"- {w}\n")
        if run_url:
            report.append(f"\nActions run: {run_url}\n")
    else:
        report.append("- ✅ Предупреждений нет\n")

    report.append("\n## Hashes\n")
    report.append(f"- sha256(final): {final_sha}\n")

    with open(OUT_REPORT, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(report))

    # ---------- state.json ----------
    state = {
        "build_time_utc": build_time,
        "sha256_final": final_sha,
        "itdog_domains": sorted(itdog_set),
        "v2fly_extras": sorted(v2_extras_set),
        "final_domains": sorted(final_set),
    }
    with open(OUT_STATE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ---------- tg_message.txt ----------
    date_part = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    time_part = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    status_line = "🚀 KVAS Domains — сборка завершена успешно"
    if warnings:
        status_line = "🚀 KVAS Domains — сборка завершена (с предупреждениями)"

    tg = []
    tg.append(status_line + "\n\n")
    tg.append(f"🗓  {date_part}\n")
    tg.append(f"🕒  {time_part}\n\n")

    tg.append("━━━━━━━━━━━━━━━━━━\n")
    tg.append("📦 РЕЗУЛЬТАТ\n")
    tg.append("━━━━━━━━━━━━━━━━━━\n")
    tg.append("📄 inside-kvas.lst\n")
    tg.append(f"📊 {len(final_list)} / {MAX_LINES} ({usage_pct:.1f}%)\n")
    tg.append(f"{'🟠' if near_limit else '🟢'} Близко к лимиту: {'ДА' if near_limit else 'НЕТ'}\n\n")

    tg.append("━━━━━━━━━━━━━━━━━━\n")
    tg.append("🔄 ИЗМЕНЕНИЯ (относительно прошлой сборки)\n")
    tg.append("━━━━━━━━━━━━━━━━━━\n")
    tg.append(f"🟦 itdog         {fmt_delta(len(itdog_added), len(itdog_removed))}   (всего {len(itdog_set)})\n")
    tg.append(f"🟩 v2fly extras  {fmt_delta(len(v2extras_added), len(v2extras_removed))}  (всего {len(v2_extras_set)})\n")
    tg.append(f"🧩 итоговый файл {fmt_delta(len(final_added), len(final_removed))}  (всего {len(final_list)})\n\n")

    if warnings:
        tg.append("━━━━━━━━━━━━━━━━━━\n")
        tg.append("⚠ ПРЕДУПРЕЖДЕНИЯ\n")
        tg.append("━━━━━━━━━━━━━━━━━━\n")
        for w in warnings[:10]:
            tg.append(f"{w}\n")

        tg.append(f"\n🔐 sha256: {final_sha[:4]}…{final_sha[-4:]}\n")

        if run_url:
            tg.append(f"\n🔎 Подробности:\n{run_url}\n")

        tg.append("\n📎 Полный отчёт во вложении\n")
    else:
        tg.append("━━━━━━━━━━━━━━━━━━\n")
        tg.append("🛡 СТАТУС\n")
        tg.append("━━━━━━━━━━━━━━━━━━\n")
        tg.append("✅ Предупреждений нет\n")
        tg.append(f"🔐 sha256: {final_sha[:4]}…{final_sha[-4:]}\n\n")
        tg.append("📎 Полный отчёт во вложении\n")

    with open(OUT_TG, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(tg))

    # ---------- короткий вывод в Actions лог ----------
    print("==== SUMMARY ====")
    print(f"itdog total={len(itdog_set)} delta={fmt_delta(len(itdog_added), len(itdog_removed))}")
    print(f"v2fly extras total={len(v2_extras_set)} delta={fmt_delta(len(v2extras_added), len(v2extras_removed))} ok={v2_ok} fail={v2_fail}")
    print(f"final total={len(final_list)} delta={fmt_delta(len(final_added), len(final_removed))} truncated={truncated} near_limit={near_limit}")
    print(f"sha256(final)={final_sha}")


if __name__ == "__main__":
    main()