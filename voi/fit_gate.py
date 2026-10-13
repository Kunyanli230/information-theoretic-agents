"""Fit TabularGainPredictor Δ̂(φ,q) on path-A N=24 calibration forks.

Labels are Δ^{π0} under frozen executor: Y_q - Y_control for schemes
short=m2, long=m3, rd=e*-argmax mid, takeover — primary at injected d=0
(request immediately after attempt-1). Cost ΔC uses diagnosis/takeover
est_output_tokens (message_cost is encoder-side, not gate fee).

Nested holdout (same split as encoder) selects (λ, μ) for score(q).
Writes results/gate/{predictor.json,summary.md}.
"""
from __future__ import annotations

import json
import os
import statistics as st
import time
from collections import defaultdict

from voi.gate import (
    TabularGainPredictor, make_phi, choose, SHORT_MID, LONG_MID,
    CAND_G_FIX, CAND_G_FIXL, CAND_VD, CAND_VD_ENC, _phi_key,
)

CAL_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "calibration", "cal.json")
E_STAR_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "encoder", "e_star.json")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "gate")

CAL_TASKS = ["T09", "T10", "T11", "T12", "T14", "T17", "T20", "T26"]
HOLDOUT_TASKS = ("T20", "T26")
FIT_TASKS = tuple(t for t in CAL_TASKS if t not in HOLDOUT_TASKS)

LAM_GRID = (0.0, 0.0005, 0.001, 0.002, 0.005, 0.01)
MU_GRID = (0.0, 0.01, 0.05, 0.1, 0.2)


def _zid(tid, seed):
    return f"{tid}:{seed}"


def _diag_cost(diag_rec):
    u = (diag_rec or {}).get("usage") or {}
    if u.get("output_tokens") is not None:
        return float(u["output_tokens"])
    return float(u.get("est_output_tokens") or 0)


def _get_fork(fs, **kw):
    for f in fs:
        if all(f.get(a) == v for a, v in kw.items()):
            return f
    return None


def build_prefix_outcomes(cal, e_star):
    """Per-prefix Y and costs for control / short / long / rd / takeover at d=0."""
    by = defaultdict(list)
    for f in cal["forks"]:
        by[(f["tid"], f["seed"])].append(f)
    diags = cal.get("diagnoses") or {}
    argmax = (e_star or {}).get("argmax_by_z") or {}
    default_rd = "m3"
    # unseen fallback: majority of argmax / q*
    if argmax:
        from collections import Counter
        default_rd = Counter(argmax.values()).most_common(1)[0][0]
    qstar = (e_star or {}).get("q_star") or {}
    if qstar:
        default_rd = max(qstar, key=qstar.get)

    snaps = {(s["tid"], s["seed"]): s for s in cal["snapshots"]}
    rows = []
    for (tid, seed), fs in sorted(by.items()):
        ctrl = _get_fork(fs, arm="control")
        if not ctrl:
            continue
        sn = snaps.get((tid, seed)) or {}
        zid = _zid(tid, seed)
        rd_mid = argmax.get(zid, default_rd)
        short = _get_fork(fs, arm="msg", mid=SHORT_MID, d=0)
        long = _get_fork(fs, arm="msg", mid=LONG_MID, d=0)
        rd = _get_fork(fs, arm="msg", mid=rd_mid, d=0)
        take = _get_fork(fs, arm="takeover")
        diag = diags.get(zid) or {}
        dc = _diag_cost(diag)
        take_c = 0.0
        if take:
            take_c = float(take.get("guide_out") or take.get("cost") or 0)
            # prefer est from usage if present in cal takeovers — often small ints
        phi = make_phi(attempt=1, err=sn.get("err") or "")
        y0 = 1.0 if ctrl.get("success") else 0.0
        schemes = {}
        if short is not None:
            schemes["short"] = dict(
                y=1.0 if short["success"] else 0.0,
                cost=dc,
                mid=SHORT_MID,
            )
        if long is not None:
            schemes["long"] = dict(
                y=1.0 if long["success"] else 0.0,
                cost=dc,
                mid=LONG_MID,
            )
        if rd is not None:
            schemes["rd"] = dict(
                y=1.0 if rd["success"] else 0.0,
                cost=dc,
                mid=rd_mid,
            )
        if take is not None:
            schemes["takeover"] = dict(
                y=1.0 if take["success"] else 0.0,
                cost=take_c,
                mid=None,
            )
        rows.append(dict(
            tid=tid, seed=seed, zid=zid, phi=phi, y0=y0, schemes=schemes,
        ))
    return rows, default_rd


def fit_table(rows, task_allow, min_cell=3):
    """Empirical mean Δ, ΔC, ΔN by φ cell + pooled."""
    # collect lists
    cell = defaultdict(lambda: defaultdict(list))  # key -> q -> list of (d,dc,dn)
    pooled = defaultdict(list)
    for r in rows:
        if r["tid"] not in task_allow:
            continue
        key = _phi_key(r["phi"])
        for q, s in r["schemes"].items():
            d = s["y"] - r["y0"]
            dc = s["cost"] - 0.0
            dn = 1.0
            cell[key][q].append((d, dc, dn))
            pooled[q].append((d, dc, dn))

    def _mean_triples(xs):
        if not xs:
            return (0.0, 0.0, 0.0)
        return (
            st.mean(t[0] for t in xs),
            st.mean(t[1] for t in xs),
            st.mean(t[2] for t in xs),
        )

    table = {"pooled": {q: _mean_triples(xs) for q, xs in pooled.items()}}
    cell_n = {"pooled": sum(len(v) for v in pooled.values()) // max(len(pooled), 1)}
    for key, qmap in cell.items():
        table[key] = {q: _mean_triples(xs) for q, xs in qmap.items()}
        # n = number of prefixes in cell (use short count as proxy)
        cell_n[key] = max(len(xs) for xs in qmap.values()) if qmap else 0

    pred = TabularGainPredictor(table=table, min_cell=min_cell)
    pred.cell_n = cell_n
    return pred


def simulate_policy(rows, task_allow, predictor, candidates, lam, mu):
    succ, costs, picks = [], [], []
    for r in rows:
        if r["tid"] not in task_allow:
            continue
        dec = choose(r["phi"], candidates, predictor, lam=lam, mu=mu)
        q = dec["q_star"]
        picks.append(q)
        if q == "none":
            succ.append(r["y0"])
            costs.append(0.0)
        elif q in r["schemes"]:
            succ.append(r["schemes"][q]["y"])
            costs.append(r["schemes"][q]["cost"])
        else:
            succ.append(r["y0"])
            costs.append(0.0)
    return dict(
        n=len(succ),
        success=st.mean(succ) if succ else None,
        cost=st.mean(costs) if costs else None,
        pick_counts={q: picks.count(q) for q in sorted(set(picks))},
        request_rate=sum(1 for q in picks if q != "none") / len(picks) if picks else None,
    )


def select_lam_mu(rows, fit_tasks, hold_tasks, candidates=CAND_VD):
    pred = fit_table(rows, fit_tasks)
    best = None
    grid = []
    for lam in LAM_GRID:
        for mu in MU_GRID:
            hold = simulate_policy(rows, hold_tasks, pred, candidates, lam, mu)
            score = dict(lam=lam, mu=mu, **hold)
            grid.append(score)
            key = (
                hold["success"] if hold["success"] is not None else -1,
                -(hold["cost"] if hold["cost"] is not None else 1e9),
            )
            if best is None or key > best["key"]:
                best = dict(key=key, lam=lam, mu=mu, hold=hold, pred_fit=pred)
    return best, grid, pred


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cal = json.load(open(CAL_PATH))
    e_star = json.load(open(E_STAR_PATH))
    assert cal.get("meta", {}).get("prereg") == "v3-path-A"

    rows, default_rd = build_prefix_outcomes(cal, e_star)
    best, grid, pred_fit = select_lam_mu(rows, FIT_TASKS, HOLDOUT_TASKS, CAND_VD)
    lam, mu = best["lam"], best["mu"]

    # Refit predictor on ALL cal tasks; freeze lam/mu
    pred = fit_table(rows, CAL_TASKS)
    evals = {
        "G_fix": simulate_policy(rows, CAL_TASKS, pred, CAND_G_FIX, lam, mu),
        "G_fixL": simulate_policy(rows, CAL_TASKS, pred, CAND_G_FIXL, lam, mu),
        "VD_enc": simulate_policy(rows, CAL_TASKS, pred, CAND_VD_ENC, lam, mu),
        "VD": simulate_policy(rows, CAL_TASKS, pred, CAND_VD, lam, mu),
        "control": dict(
            n=len(rows),
            success=st.mean(r["y0"] for r in rows),
            cost=0.0,
        ),
    }
    # descriptive scheme rates on cal
    scheme_rates = {}
    for q in ("short", "long", "rd", "takeover"):
        ys = [r["schemes"][q]["y"] for r in rows if q in r["schemes"]]
        cs = [r["schemes"][q]["cost"] for r in rows if q in r["schemes"]]
        scheme_rates[q] = dict(
            success=st.mean(ys) if ys else None,
            cost=st.mean(cs) if cs else None,
            n=len(ys),
        )

    out = dict(
        meta=dict(
            source="results/calibration/cal.json",
            encoder="results/encoder/e_star.json",
            prereg="v3-path-A",
            short_mid=SHORT_MID,
            long_mid=LONG_MID,
            default_rd_mid=default_rd,
            fit_tasks=list(FIT_TASKS),
            holdout_tasks=list(HOLDOUT_TASKS),
            label="Delta_pi0_d0",
            cost_recipe="guide_est_output_tokens",
            fitted_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            underpowered_note="tabular on N=24; confirmatory 7 tasks underpowered",
        ),
        lam=lam,
        mu=mu,
        holdout_best=best["hold"],
        holdout_grid_top10=sorted(
            grid,
            key=lambda s: (-(s["success"] or -1), s["cost"] or 1e9),
        )[:10],
        cal_policy_eval=evals,
        scheme_rates_d0=scheme_rates,
        predictor=pred.to_jsonable(),
        pooled_row={q: list(v) for q, v in pred.table.get("pooled", {}).items()},
    )
    pred.save(os.path.join(OUT_DIR, "predictor.json"))
    # also store full fit artifact
    json.dump(out, open(os.path.join(OUT_DIR, "fit.json"), "w"), indent=2)

    lines = [
        "# TabularGainPredictor fit (path-A N=24)",
        "",
        f"- short={SHORT_MID}, long={LONG_MID}, rd-default={default_rd}",
        f"- fit tasks: {', '.join(FIT_TASKS)}",
        f"- holdout: {', '.join(HOLDOUT_TASKS)}",
        f"- selected λ={lam}, μ={mu}",
        f"- labels: Δ^{{π0}} at d=0; cost = guide est_output_tokens",
        "",
        "## Pooled Δ̂ (success − control, cost, n_proxy=1)",
        "",
    ]
    for q, trip in sorted((pred.table.get("pooled") or {}).items()):
        lines.append(f"- `{q}`: Δ={trip[0]:.3f}, ΔC={trip[1]:.1f}, ΔN={trip[2]:.1f}")
    lines += [
        "",
        "## Holdout VD policy",
        "",
        f"- success={best['hold']['success']:.3f}, cost={best['hold']['cost']:.1f}, "
        f"request_rate={best['hold']['request_rate']:.3f}, picks={best['hold']['pick_counts']}",
        "",
        "## Cal replay (descriptive, same prefixes used to fit — not confirmatory)",
        "",
    ]
    for arm, ev in evals.items():
        if arm == "control":
            lines.append(f"- {arm}: success={ev['success']:.3f}")
        else:
            lines.append(
                f"- {arm}: success={ev['success']:.3f}, cost={ev['cost']:.1f}, "
                f"request_rate={ev.get('request_rate')}, picks={ev.get('pick_counts')}"
            )
    lines += [
        "",
        "## Scheme d=0 rates",
        "",
    ]
    for q, r in scheme_rates.items():
        lines.append(f"- {q}: success={r['success']:.3f}, cost={r['cost']:.1f}, n={r['n']}")
    lines += [
        "",
        "## Paper notes",
        "",
        "1. Family short=m2 / long=m3 / drop m4 — mirrored in gate schemes.",
        "2. Thm1 risk: rd≈long on cal; confirmatory must ablate G_fixL vs VD.",
        "3. Real Δ̂ table (not stub). Cap/backoff: cell n < 3 → pooled.",
        "4. Confirmatory labelled underpowered (7 tasks).",
        "",
    ]
    open(os.path.join(OUT_DIR, "summary.md"), "w").write("\n".join(lines))
    print("WROTE", OUT_DIR)
    print("lam", lam, "mu", mu)
    print("pooled", pred.table.get("pooled"))
    print("hold", best["hold"])


if __name__ == "__main__":
    main()
