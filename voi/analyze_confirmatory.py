"""Summarize confirmatory results: rates, G_fixL vs VD, takeover rate, underpowered."""
from __future__ import annotations

import json
import math
import os
import statistics as st
from collections import Counter, defaultdict

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "confirmatory")
INP = os.path.join(OUT_DIR, "confirm.json")


def _wilson(k, n, z=1.64485):
    """90% Wilson interval (matches pilot-style one-sided~95 feeling; report as 90% two-sided)."""
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / den, (centre + margin) / den


def rate(xs):
    n = len(xs)
    k = sum(1 for x in xs if x)
    lo, hi = _wilson(k, n)
    return dict(n=n, k=k, rate=(k / n if n else None), ci90=[lo, hi])


def main():
    state = json.load(open(INP))
    eps = state.get("episodes") or []
    meta = state.get("meta") or {}

    by_arm = defaultdict(list)
    by_arm_d = defaultdict(list)
    for e in eps:
        by_arm[e["arm"]].append(e)
        by_arm_d[(e["arm"], e.get("d"))].append(e)

    arm_rates = {a: rate([e["success"] for e in xs]) for a, xs in sorted(by_arm.items())}
    arm_d_rates = {
        f"{a}|d={d}": rate([e["success"] for e in xs])
        for (a, d), xs in sorted(by_arm_d.items(), key=lambda x: (x[0][0], x[0][1] if x[0][1] is not None else -1))
    }

    # Primary Q3: VD vs G_fixL — pool over delays for gated; fixed use all d
    def pool(arm):
        return [e["success"] for e in by_arm.get(arm, [])]

    gfixl = rate(pool("G_fixL"))
    vd_enc = rate(pool("VD_enc"))
    vd = rate(pool("VD"))
    # paired by (tid,seed,d) where both exist
    idx = {}
    for e in eps:
        if e["arm"] in ("G_fixL", "VD_enc"):
            idx.setdefault((e["tid"], e["seed"], e.get("d")), {})[e["arm"]] = e
    paired = []
    for k, m in idx.items():
        if "G_fixL" in m and "VD_enc" in m:
            paired.append(dict(
                key=k,
                g=1 if m["G_fixL"]["success"] else 0,
                v=1 if m["VD_enc"]["success"] else 0,
            ))
    if paired:
        diff = st.mean(p["v"] - p["g"] for p in paired)
    else:
        diff = None

    # takeover selection on gated arms
    takeover_stats = {}
    for arm in ("G_fix", "G_fixL", "VD_enc", "VD"):
        xs = by_arm.get(arm, [])
        # unique decisions per prefix: prefer d=0 or d=None
        seen = {}
        for e in xs:
            key = (e["tid"], e["seed"])
            d = e.get("d")
            if key not in seen or d in (0, None):
                seen[key] = e
        decs = list(seen.values())
        req = [e for e in decs if e.get("request")]
        to = [e for e in req if e.get("q_star") == "takeover"]
        takeover_stats[arm] = dict(
            n_prefixes=len(decs),
            n_request=len(req),
            n_takeover=len(to),
            takeover_among_paid=(len(to) / len(req) if req else None),
            q_counts=dict(Counter(e.get("q_star") for e in decs)),
        )

    # stale on delayed message deliveries
    delayed = [e for e in eps if e.get("d") in (1, 2) and e.get("mid")]
    stale_n = sum(1 for e in delayed if e.get("status") == "stale")
    stale = dict(n_delayed=len(delayed), n_stale=stale_n,
                 rate=(stale_n / len(delayed) if delayed else None))

    # C2/C3 delay gradient (Thm2 directional / logistic later)
    c2_by_d = {d: rate([e["success"] for e in by_arm_d.get(("C2", d), [])]) for d in (0, 1, 2)}
    c3_by_d = {d: rate([e["success"] for e in by_arm_d.get(("C3", d), [])]) for d in (0, 1, 2)}

    # cost (guide_out mean)
    cost = {}
    for a, xs in by_arm.items():
        outs = [e.get("guide_out") or 0 for e in xs]
        cost[a] = dict(mean_guide_out=st.mean(outs) if outs else None, n=len(outs))

    q3 = dict(
        G_fixL=gfixl,
        VD_enc=vd_enc,
        VD_full=vd,
        paired_n=len(paired),
        paired_mean_VD_enc_minus_G_fixL=diff,
        encoder_empirical_increment=(
            None if diff is None else (
                "yes" if diff > 1e-9 else ("no" if diff < -1e-9 else "tie")
            )
        ),
        note=(
            "Q3 primary = G_fixL vs VD_enc (candidates without takeover). "
            "Full VD (with takeover) reported separately. "
            "If VD_enc does not beat G_fixL, Theorem-1 encoder stays theory-only."
        ),
    )

    summary = dict(
        meta=dict(
            label="underpowered",
            n_episodes=len(eps),
            n_snapshots=len(state.get("snapshots") or []),
            guide_model=meta.get("guide_model"),
            gate_lam=meta.get("gate_lam"),
            gate_mu=meta.get("gate_mu"),
            short_mid=meta.get("short_mid"),
            long_mid=meta.get("long_mid"),
            capability_gap_passed=meta.get("capability_gap_passed"),
            confirmatory_claim_level="confirmatory_underpowered_not_exploratory_downgrade",
        ),
        arm_rates=arm_rates,
        arm_delay_rates=arm_d_rates,
        q3_G_fixL_vs_VD=q3,
        takeover_selection=takeover_stats,
        stale=stale,
        c2_by_delay=c2_by_d,
        c3_by_delay=c3_by_d,
        cost=cost,
    )
    json.dump(summary, open(os.path.join(OUT_DIR, "summary.json"), "w"), indent=2)

    lines = [
        "# Confirmatory summary (UNDERPOWERED, 7 tasks)",
        "",
        f"- episodes: {len(eps)}",
        f"- guide: {meta.get('guide_model')} / path-A fresh z",
        f"- family: short={meta.get('short_mid')}, long={meta.get('long_mid')}, m4 dropped",
        f"- gate λ={meta.get('gate_lam')}, μ={meta.get('gate_mu')}",
        f"- capability gap: PASSED → confirmatory path (not exploratory downgrade)",
        "",
        "## Success by arm (pooled)",
        "",
        "| arm | rate | k/n | 90% Wilson |",
        "|-----|------|-----|------------|",
    ]
    for a, r in sorted(arm_rates.items()):
        ci = r["ci90"]
        ci_s = f"[{ci[0]:.2f},{ci[1]:.2f}]" if ci[0] is not None else "—"
        lines.append(f"| {a} | {r['rate']:.3f} | {r['k']}/{r['n']} | {ci_s} |")

    lines += [
        "",
        "## Q3: G_fixL vs VD (encoder increment)",
        "",
        f"- G_fixL: {gfixl['rate']:.3f} ({gfixl['k']}/{gfixl['n']})",
        f"- VD_enc: {vd_enc['rate']:.3f} ({vd_enc['k']}/{vd_enc['n']})",
        f"- VD (full): {vd['rate']:.3f} ({vd['k']}/{vd['n']})",
        f"- paired mean (VD_enc−G_fixL): {diff}",
        f"- empirical encoder increment: **{q3['encoder_empirical_increment']}**",
        "",
        "## Takeover selection (paid requests)",
        "",
    ]
    for arm, t in takeover_stats.items():
        lines.append(
            f"- {arm}: takeover_among_paid={t['takeover_among_paid']}, "
            f"q_counts={t['q_counts']}"
        )
    lines += [
        "",
        "## C2/C3 × delay (Thm-2 directional; primary logistic separate)",
        "",
        f"- C2: " + ", ".join(f"d={d}:{c2_by_d[d]['rate']}" for d in (0, 1, 2)),
        f"- C3: " + ", ".join(f"d={d}:{c3_by_d[d]['rate']}" for d in (0, 1, 2)),
        "",
        f"## Stale: {stale}",
        "",
        "## Decision-rule reminders",
        "",
        "1. UNDERPOWERED — do not claim powered cost non-inferiority.",
        "2. If VD ≯ G_fixL → RD encoder theory-only.",
        "3. If VD takeover_among_paid > 50% → upgrade-routing claim unless sensitivity.",
        "4. Do not claim optimal length shortens with delay from discrete argmax alone.",
        "",
    ]
    open(os.path.join(OUT_DIR, "summary.md"), "w").write("\n".join(lines))
    print("WROTE", OUT_DIR)
    print("Q3", q3["encoder_empirical_increment"], "VD_enc", vd_enc["rate"], "G_fixL", gfixl["rate"], "VD", vd["rate"])


if __name__ == "__main__":
    main()
