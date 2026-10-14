"""Offline Theorem-1 encoder fit on path-A N=24 calibration forks.

Estimates d̂_h(z,m), ĉ_h(z,m) (message-side est_tokens), solves e* via
Blahut–Arimoto (eqs. 7–9). Nested holdout within the 8 cal tasks chooses
family (with/without m4) and (λ, β). Short class frozen to m2 (not m1).

Writes results/encoder/{tables.json,e_star.json,summary.md}.
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
import time
from collections import defaultdict

from voi import messages
from voi.encoder import blahut_arimoto

# Keep in sync with voi.calibration.CAL_TASKS (avoid importing executor/torch).
CAL_TASKS = ["T09", "T10", "T11", "T12", "T14", "T17", "T20", "T26"]

CAL_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "calibration", "cal.json")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "encoder")

# Nested holdout: last 2 cal tasks (fixed before seeing fit metrics used for selection).
# Fit on the other 6. Documented in DEVIATIONS / summary.
HOLDOUT_TASKS = ("T20", "T26")
FIT_TASKS = tuple(t for t in CAL_TASKS if t not in HOLDOUT_TASKS)

FAMILY_FULL = ("m1", "m2", "m3", "m4")
FAMILY_NO_M4 = ("m1", "m2", "m3")
# Deploy default after holdout (may be overridden by selection):
SHORT_DEFAULT = "m2"
LONG_DEFAULT = "m3"

LAM_GRID = (0.0, 0.001, 0.005, 0.01, 0.02, 0.05)
BETA_GRID = (0.05, 0.1, 0.2, 0.5, 1.0)
N_ITER = 80


def _z_id(tid, seed):
    return f"{tid}:{seed}"


def load_cal(path=CAL_PATH):
    return json.load(open(path))


def build_prefix_tables(cal, mids, delays=(0, 1, 2)):
    """Per-prefix empirical v(z,m,d), c(z,m), and decision distortion d(z,m,d).

    S=1 CRN forks → v̂ is the Bernoulli outcome. d̂ = max_{m'} v̂ - v̂.
    ĉ = post-encode message_cost (est_tokens); shared across delays.
    """
    forks = cal["forks"]
    diags = cal["diagnoses"]
    # success[z][d][mid], cost[z][mid]
    succ = defaultdict(lambda: defaultdict(dict))
    cost = {}
    meta = {}
    for f in forks:
        if f.get("arm") != "msg":
            continue
        mid = f.get("mid")
        if mid not in mids:
            continue
        zid = _z_id(f["tid"], f["seed"])
        d = f.get("d")
        if d not in delays:
            continue
        succ[zid][d][mid] = 1.0 if f.get("success") else 0.0
        if zid not in cost:
            cost[zid] = {}
        # message_cost identical across d for same mid; take first non-null
        if mid not in cost[zid] and f.get("message_cost") is not None:
            cost[zid][mid] = float(f["message_cost"])
        meta[zid] = dict(tid=f["tid"], seed=f["seed"])

    # fill costs from diagnosis render if missing
    for zid, m in meta.items():
        rec = diags.get(zid) or {}
        z = rec.get("obj") or {}
        for mid in mids:
            if mid not in cost.get(zid, {}):
                c = messages.message_cost(z, mid)
                cost.setdefault(zid, {})[mid] = float(c) if c is not None else 0.0

    # distortion per (z, d)
    d_hat = defaultdict(lambda: defaultdict(dict))  # d_hat[delay][zid][mid]
    v_hat = defaultdict(lambda: defaultdict(dict))
    for zid in succ:
        for d in delays:
            row = succ[zid].get(d) or {}
            if not row:
                continue
            vals = [row.get(m, 0.0) for m in mids if m in row]
            if not vals:
                continue
            vmax = max(vals)
            for mid in mids:
                if mid not in row:
                    continue
                v = row[mid]
                v_hat[d][zid][mid] = v
                d_hat[d][zid][mid] = vmax - v

    # delay-pooled: mean success across delays, then distortion
    d_pooled = {}
    v_pooled = {}
    for zid in succ:
        v_pooled[zid] = {}
        means = []
        for mid in mids:
            xs = [succ[zid][d][mid] for d in delays if mid in succ[zid].get(d, {})]
            if not xs:
                continue
            v_pooled[zid][mid] = sum(xs) / len(xs)
            means.append(v_pooled[zid][mid])
        if not means:
            continue
        vmax = max(means)
        d_pooled[zid] = {mid: vmax - v_pooled[zid][mid] for mid in v_pooled[zid]}

    return dict(
        d_by_delay={str(d): dict(d_hat[d]) for d in delays},
        v_by_delay={str(d): dict(v_hat[d]) for d in delays},
        d_pooled=d_pooled,
        v_pooled=v_pooled,
        c=cost,
        meta=meta,
        mids=list(mids),
        delays=list(delays),
    )


def _subset_p_z(meta, task_allow):
    zs = [zid for zid, m in meta.items() if m["tid"] in task_allow]
    if not zs:
        return {}
    p = 1.0 / len(zs)
    return {z: p for z in zs}


def _slice_dc(d_table, c_table, zs, mids):
    d = {z: {m: d_table[z][m] for m in mids if m in d_table.get(z, {})} for z in zs if z in d_table}
    c = {z: {m: c_table[z][m] for m in mids if m in c_table.get(z, {})} for z in zs if z in c_table}
    # drop z missing any mid
    keep = [z for z in d if all(m in d[z] and m in c.get(z, {}) for m in mids)]
    return {z: d[z] for z in keep}, {z: c[z] for z in keep}


def evaluate_argmax(e, v_table, c_table, zs, mids):
    """Argmax_m e(m|z) then mean success / cost on those z."""
    succ, costs, picks = [], [], []
    for z in zs:
        row = e.get(z) or {}
        if not row:
            continue
        mid = max(mids, key=lambda m: row.get(m, -1.0))
        picks.append(mid)
        if z in v_table and mid in v_table[z]:
            succ.append(v_table[z][mid])
        if z in c_table and mid in c_table[z]:
            costs.append(c_table[z][mid])
    return dict(
        n=len(succ),
        success_mean=st.mean(succ) if succ else None,
        cost_mean=st.mean(costs) if costs else None,
        pick_counts={m: picks.count(m) for m in mids},
    )


def evaluate_fixed(mid, v_table, c_table, zs):
    succ = [v_table[z][mid] for z in zs if mid in v_table.get(z, {})]
    costs = [c_table[z][mid] for z in zs if mid in c_table.get(z, {})]
    return dict(
        n=len(succ),
        success_mean=st.mean(succ) if succ else None,
        cost_mean=st.mean(costs) if costs else None,
        mid=mid,
    )


def sweep_and_select(tables, fit_tasks, hold_tasks, mids, lam_grid=LAM_GRID, beta_grid=BETA_GRID):
    """Fit on fit_tasks (pooled delay), score on hold_tasks; return best (λ,β,e,q)."""
    meta = tables["meta"]
    p_fit = _subset_p_z(meta, fit_tasks)
    p_hold = _subset_p_z(meta, hold_tasks)
    d_fit, c_fit = _slice_dc(tables["d_pooled"], tables["c"], list(p_fit), mids)
    d_hold, c_hold = _slice_dc(tables["d_pooled"], tables["c"], list(p_hold), mids)
    v_hold = {z: tables["v_pooled"][z] for z in d_hold}
    p_fit = {z: 1.0 / len(d_fit) for z in d_fit}

    best = None
    grid = []
    for lam in lam_grid:
        for beta in beta_grid:
            e, q, hist = blahut_arimoto(d_fit, c_fit, p_fit, lam, beta, n_iter=N_ITER, mids=mids)
            # map e onto hold z via nearest: each hold z has its own row only if in fit —
            # hold z are disjoint, so deploy uses **pooled q + cost-sensitive score** on hold
            # using train-fitted (d,c) structure: for unseen z, use argmin_m d̂? We don't have
            # d for hold at train time in deploy. Nested selection uses hold *oracle v* only
            # to score a policy that for each hold z picks argmax_m e_train-style via
            # minimizing d_hold+λc (oracle tables) would leak. Correct approach:
            # For hold prefixes we DO have empirical forks (cal data); selection of hyperparams
            # may use hold fork outcomes. The encoder e is fit on train z only; for hold z,
            # apply the **cost-sensitive rule** mid* = argmin_m [0 + λ c(z,m)] among m that
            # achieve max train-pooled success? Simpler prereg-faithful:
            # Deploy decode = ArgmaxEncoder on e(m|z). For z not in train table, fall back to
            # pooled marginal q, or argmin λc + expected d from train mid ranking.
            #
            # Practical nested score used here:
            # 1) Train BA → e_train(z,m) for train z.
            # 2) Induce mid ranking by mean e / mean (d+λc) on train → fixed preference order.
            # 3) On hold, pick mid = argmin_m (d̄_train(m) + λ c_hold(z,m)) where d̄_train is
            #    mean distortion of mid on train (context-free length prior from RD fit).
            dbar = {m: st.mean([d_fit[z][m] for z in d_fit]) for m in mids}
            picks = []
            succ = []
            costs = []
            for z in d_hold:
                mid = min(mids, key=lambda m: dbar[m] + lam * c_hold[z][m])
                picks.append(mid)
                succ.append(v_hold[z][mid])
                costs.append(c_hold[z][mid])
            # also report train objective final F
            F = hist[-1] if hist else None
            score = dict(
                lam=lam, beta=beta, F_train=F,
                hold_success=st.mean(succ) if succ else None,
                hold_cost=st.mean(costs) if costs else None,
                hold_picks={m: picks.count(m) for m in mids},
                q={m: q[m] for m in mids},
            )
            grid.append(score)
            # selection: maximize hold_success, then minimize hold_cost, then smaller F
            key = (
                score["hold_success"] if score["hold_success"] is not None else -1,
                -(score["hold_cost"] if score["hold_cost"] is not None else 1e9),
                -(F if F is not None else 1e9),
            )
            if best is None or key > best["key"]:
                best = dict(key=key, lam=lam, beta=beta, e=e, q=q, hist=hist, score=score,
                            dbar=dbar, d_fit=d_fit, c_fit=c_fit, p_fit=p_fit)

    return best, grid


def fit_delay_conditional(tables, tasks, mids, lam, beta):
    """Per-delay BA tables (Theorem-2: length vs delay)."""
    out = {}
    meta = tables["meta"]
    p_all = _subset_p_z(meta, tasks)
    for d_str, d_table in tables["d_by_delay"].items():
        d_s, c_s = _slice_dc(d_table, tables["c"], list(p_all), mids)
        if not d_s:
            continue
        p = {z: 1.0 / len(d_s) for z in d_s}
        e, q, hist = blahut_arimoto(d_s, c_s, p, lam, beta, n_iter=N_ITER, mids=mids)
        # argmax picks distribution
        picks = []
        for z in e:
            picks.append(max(mids, key=lambda m: e[z].get(m, -1.0)))
        out[d_str] = dict(
            q={m: q[m] for m in mids},
            F=hist[-1] if hist else None,
            argmax_counts={m: picks.count(m) for m in mids},
            n_z=len(e),
            # store e sparsely: argmax only for size
            argmax={z: max(mids, key=lambda m: e[z].get(m, -1.0)) for z in e},
        )
    return out


def mean_v_c_by_mid(tables, tasks, mids):
    zs = [z for z, m in tables["meta"].items() if m["tid"] in tasks]
    rows = []
    for mid in mids:
        vs = [tables["v_pooled"][z][mid] for z in zs if mid in tables["v_pooled"].get(z, {})]
        cs = [tables["c"][z][mid] for z in zs if mid in tables["c"].get(z, {})]
        by_d = {}
        for d_str, vtab in tables["v_by_delay"].items():
            xs = [vtab[z][mid] for z in zs if mid in vtab.get(z, {})]
            by_d[d_str] = st.mean(xs) if xs else None
        rows.append(dict(
            mid=mid,
            success_pooled=st.mean(vs) if vs else None,
            cost_mean=st.mean(cs) if cs else None,
            success_by_delay=by_d,
            n=len(vs),
        ))
    return rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cal = load_cal()
    assert cal.get("meta", {}).get("prereg") == "v3-path-A"

    # Build tables for both families
    tables_full = build_prefix_tables(cal, FAMILY_FULL)
    tables_no = build_prefix_tables(cal, FAMILY_NO_M4)

    sel_full, grid_full = sweep_and_select(tables_full, FIT_TASKS, HOLDOUT_TASKS, FAMILY_FULL)
    sel_no, grid_no = sweep_and_select(tables_no, FIT_TASKS, HOLDOUT_TASKS, FAMILY_NO_M4)

    # Family decision (paper-side + holdout): prefer no-m4 if hold success not worse by >1pp
    # and cost lower; else keep full but mark m4 cost-redundant if tied.
    hs_full = sel_full["score"]["hold_success"]
    hs_no = sel_no["score"]["hold_success"]
    hc_full = sel_full["score"]["hold_cost"]
    hc_no = sel_no["score"]["hold_cost"]
    drop_m4 = (hs_no is not None and hs_full is not None
               and hs_no + 1e-9 >= hs_full - 0.01
               and (hc_no is None or hc_full is None or hc_no <= hc_full + 1e-9))

    chosen = sel_no if drop_m4 else sel_full
    chosen_mids = list(FAMILY_NO_M4 if drop_m4 else FAMILY_FULL)
    chosen_tables = tables_no if drop_m4 else tables_full

    # Refit e* on ALL cal tasks with chosen (λ,β,family) — freeze for confirmatory
    meta = chosen_tables["meta"]
    p_all = _subset_p_z(meta, CAL_TASKS)
    d_all, c_all = _slice_dc(chosen_tables["d_pooled"], chosen_tables["c"], list(p_all), chosen_mids)
    p_all = {z: 1.0 / len(d_all) for z in d_all}
    lam, beta = chosen["lam"], chosen["beta"]
    e_star, q_star, hist = blahut_arimoto(
        d_all, c_all, p_all, lam, beta, n_iter=N_ITER, mids=chosen_mids,
    )
    argmax = {z: max(chosen_mids, key=lambda m: e_star[z].get(m, -1.0)) for z in e_star}

    delay_cond = fit_delay_conditional(chosen_tables, CAL_TASKS, chosen_mids, lam, beta)

    # Fixed-length baselines for ablation reference (cal descriptive)
    fixed = {
        "m1": evaluate_fixed("m1", chosen_tables["v_pooled"], chosen_tables["c"], list(p_all)),
        "m2": evaluate_fixed("m2", chosen_tables["v_pooled"], chosen_tables["c"], list(p_all)),
        "m3": evaluate_fixed("m3", chosen_tables["v_pooled"], chosen_tables["c"], list(p_all)),
    }
    if "m4" in FAMILY_FULL:
        # always report m4 descriptive even if dropped
        tfull = tables_full
        pall_f = _subset_p_z(tfull["meta"], CAL_TASKS)
        fixed["m4"] = evaluate_fixed("m4", tfull["v_pooled"], tfull["c"], list(pall_f))

    enc_eval = evaluate_argmax(e_star, chosen_tables["v_pooled"], chosen_tables["c"], list(p_all), chosen_mids)

    # Short/long class freeze
    short_id = SHORT_DEFAULT  # m2
    long_id = LONG_DEFAULT    # m3

    rate_table = mean_v_c_by_mid(tables_full, CAL_TASKS, FAMILY_FULL)

    tables_out = dict(
        meta=dict(
            source="results/calibration/cal.json",
            prereg="v3-path-A",
            guide_model=cal["meta"].get("guide_model"),
            fit_tasks=list(FIT_TASKS),
            holdout_tasks=list(HOLDOUT_TASKS),
            cost_recipe="est_tokens",
            distortion="decision_eq5_S1",
            h_buckets="pooled_delay + per_delay={0,1,2}; attempt=1 almost all assert",
            short_class=short_id,
            long_class=long_id,
            family_default=chosen_mids,
            drop_m4=drop_m4,
            fitted_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        ),
        rate_distortion_descriptive=rate_table,
        c_hat=chosen_tables["c"],
        d_pooled=chosen_tables["d_pooled"],
        d_by_delay=chosen_tables["d_by_delay"],
        v_pooled=chosen_tables["v_pooled"],
        v_by_delay=chosen_tables["v_by_delay"],
        holdout_comparison=dict(
            family_full=dict(
                mids=list(FAMILY_FULL),
                best=sel_full["score"],
                grid_top5=sorted(grid_full, key=lambda s: (-(s["hold_success"] or -1), s["hold_cost"] or 1e9))[:5],
            ),
            family_no_m4=dict(
                mids=list(FAMILY_NO_M4),
                best=sel_no["score"],
                grid_top5=sorted(grid_no, key=lambda s: (-(s["hold_success"] or -1), s["hold_cost"] or 1e9))[:5],
            ),
            decision="drop_m4" if drop_m4 else "keep_m4",
            reason=(
                "holdout success of no-m4 ≥ full−1pp and cost ≤ full; m3≡m4 on cal rates"
                if drop_m4 else
                "holdout favored full family"
            ),
        ),
    )

    e_out = dict(
        meta=tables_out["meta"],
        lam=lam,
        beta=beta,
        mids=chosen_mids,
        q_star=q_star,
        F_hist_tail=hist[-5:] if hist else [],
        F_final=hist[-1] if hist else None,
        e_star=e_star,
        argmax_by_z=argmax,
        argmax_counts={m: sum(1 for x in argmax.values() if x == m) for m in chosen_mids},
        delay_conditional=delay_cond,
        cal_eval_argmax=enc_eval,
        fixed_length_baselines=fixed,
        deploy=dict(
            rule="one diagnosis z → ArgmaxEncoder(e_star) or cost-sensitive argmin dbar+λc for unseen z",
            short_template=short_id,
            long_template=long_id,
            default_family=chosen_mids,
            verification_in_default=False if drop_m4 else True,
        ),
    )

    json.dump(tables_out, open(os.path.join(OUT_DIR, "tables.json"), "w"), indent=2)
    json.dump(e_out, open(os.path.join(OUT_DIR, "e_star.json"), "w"), indent=2)

    # Markdown summary
    lines = [
        "# Theorem-1 offline encoder fit (path-A N=24)",
        "",
        f"- source: `results/calibration/cal.json` (commit lineage after `53cf6b1`)",
        f"- fit tasks: {', '.join(FIT_TASKS)}",
        f"- nested holdout tasks: {', '.join(HOLDOUT_TASKS)}",
        f"- cost: post-encode est_tokens chat (not diagnosis baseline)",
        f"- distortion d-hat: eq.5 with S=1 CRN forks; pooled over d in {{0,1,2}} for primary e*; per-delay tables for Thm-2",
        f"- short class: **{short_id}** (not m1 — cal m1≈control)",
        f"- long class: **{long_id}**",
        f"- default family: `{chosen_mids}` — **{'m4 dropped from default encode family' if drop_m4 else 'm4 retained'}**",
        f"- selected λ={lam}, β={beta}",
        "",
        "## Descriptive success × cost (all 24 prefixes, pooled delay)",
        "",
        "| mid | success | cost (est_tok) | d=0 | d=1 | d=2 |",
        "|-----|---------|----------------|-----|-----|-----|",
    ]
    for r in rate_table:
        bd = r["success_by_delay"]
        lines.append(
            f"| {r['mid']} | {r['success_pooled']:.3f} | {r['cost_mean']:.1f} | "
            f"{bd.get('0'):.3f} | {bd.get('1'):.3f} | {bd.get('2'):.3f} |"
        )
    lines += [
        "",
        "## Nested holdout family choice",
        "",
        f"| family | hold success | hold cost | λ | β |",
        f"|--------|--------------|-----------|---|---|",
        f"| m1–m4 | {hs_full:.3f} | {hc_full:.1f} | {sel_full['lam']} | {sel_full['beta']} |",
        f"| m1–m3 (no m4) | {hs_no:.3f} | {hc_no:.1f} | {sel_no['lam']} | {sel_no['beta']} |",
        f"",
        f"**Decision:** `{tables_out['holdout_comparison']['decision']}` — {tables_out['holdout_comparison']['reason']}",
        "",
        "## Frozen e* (all cal tasks)",
        "",
        f"- q*: " + ", ".join(f"{m}={q_star[m]:.3f}" for m in chosen_mids),
        f"- argmax counts: {e_out['argmax_counts']}",
        f"- argmax policy on cal (pooled): success={enc_eval['success_mean']:.3f}, cost={enc_eval['cost_mean']:.1f}",
        f"- fixed m2: success={fixed['m2']['success_mean']:.3f}, cost={fixed['m2']['cost_mean']:.1f}",
        f"- fixed m3: success={fixed['m3']['success_mean']:.3f}, cost={fixed['m3']['cost_mean']:.1f}",
        f"- fixed m1: success={fixed['m1']['success_mean']:.3f}, cost={fixed['m1']['cost_mean']:.1f}",
        f"- fixed m4: success={fixed['m4']['success_mean']:.3f}, cost={fixed['m4']['cost_mean']:.1f}",
        "",
        "## Delay-conditional argmax (Theorem-2 direction)",
        "",
        "| delay | argmax counts | q* |",
        "|-------|---------------|----|",
    ]
    for d_str in sorted(delay_cond.keys(), key=int):
        dc = delay_cond[d_str]
        lines.append(
            f"| {d_str} | {dc['argmax_counts']} | "
            + ", ".join(f"{m}={dc['q'][m]:.2f}" for m in chosen_mids)
            + " |"
        )
    lines += [
        "",
        "## Paper-side notes reflected",
        "",
        "1. Main gain at m3; m4 verification dropped from default family (or would be cost-redundant).",
        "2. m3 delay gradient 0.833→0.792→0.708 supports length–delay narrowing; primary logistic still confirmatory.",
        "3. stale=16 (~8% of delayed deliveries) retained as mechanism contribution (see cal_summary).",
        "4. Short arm = **m2** (m1≈control).",
        "5. Capability gap passed → confirmatory path (not exploratory downgrade).",
        "",
        "## Confirmatory readiness",
        "",
        "- Encoder artifacts frozen under `results/encoder/`.",
        "- No confirmatory runner in repo yet; gate `TabularGainPredictor` still stub — **do not start confirmatory** until gate fit + runner exist and Heath okays.",
        "",
    ]
    open(os.path.join(OUT_DIR, "summary.md"), "w").write("\n".join(lines))
    print("WROTE", OUT_DIR)
    print("drop_m4", drop_m4, "lam", lam, "beta", beta)
    print("argmax_counts", e_out["argmax_counts"])
    print("hold", "full", hs_full, hc_full, "no_m4", hs_no, hc_no)


if __name__ == "__main__":
    main()
