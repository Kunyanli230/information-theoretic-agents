# Signal probe summary (v3)

- Snapshots: 8; forks: 40; d=0 only.
- Q1-style lift exists: **True** (best m3 75% vs control 38%, lift +37.5 pp).

| arm | n | success | guide_out mean | message_cost mean | accepted | stale |
|---|---:|---:|---:|---:|---:|---:|
| control | 8 | 37.5% | 0 | 0.0 | 0 | 0 |
| m1 | 8 | 50.0% | 121 | 14.1 | 8 | 0 |
| m2 | 8 | 62.5% | 121 | 50.2 | 8 | 0 |
| m3 | 8 | 75.0% | 121 | 76.6 | 8 | 0 |
| m4 | 8 | 75.0% | 121 | 101.9 | 8 | 0 |

## Paired lift vs control

- m1: mean lift +12.5 pp (better 1 / worse 0 / tie 7)
- m2: mean lift +25.0 pp (better 2 / worse 0 / tie 6)
- m3: mean lift +37.5 pp (better 4 / worse 1 / tie 3)
- m4: mean lift +37.5 pp (better 4 / worse 1 / tie 3)

Footnote: `guide_out` is diagnosis-call output (shared across m on a prefix); `message_cost` is post-encode est_tokens of rendered m (encoder-differentiating c).

Probe is directional only; do not expand to full cal if no Q1-style lift.
