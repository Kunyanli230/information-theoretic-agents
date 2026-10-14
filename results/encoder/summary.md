# Theorem-1 offline encoder fit (path-A N=24)

- source: `results/calibration/cal.json` (commit lineage after `53cf6b1`)
- fit tasks: T09, T10, T11, T12, T14, T17
- nested holdout tasks: T20, T26
- cost c-hat: post-encode est_tokens (not diagnosis baseline)
- distortion d-hat: eq.5 with S=1 CRN forks; pooled over d in {0,1,2} for primary e*; per-delay tables for Thm-2
- short class: **m2** (not m1 — cal m1≈control)
- long class: **m3**
- default family: `['m1', 'm2', 'm3']` — **m4 dropped from default encode family**
- selected λ=0.0, β=0.05
- **honesty:** nested holdout picked λ=0 (pure distortion). Frozen argmax is ~fixed **m3** (22/24 prefixes). Cost term does not move picks once m4 is dropped — Q3 / prediction-5 risk: gate+fixed-long may match RD encoder. Report as cal fact; confirmatory must ablate G_fixL vs VD.
- **Thm-2 on discrete argmax:** per-delay BA did **not** shift mass to shorter m as d↑ (d=0: 2×m2+22×m3; d=1–2: 24×m3). Long−short gap m3−m2 stays ~25 pp across delays in this N=24 sample. Absolute m3 decline 83→79→71% is directional only; **primary Thm-2 test remains confirmatory logistic**.


## Descriptive success × cost (all 24 prefixes, pooled delay)

| mid | success | cost (est_tok) | d=0 | d=1 | d=2 |
|-----|---------|----------------|-----|-----|-----|
| m1 | 0.431 | 15.2 | 0.417 | 0.458 | 0.417 |
| m2 | 0.528 | 50.1 | 0.583 | 0.542 | 0.458 |
| m3 | 0.778 | 78.8 | 0.833 | 0.792 | 0.708 |
| m4 | 0.778 | 110.9 | 0.833 | 0.792 | 0.708 |

## Nested holdout family choice

| family | hold success | hold cost | λ | β |
|--------|--------------|-----------|---|---|
| m1–m4 | 0.778 | 73.2 | 0.001 | 0.05 |
| m1–m3 (no m4) | 0.778 | 73.2 | 0.0 | 0.05 |

**Decision:** `drop_m4` — holdout success of no-m4 ≥ full−1pp and cost ≤ full; m3≡m4 on cal rates

## Frozen e* (all cal tasks)

- q*: m1=0.000, m2=0.181, m3=0.819
- argmax counts: {'m1': 0, 'm2': 2, 'm3': 22}
- argmax policy on cal (pooled): success=0.806, cost=76.1
- fixed m2: success=0.528, cost=50.1
- fixed m3: success=0.778, cost=78.8
- fixed m1: success=0.431, cost=15.2
- fixed m4: success=0.778, cost=110.9

## Delay-conditional argmax (Theorem-2 direction)

| delay | argmax counts | q* |
|-------|---------------|----|
| 0 | {'m1': 0, 'm2': 2, 'm3': 22} | m1=0.00, m2=0.20, m3=0.80 |
| 1 | {'m1': 0, 'm2': 0, 'm3': 24} | m1=0.00, m2=0.00, m3=1.00 |
| 2 | {'m1': 0, 'm2': 0, 'm3': 24} | m1=0.00, m2=0.00, m3=1.00 |

## Paper-side notes reflected

1. Main gain at m3; m4 verification dropped from default family (or would be cost-redundant).
2. m3 delay gradient 0.833→0.792→0.708 supports length–delay narrowing; primary logistic still confirmatory.
3. stale=16 (~8% of delayed deliveries) retained as mechanism contribution (see cal_summary).
4. Short arm = **m2** (m1≈control).
5. Capability gap passed → confirmatory path (not exploratory downgrade).

## Confirmatory readiness

- Encoder artifacts frozen under `results/encoder/`.
- No confirmatory runner in repo yet; gate `TabularGainPredictor` still stub — **do not start confirmatory** until gate fit + runner exist and Heath okays.
