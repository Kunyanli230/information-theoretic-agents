# Path-A N=24 calibration summary (Cursor CLI / grok-4.6)

- prereg: `v3-path-A`
- guide: `grok-4.6` via `cursor-cli-agent` `2026.10.01-e373342`
- capability gap: guide_alone=1.0, small_alone=0.56, gap=44.0 pp (PASS)
- N prefixes: 24, forks: 336
- started: 2026-10-14T00:00:18+0800
- finished: 2026-10-14T01:06:06+0800

## Success by arm

| arm | success | n | rate |
|-----|---------|---|------|
| control | 10 | 24 | 0.417 |
| m1 | 31 | 72 | 0.431 |
| m2 | 38 | 72 | 0.528 |
| m3 | 56 | 72 | 0.778 |
| m4 | 56 | 72 | 0.778 |
| takeover | 22 | 24 | 0.917 |

## Success by arm × delay

| arm | d | success | n | rate |
|-----|---|---------|---|------|
| control | 0 | 10 | 24 | 0.417 |
| m1 | 0 | 10 | 24 | 0.417 |
| m1 | 1 | 11 | 24 | 0.458 |
| m1 | 2 | 10 | 24 | 0.417 |
| m2 | 0 | 14 | 24 | 0.583 |
| m2 | 1 | 13 | 24 | 0.542 |
| m2 | 2 | 11 | 24 | 0.458 |
| m3 | 0 | 20 | 24 | 0.833 |
| m3 | 1 | 19 | 24 | 0.792 |
| m3 | 2 | 17 | 24 | 0.708 |
| m4 | 0 | 20 | 24 | 0.833 |
| m4 | 1 | 19 | 24 | 0.792 |
| m4 | 2 | 17 | 24 | 0.708 |
| takeover | None | 22 | 24 | 0.917 |

## Status counts

```
{
  "none": 24,
  "accepted": 192,
  "not_needed": 80,
  "takeover": 24,
  "stale": 16
}
```
