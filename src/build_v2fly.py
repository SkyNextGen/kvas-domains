import os
import re
from urllib.request import urlopen

V2FLY_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
ALLOW_FILE = "src/v2fly_allow.txt"
OUT_FILE = "dist/v2fly-only.lst"

# Практичный валидатор домена (ASCII, без IDN/punycode усложнений)
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

# Служебные типы правил v2fly, которые нам НЕ нужны для kvas
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
    s = s.strip().lower()
    s = s.lstrip(".")
    if not s:
        return None
    # отсекаем явно не доменные вещи
    if " " in s or "/" in s or "\\" in s:
        return None
    # домены с '_' встречаются в реальности, но для kvas лучше держать строго
    if "_" in s:
        return None
    return s if DOMAIN_RE.match(s) else None

def parse_v2fly(text: str) -> list[str]:
    out: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # выкидываем служебные правила
        low = line.lower()
        if low.startswith(SKIP_PREFIXES):
            continue

        # 1) full:
        if low.startswith("full:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
            continue

        # 2) domain:
        if low.startswith("domain:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
            continue

        # 3) голый домен (без префикса), как в wbgames
        # если есть двоеточие — это, скорее всего, другой тип правила (пропускаем)
        if ":" in line:
            continue

        d = norm_domain(line)
        if d:
            out.append(d)

    return out

def read_allow_list() -> list[str]:
    if not os.path.exists(ALLOW_FILE):
        raise SystemExit(f"Missing {ALLOW_FILE}. Create it first.")

    with open(ALLOW_FILE, "r", encoding="utf-8") as f:
        names = []
        for raw in f.read().splitlines():
            x = raw.strip()
            if not x or x.startswith("#"):
                continue
            # имена файлов в data обычно lowercase
            names.append(x)
        return names

def main():
    names = read_allow_list()

    ok = 0
    fail = 0
    all_domains: list[str] = []

    for name in names:
        url = f"{V2FLY_BASE}/{name}"
        try:
            text = fetch_text(url)
            items = parse_v2fly(text)
            all_domains.extend(items)
            ok += 1
            print(f"[OK] {name}: +{len(items)}")
        except Exception as e:
            fail += 1
            print(f"[FAIL] {name}: {e}")

    final = sorted(set(all_domains))

    if not final:
        raise SystemExit("Empty result (no domains parsed). Check allow list categories.")

    os.makedirs("dist", exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(final) + "\n")

    print(f"lists ok={ok}, fail={fail}")
    print(f"domains={len(final)}")
    print(f"output={OUT_FILE}")

if __name__ == "__main__":
    main()