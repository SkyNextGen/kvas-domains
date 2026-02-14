import os
from urllib.request import urlopen

ITDOG_URL = "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-kvas.lst"
OUT_FILE = "dist/inside-kvas.lst"

def fetch_text(url: str) -> str:
    with urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def main():
    text = fetch_text(ITDOG_URL)

    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.lower())

    if not lines:
        raise SystemExit("Empty result")

    os.makedirs("dist", exist_ok=True)

    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(sorted(set(lines))) + "\n")

    print(f"Total domains: {len(lines)}")

if __name__ == "__main__":
    main()
