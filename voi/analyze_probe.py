"""Summarize signal probe: control vs m1–m4 success, output tokens, Q1-style lift."""
import json, os, statistics as st
from collections import defaultdict

R = os.path.join(os.path.dirname(__file__), "..", "results", "probe")
D = json.load(open(os.path.join(R, "probe.json")))
F = D["forks"]

def arm_key(f):
    return "control" if f["arm"] == "control" else f["mid"]

by = defaultdict(list)
for f in F:
    by[arm_key(f)].append(f)

rep = dict(n_snapshots=len({(f["tid"], f["seed"]) for f in F}),
           n_forks=len(F), arms={}, Q1={})
for a in ("control", "m1", "m2", "m3", "m4"):
    c = by.get(a) or []
    if not c:
        continue
    outs = [f.get("guide_out") or 0 for f in c]
    msgs = [f.get("message_cost") or 0 for f in c]
    rep["arms"][a] = dict(
        n=len(c),
        success_rate=sum(f["success"] for f in c) / len(c),
        n_success=sum(f["success"] for f in c),
        guide_out_mean=st.mean(outs) if outs else 0,
        message_cost_mean=st.mean(msgs) if msgs else 0,
        accepted=sum(f["status"] == "accepted" for f in c),
        stale=sum(f["status"] == "stale" for f in c),
        render_fail=sum(f["status"] == "render_fail" for f in c),
    )

# Paired lift vs control by snapshot
ctrl = {(f["tid"], f["seed"]): f["success"] for f in by["control"]}
for a in ("m1", "m2", "m3", "m4"):
    lifts = []
    for f in by.get(a) or []:
        k = (f["tid"], f["seed"])
        if k in ctrl:
            lifts.append(float(f["success"]) - float(ctrl[k]))
    if lifts:
        rep["Q1"][a] = dict(
            mean_lift_pp=100 * st.mean(lifts),
            n_better=sum(x > 0 for x in lifts),
            n_worse=sum(x < 0 for x in lifts),
            n_tie=sum(x == 0 for x in lifts),
            any_positive_lift=st.mean(lifts) > 0,
        )

best = max(
    ((a, rep["arms"][a]["success_rate"]) for a in ("m1", "m2", "m3", "m4") if a in rep["arms"]),
    key=lambda x: x[1], default=(None, 0),
)
ctrl_r = rep["arms"].get("control", {}).get("success_rate", 0)
rep["signal"] = dict(
    control_success=ctrl_r,
    best_mid=best[0],
    best_success=best[1],
    best_lift_pp=100 * (best[1] - ctrl_r),
    q1_style_lift_exists=best[1] > ctrl_r,
)

json.dump(rep, open(os.path.join(R, "probe_summary.json"), "w"), indent=1)

# Markdown
lines = [
    "# Signal probe summary (v3)",
    "",
    f"- Snapshots: {rep['n_snapshots']}; forks: {rep['n_forks']}; d=0 only.",
    f"- Q1-style lift exists: **{rep['signal']['q1_style_lift_exists']}** "
    f"(best {rep['signal']['best_mid']} {rep['signal']['best_success']:.0%} vs control {ctrl_r:.0%}, "
    f"lift {rep['signal']['best_lift_pp']:+.1f} pp).",
    "",
    "| arm | n | success | guide_out mean | message_cost mean | accepted | stale |",
    "|---|---:|---:|---:|---:|---:|---:|",
]
for a in ("control", "m1", "m2", "m3", "m4"):
    if a not in rep["arms"]:
        continue
    x = rep["arms"][a]
    lines.append(
        f"| {a} | {x['n']} | {x['success_rate']:.1%} | {x['guide_out_mean']:.0f} | "
        f"{x['message_cost_mean']:.1f} | {x['accepted']} | {x['stale']} |"
    )
lines += ["", "## Paired lift vs control", ""]
for a, q in rep["Q1"].items():
    lines.append(f"- {a}: mean lift {q['mean_lift_pp']:+.1f} pp "
                 f"(better {q['n_better']} / worse {q['n_worse']} / tie {q['n_tie']})")
lines += [
    "",
    "Footnote: `guide_out` is diagnosis-call output (shared across m on a prefix); "
    "`message_cost` is post-encode est_tokens of rendered m (encoder-differentiating c).",
    "",
    "Probe is directional only; do not expand to full cal if no Q1-style lift.",
]
open(os.path.join(R, "probe_summary.md"), "w").write("\n".join(lines) + "\n")
print(json.dumps(rep, indent=1))
