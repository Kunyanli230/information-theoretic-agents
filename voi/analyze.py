import json, os, random, statistics as st
R = os.path.join(os.path.dirname(__file__), "..", "results"); D = json.load(open(os.path.join(R, "pilot.json")))
F = D["forks"]; random.seed(0)
def cell(arm, d="any"): return [f for f in F if f["arm"] == arm and (d == "any" or f["d"] == d)]
rep = {"precheck": D["precheck"], "kept": D["kept"], "n_snapshots": len({(f["tid"], f["seed"]) for f in F}), "arms": {}}
for arm, ds in (("A0", [None]), ("A1", [None]), ("A2", [0, 1, 2, "any"]), ("A3", [0, 1, 2, "any"])):
    for d in ds:
        c = cell(arm, d) if d is not None else cell(arm)
        if not c: continue
        dl = [f for f in c if f["status"] in ("accepted", "stale")]
        rep["arms"][f"{arm}" + ("" if d is None else f"_d{d}")] = dict(n=len(c), success=sum(f["success"] for f in c) / len(c),
            guide_tokens_mean=st.mean(f["cost"] for f in c), wall_mean_s=st.mean(f["wall"] for f in c),
            accepted=sum(f["status"] == "accepted" for f in c), stale=sum(f["status"] == "stale" for f in c),
            not_needed=sum(f["status"] == "not_needed" for f in c))
# paired by snapshot, bootstrap over tasks
def per_snap(arm, d="any"):
    m = {}
    for f in cell(arm, d): m.setdefault((f["tid"], f["seed"]), []).append(f)
    return {k: (st.mean(x["success"] for x in v), st.mean(x["cost"] for x in v)) for k, v in m.items()}
tasks = sorted({f["tid"] for f in F})
def boot(fn, B=10000):
    xs = []
    for _ in range(B):
        ts = [random.choice(tasks) for _ in tasks]; xs.append(fn(ts))
    xs.sort(); return xs[int(.05 * B)], xs[int(.95 * B)]
P = {a: per_snap(a) for a in ("A0", "A1", "A2", "A3")}
def diff(a, b): return lambda ts: st.mean(P[a][k][0] - P[b][k][0] for t in ts for k in P[a] if k[0] == t)
def mean_succ(a): return st.mean(v[0] for v in P[a].values())
B = max(("A0", "A1"), key=lambda a: (mean_succ(a), -st.mean(v[1] for v in P[a].values())))
if abs(mean_succ("A0") - mean_succ("A1")) <= 0.01: B = "A0"
G = max(("A2", "A3"), key=lambda a: (mean_succ(a), -st.mean(v[1] for v in P[a].values())))
costB = st.mean(v[1] for v in P["A1"].values()); costG = st.mean(v[1] for v in P[G].values())
rep["gate"] = dict(strongest_baseline=B, best_guidance=G, succ_G_minus_B=mean_succ(G) - mean_succ(B), ci90_G_minus_B=boot(diff(G, B)),
    saving_vs_takeover=1 - costG / costB, Q1_G_minus_A0=mean_succ(G) - mean_succ("A0"), Q1_ci90=boot(diff(G, "A0")),
    Q1_A2_minus_A0_ci90=boot(diff("A2", "A0")), Q1_A3_minus_A0_ci90=boot(diff("A3", "A0")))
# Q2: (A3-A2) by delay
q2 = {}
for d in (0, 1, 2):
    a = per_snap("A3", d); b = per_snap("A2", d); q2[d] = st.mean(a[k][0] - b[k][0] for k in a)
def slope(ts):
    v = []
    for d in (0, 1, 2):
        a = per_snap("A3", d); b = per_snap("A2", d); v.append(st.mean(a[k][0] - b[k][0] for t in ts for k in a if k[0] == t))
    return (v[2] - v[0]) / 2
rep["Q2"] = dict(A3_minus_A2_by_delay=q2, slope=(q2[2] - q2[0]) / 2, slope_ci90=boot(slope, 3000))
dl = [f for f in F if f["arm"] in ("A2", "A3") and f["d"] and f["status"] in ("accepted", "stale")]
rep["stale_rate_delayed"] = sum(f["status"] == "stale" for f in dl) / max(1, len(dl)); rep["n_delayed_delivered_or_stale"] = len(dl)
d = [f["seed"] for f in F if f["arm"] == "A0"]
sd = [P[G][k][0] - P[B][k][0] for k in P[G]]; rep["sigma_d2"] = st.pvariance(sd)
rep["n_main_needed"] = round(6.18 * rep["sigma_d2"] / 0.0025)
json.dump(rep, open(os.path.join(R, "pilot_summary.json"), "w"), indent=1, default=str); print(json.dumps(rep, indent=1, default=str))
