# TabularGainPredictor fit (path-A N=24)

- short=m2, long=m3, rd-default=m3
- fit tasks: T09, T10, T11, T12, T14, T17
- holdout: T20, T26
- selected λ=0.001, μ=0.0
- labels: Δ^{π0} at d=0; cost = guide est_output_tokens

## Pooled Δ̂ (success − control, cost, n_proxy=1)

- `long`: Δ=0.417, ΔC=125.2, ΔN=1.0
- `rd`: Δ=0.500, ΔC=125.2, ΔN=1.0
- `short`: Δ=0.167, ΔC=125.2, ΔN=1.0
- `takeover`: Δ=0.500, ΔC=31.2, ΔN=1.0

## Holdout VD policy

- success=1.000, cost=31.7, request_rate=1.000, picks={'takeover': 6}

## Cal replay (descriptive, same prefixes used to fit — not confirmatory)

- G_fix: success=0.583, cost=125.2, request_rate=1.0, picks={'short': 24}
- G_fixL: success=0.833, cost=125.2, request_rate=1.0, picks={'long': 24}
- VD_enc: success=0.917, cost=125.2, request_rate=1.0, picks={'rd': 24}
- VD: success=0.917, cost=31.2, request_rate=1.0, picks={'takeover': 24}
- control: success=0.417

## Scheme d=0 rates

- short: success=0.583, cost=125.2, n=24
- long: success=0.833, cost=125.2, n=24
- rd: success=0.917, cost=125.2, n=24
- takeover: success=0.917, cost=31.2, n=24

## Paper notes

1. Family short=m2 / long=m3 / drop m4 — mirrored in gate schemes.
2. Thm1 risk: rd≈long on cal; confirmatory must ablate G_fixL vs VD.
3. Real Δ̂ table (not stub). Cap/backoff: cell n < 3 → pooled.
4. Confirmatory labelled underpowered (7 tasks).
