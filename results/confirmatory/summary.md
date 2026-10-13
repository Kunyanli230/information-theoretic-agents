# Confirmatory summary (UNDERPOWERED, 7 tasks)

- episodes: 378
- guide: grok-4.6 / path-A fresh z
- family: short=m2, long=m3, m4 dropped
- gate λ=0.001, μ=0.0
- capability gap: PASSED → confirmatory path (not exploratory downgrade)

## Success by arm (pooled)

| arm | rate | k/n | 90% Wilson |
|-----|------|-----|------------|
| C0 | 0.381 | 8/21 | [0.23,0.56] |
| C1 | 0.952 | 20/21 | [0.81,0.99] |
| C2 | 0.556 | 35/63 | [0.45,0.65] |
| C3 | 0.810 | 51/63 | [0.72,0.88] |
| G_fix | 0.587 | 37/63 | [0.48,0.68] |
| G_fixL | 0.810 | 51/63 | [0.72,0.88] |
| VD | 0.952 | 20/21 | [0.81,0.99] |
| VD_enc | 0.841 | 53/63 | [0.75,0.90] |

## Q3: G_fixL vs VD (encoder increment)

- G_fixL: 0.810 (51/63)
- VD_enc: 0.841 (53/63)
- VD (full): 0.952 (20/21)
- paired mean (VD_enc−G_fixL): 0.031746031746031744
- empirical encoder increment: **yes**

## Takeover selection (paid requests)

- G_fix: takeover_among_paid=0.0, q_counts={'short': 21}
- G_fixL: takeover_among_paid=0.0, q_counts={'long': 21}
- VD_enc: takeover_among_paid=0.0, q_counts={'rd': 21}
- VD: takeover_among_paid=1.0, q_counts={'takeover': 21}

## C2/C3 × delay (Thm-2 directional; primary logistic separate)

- C2: d=0:0.5238095238095238, d=1:0.6190476190476191, d=2:0.5238095238095238
- C3: d=0:0.8571428571428571, d=1:0.7142857142857143, d=2:0.8571428571428571

## Stale: {'n_delayed': 210, 'n_stale': 10, 'rate': 0.047619047619047616}

## Decision-rule reminders

1. UNDERPOWERED — do not claim powered cost non-inferiority.
2. If VD ≯ G_fixL → RD encoder theory-only.
3. If VD takeover_among_paid > 50% → upgrade-routing claim unless sensitivity.
4. Do not claim optimal length shortens with delay from discrete argmax alone.
