#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple, Dict, Set, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# Базовые пути проекта
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DIST_DIR = ROOT / "dist"
HISTORY_DIR = DIST_DIR / "history"

# Источник itdog (основной список)
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"

# База для категорий v2fly
V2FLY_DATA_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"

# Файл с перечислением категорий v2fly
V2FLY_CATEGORIES_FILE = SRC_DIR / "v2fly_categories.txt"

# Финальный список для kvas
FINAL_OUT = DIST_DIR / "inside-kvas.lst"

# Отчёт и служебные файлы
REPORT_OUT = DIST_DIR / "report.md"
TG_MESSAGE_OUT = DIST_DIR / "tg_message.txt"
TG_ALERT_OUT = DIST_DIR / "tg_alert.txt"
STATS_JSON = DIST_DIR / "stats.json"

# Сколько снапшотов хранить в history
MAX_HISTORY = 12


# Проверка домена
DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$",
    re.IGNORECASE,
)

# В v2fly интересуют только явные домены
V2FLY_PREFIXES = ("full:", "domain:")


@dataclass
class FetchResult:
    ok: bool
    text: str
    error: Optional[str] = None
    status: Optional[int] = None


# Простой http get
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


# Нормализация строки к домену
def normalize_domain(s: str) -> Optional[str]:
    s = s.strip().lower().replace("\r", "")
    if not s:
        return None
    if s.endswith("."):
        s = s[:-1]
    return s if is_domain(s) else None


# Парсинг itdog
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


# Парсинг одного файла v2fly
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

    return out


# Читаем список категорий v2fly
def read_v2fly_categories(path: Path) -> List[str]:
    if not path.exists():
        return []
    cats = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cats.append(line)
    return cats


# Предыдущий финальный список
def load_previous_final(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [
        x.strip()
        for x in path.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]


# Разница между версиями
def diff_lists(prev: Iterable[str], curr: Iterable[str]) -> Tuple[List[str], List[str]]:
    prev_set = set(prev)
    curr_set = set(curr)
    added = sorted(curr_set - prev_set)
    removed = sorted(prev_set - curr_set)
    return added, removed


# Создание нужных директорий
def ensure_dirs() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# Чистим старые снапшоты
def rotate_history(history_dir: Path, max_items: int) -> None:
    files = sorted(history_dir.glob("snapshot-*.lst"))
    for p in files[:-max_items]:
        p.unlink(missing_ok=True)

    diffs = sorted(history_dir.glob("diff-*.txt"))
    for p in diffs[:-max_items]:
        p.unlink(missing_ok=True)


# Обновление stats.json
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
        except Exception:
            data = []
    else:
        data = []

    data.append(rec)
    data = data[-200:]

    STATS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "first": data[0],
        "prev": data[-2] if len(data) >= 2 else None,
        "count": len(data),
        "min_total": min(x["total"] for x in data),
        "max_total": max(x["total"] for x in data),
    }


# Формирование markdown-отчёта
def format_report(
    total_domains: int,
    prev_total: Optional[int],
    itdog_added: int,
    v2fly_added: int,
    added: List[str],
    removed: List[str],
    warnings: List[str],
    stats_info: Dict,
) -> str:

    delta = (total_domains - prev_total) if prev_total else None
    delta_str = f"{delta:+d}" if delta is not None else "—"

    lines = []
    lines.append("# KVAS domains report\n")
    lines.append(f"**UTC:** {now_utc_iso()}\n")
    lines.append(f"- Итог: **{total_domains}** (Δ {delta_str})")
    lines.append(f"- itdog новых: **{itdog_added}**")
    lines.append(f"- v2fly новых: **{v2fly_added}**\n")

    lines.append("## Предупреждения")
    lines.append("\n".join(warnings) if warnings else "нет")
    lines.append("\n")

    lines.append("## Топ добавленных")
    lines.extend(added[:20] or ["нет"])
    lines.append("\n")

    lines.append("## Топ удалённых")
    lines.extend(removed[:20] or ["нет"])
    lines.append("\n")

    lines.append("## Рост за всё время")
    lines.append(f"- Билдов: {stats_info['count']}")
    lines.append(f"- Минимум: {stats_info['min_total']}")
    lines.append(f"- Максимум: {stats_info['max_total']}")
    lines.append(
        f"- Рост с первого: {total_domains - stats_info['first']['total']:+d}"
    )

    return "\n".join(lines)


def main() -> int:
    ensure_dirs()

    prev_final = load_previous_final(FINAL_OUT)
    prev_total = len(prev_final) if prev_final else None

    # itdog
    itdog_fetch = http_get_text(ITDOG_URL)
    itdog_list = parse_itdog(itdog_fetch.text) if itdog_fetch.ok else []

    # v2fly
    categories = read_v2fly_categories(V2FLY_CATEGORIES_FILE)
    v2fly_all: List[str] = []

    for cat in categories:
        res = http_get_text(f"{V2FLY_DATA_BASE}/{cat}")
        if res.ok:
            v2fly_all.extend(parse_v2fly_file(res.text))

    # Убираем дубли
    itdog_unique = list(dict.fromkeys(itdog_list))
    itdog_set = set(itdog_unique)

    v2fly_unique = sorted({d for d in v2fly_all if d not in itdog_set})

    final_list = itdog_unique + v2fly_unique
    total_domains = len(set(final_list))

    added, removed = diff_lists(prev_final, final_list)

    itdog_added = len(set(itdog_unique) - set(prev_final))
    v2fly_added = len(set(v2fly_unique) - set(prev_final))

    FINAL_OUT.write_text("\n".join(final_list) + "\n", encoding="utf-8")

    stats_info = append_stats(
        total=total_domains,
        itdog_count=len(itdog_unique),
        v2fly_count=len(v2fly_unique),
        warnings=[],
    )

    REPORT_OUT.write_text(
        format_report(
            total_domains,
            prev_total,
            itdog_added,
            v2fly_added,
            added,
            removed,
            [],
            stats_info,
        ),
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
