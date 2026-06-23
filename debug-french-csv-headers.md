[OPEN] french-csv-headers

- Scope: implement French Legrand CSV header support and validate end-to-end import recovery
- Constraints:
  - keep responses in English
  - limit code changes to header alias recognition and targeted tests
  - restart Agent only after code/test validation

## Hypotheses

1. The only blocker for `192.168.1.201` session import is unsupported French CSV header aliases in `driver.py`.
2. Once the French aliases are added, the existing parser, datetime parsing, and numeric parsing logic will successfully import the CSV rows without further parser changes.
3. Italian CSV imports from `192.168.1.200` will remain valid because the alias expansion is additive and will not displace existing matches.
4. After restarting `CondoChargeAgent`, the next session import cycle will backfill the missing `192.168.1.201` sessions up to the latest CSV row timestamp.
5. The recurring `CSV is missing required column` error for `192.168.1.201` will disappear, while unrelated Legrand warnings for other data issues may still remain.

## Evidence Log

- Prior audits confirmed `192.168.1.201` returns a valid French CSV with unsupported header labels.
- Prior audits confirmed the active Agent process can be restarted locally and posts successfully to production.
