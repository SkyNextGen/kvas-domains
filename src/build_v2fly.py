import os
import re
from urllib.request import urlopen

V2FLY_BASE = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
ALLOW_FILE = "src/v2fly_allow.txt"
OUT_FILE = "dist/v2fly-only.lst"

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

def fetch_text(url: str) -> str:
    with urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def norm_domain(s: str) -> str | None:
    s = s.strip().lower().lstrip(".")
    if not s or " " in s or "/" in s:
        return None
    return s if DOMAIN_RE.match(s) else None

def parse_v2fly(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Берём только доменные записи
        if line.startswith("domain:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)
        elif line.startswith("full:"):
            d = norm_domain(line.split(":", 1)[1])
            if d:
                out.append(d)

    return out

def read_allow_list() -> list[str]:
    if not os.path.exists(ALLOW_FILE):
        return []
    with open(ALLOW_FILE, "r", encoding="utf-8") as f:
        return [x.strip() for x in f.read().splitlines() if x.strip() and not x.strip().startswith("#")]

def main():
    names = read_allow_list()
    ok = 0
    fail = 0
    all_domains = []

    for name in names:
        url = f"{V2FLY_BASE}/{name}"
        try:
            all_domains.extend(parse_v2fly(fetch_text(url)))
            ok += 1
        except Exception:
            fail += 1

    final = sorted(set(all_domains))
    if not final:
        raise SystemExit("Empty result")

    os.makedirs("dist", exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(final) + "\n")

    print(f"lists ok={ok}, fail={fail}")
    print(f"domains={len(final)}")

if __name__ == "__main__":
    main()
