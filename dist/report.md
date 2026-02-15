# KVAS domains build report

Build time (UTC): 2026-02-15 07:04:30
Repo: SkyNextGen/kvas-domains
Output: dist/inside-kvas.lst
Max lines: 3000

## Summary
- itdog:
  - total: 1123
  - change vs prev: +0 / -0
- v2fly (extras only: not in itdog):
  - total: 670
  - change vs prev: +0 / -0
  - lists: ok=8, fail=0
- final output:
  - total: 1793
  - change vs prev: +0 / -0
  - truncated: 0

## Limit status
- usage: 1793 / 3000 (59.8%)
- near limit: NO (threshold: 2900)

## itdog changes vs prev (top 20)
### Added
- none
### Removed
- none

## v2fly extras changes vs prev (top 20)
### Added
- none
### Removed
- none

## final output changes vs prev (top 20)
### Added
- none
### Removed
- none

## v2fly per-category stats
| category | valid_domains | extras_added | invalid_lines | skipped_directives | status |
|---|---:|---:|---:|---:|---|
| discord | 28 | 8 | 0 | 0 | OK |
| instagram | 72 | 69 | 2 | 0 | OK |
| openai | 16 | 9 | 2 | 1 | OK |
| telegram | 20 | 20 | 0 | 0 | OK |
| whatsapp | 11 | 8 | 2 | 0 | OK |
| youtube | 175 | 162 | 3 | 0 | OK |
| facebook | 394 | 389 | 3 | 0 | OK |
| wbgames | 6 | 5 | 0 | 0 | OK |

Notes:
- `valid_domains` = домены, извлечённые из категории после фильтра (full:/domain:/голые домены)
- `extras_added` = домены, которые реально попали в хвост (не пересекаются с itdog)
- `skipped_directives` = include:/regexp:/keyword:/etc (мы их не разворачиваем)

## Warnings
- Failed categories (download/parse errors): none
- Empty categories (0 valid domains): none
- Bad output lines: 0
- Truncated output: NO

## Hashes
- sha256(final): 9119...8e20
