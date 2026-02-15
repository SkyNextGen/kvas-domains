# KVAS domains build report

Build time (UTC): 2026-02-15 06:46:56
Repo: SkyNextGen/kvas-domains
Output: dist/inside-kvas.lst
Max lines: 3000

## Summary
- itdog:
  - total: 1123
  - change vs prev: +1123 / -0
- v2fly (extras only: not in itdog):
  - total: 670
  - change vs prev: +670 / -0
  - lists: ok=8, fail=0
- final output:
  - total: 1793
  - change vs prev: +1793 / -0
  - truncated: 0

## Limit status
- usage: 1793 / 3000 (59.8%)
- near limit: NO (threshold: 2900)

## itdog changes vs prev (top 20)
### Added
1. 10minutemail.com
2. 1337x.to
3. 24.kg
4. 4freerussia.org
5. 4pda.to
6. 4pda.ws
7. 4pna.com
8. 5sim.net
9. 7dniv.rv.ua
10. 7tv.app
11. 7tv.io
12. 9tv.co.il
13. a-vrv.akamaized.net
14. abercrombie.com
15. abook-club.ru
16. academy.terrasoft.ua
17. activatica.org
18. adguard.com
19. adidas.com
20. adminforge.de
### Removed
- none

## v2fly extras changes vs prev (top 20)
### Added
1. aboutfacebook.com
2. accessfacebookfromschool.com
3. acebooik.com
4. acebook.com
5. achat-followers-instagram.com
6. acheter-followers-instagram.com
7. acheterdesfollowersinstagram.com
8. acheterfollowersinstagram.com
9. advancediddetection.com
10. airhorn.solutions
11. airhornbot.com
12. askfacebook.net
13. askfacebook.org
14. atdmt2.com
15. atlasdmt.com
16. atlasonepoint.com
17. bigbeans.solutions
18. bookstagram.com
19. buyingfacebooklikes.com
20. careersatfb.com
### Removed
- none

## final output changes vs prev (top 20)
### Added
1. 10minutemail.com
2. 1337x.to
3. 24.kg
4. 4freerussia.org
5. 4pda.to
6. 4pda.ws
7. 4pna.com
8. 5sim.net
9. 7dniv.rv.ua
10. 7tv.app
11. 7tv.io
12. 9tv.co.il
13. a-vrv.akamaized.net
14. abercrombie.com
15. abook-club.ru
16. aboutfacebook.com
17. academy.terrasoft.ua
18. accessfacebookfromschool.com
19. acebooik.com
20. acebook.com
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
- Failed categories (download/parse errors):
- none
- Empty categories (0 valid domains):
- none
- Bad output lines: 0
- Truncated output: NO

## Hashes
- sha256(final): 9119...8e20
