# Confirmatory DONE — Q3 ablation note (UNDERPOWERED)

**Label:** underpowered (7 tasks × 3 snaps; not powered cost non-inferiority).
**Family:** short=m2, long=m3, **m4 dropped**.
**Guide:** grok-4.6 / Cursor CLI, path-A fresh diagnoses. Gap gate PASSED → confirmatory path (not exploratory downgrade).

## Primary ablation: VD_enc vs G_fixL

| arm | success | k/n |
|-----|---------|-----|
| G_fixL (fixed long / gated short-set without takeover) | **81.0%** | 51/63 |
| VD_enc (encoder Δ̂ among {short,long,rd}, no takeover) | **84.1%** | 53/63 |
| paired mean (VD_enc − G_fixL) | **+3.17 pp** | n=63 pairs |
| empirical encoder increment | **yes** (tiny) | |

Full **VD** (candidates include takeover): **95.2%** (20/21) — but `takeover_among_paid=1.0` (always picks takeover) ⇒ collapses to C1 / upgrade-routing; do **not** treat full VD as encoder evidence. Q3 claim rests on **VD_enc vs G_fixL**.

## Floors / fixed arms

- C0 control 38.1% (8/21)
- C1 takeover 95.2% (20/21)
- C2 short=m2 55.6% (35/63); C3 long=m3 81.0% (51/63)
- G_fix short-gated 58.7% (37/63)

## Other

- Stale on delayed deliveries: 10/210 = **4.76%** (<5% threshold)
- C3×delay: 85.7% / 71.4% / 85.7% (not monotone; Thm-2 logistic still separate)
- Gate λ=0.001, μ=0.0 → argmax often near-fixed length (cal foreshadowed)

## Decision reminders applied

1. UNDERPOWERED — no powered cost claims.
2. Encoder increment exists but small (+3 pp); report cautiously; theory still primary for Thm-1 if reviewers demand powered Δ.
3. Full VD takeover rate 100% → upgrade-routing caveat / sensitivity required.
4. Do not claim optimal length shortens with delay from discrete argmax alone.
