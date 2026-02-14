import os
import re
from urllib.request import urlopen

# ===== Sources =====
ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"
V2FLY_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
V2FLY_ALLOW_FILE = "src/v2fly_allow.txt"

# ===== Output =====
OUT_FILE = "dist/inside-kvas.lst"
MAX_LINES = 3000  # при желании меняй

# ===== Domain validation =====
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

# Служебные типы правил v2fly, которые нам НЕ нужны для kvas (пока include не разворачиваем)
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

def fetch_text(url: str) -> str:
    with urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def norm_domain(s: str) -> str | None:
    s = s.strip().lower().lstrip(".")
    if not s:
        return None
    if " " in s or "/" in s or "\\" in s:
        return None
    if "_" in s:
        return None
    return s if DOMAIN_RE.match(s) else None

# ===== itdog =====
def parse_itdog(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = norm_domain(line)
        if d:
            out.append(d)
    return out

# ===== v2fly =====
def read_v2fly_allow() -> list[str]:
    if not os.path.exists(V2FLY_ALLOW_FILE):
        return []
    with open(V2FLY_ALLOW_FILE, "r", encoding="utf-8") as f:
        return [x.strip() for x in f.read().splitlines() if x.strip() and not x.strip().startswith("#")]

def parse_v2fly(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        low = line.lower()

        # выкидываем мусорные директивы
        if low.startswith(SKIP_PREFIXES):
            continue

        # full:
        if low.startswith("full:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
            continue

        # domain:
        if low.startswith("domain:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
            continue

        # голый домен (без префикса)
        if ":" in line:
            continue

        d = norm_domain(line)
        if d:
            out.append(d)

    return out

def fetch_v2fly_domains() -> tuple[list[str], int, int]:
    names = read_v2fly_allow()
    ok = 0
    fail = 0
    all_domains = []

    for name in names:
        url = f"{V2FLY_BASE}/{name}"
        try:
            items = parse_v2fly(fetch_text(url))
            all_domains.extend(items)
            ok += 1
            print(f"[OK] v2fly/{name}: +{len(items)}")
        except Exception as e:
            fail += 1
            print(f"[FAIL] v2fly/{name}: {e}")

    return all_domains, ok, fail

def main():
    # 1) itdog база
    itdog_domains = parse_itdog(fetch_text(ITDOG_URL))
    itdog_set = set(itdog_domains)

    # 2) v2fly
    v2fly_domains, ok, fail = fetch_v2fly_domains()

    # 3) dedupe: добавляем из v2fly ТОЛЬКО то, чего нет в itdog
    extras_set = set()
    for d in v2fly_domains:
        if d not in itdog_set:
            extras_set.add(d)

    extras_sorted = sorted(extras_set)

    # 4) финальный порядок: itdog как есть + хвост v2fly sorted
    final = itdog_domains + extras_sorted

    # 5) лимит (приоритет itdog)
    truncated = 0
    if len(final) > MAX_LINES:
        truncated = len(final) - MAX_LINES
        final = final[:MAX_LINES]

    if not final:
        raise SystemExit("Empty result")

    os.makedirs("dist", exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(final) + "\n")

    print("==== SUMMARY ====")
    print(f"itdog: {len(itdog_domains)}")
    print(f"v2fly lists ok={ok}, fail={fail}")
    print(f"v2fly parsed (raw): {len(v2fly_domains)}")
    print(f"v2fly unique extras: {len(extras_set)}")
    print(f"final lines: {len(final)} (max={MAX_LINES}, truncated={truncated})")
    print(f"output: {OUT_FILE}")

if __name__ == "__main__":
    main()