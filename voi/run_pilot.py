import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from voi.harness import *
from voi.executor import attempt
out = {}
P = os.path.join(R, "pilot.json")
def save(): json.dump(out, open(P, "w"), indent=1)
# Stage 1: difficulty filter
prev = json.load(open(P)) if os.path.exists(P) else {}
filt = prev.get("filter", {})
for t in T:
    if t["id"] in filt: continue
    filt[t["id"]] = [full_alone(t, s)["success"] for s in range(5)]
    print("filter", t["id"], filt[t["id"]], flush=True)
out["filter"] = filt
keep = [t for t in T if 1 <= sum(filt[t["id"]]) <= 4]
out["kept"] = [t["id"] for t in keep]; save()
print("kept", len(keep), flush=True)
# Stage 2: precheck guide alone on original buggy code
def pre(t):
    ok, err = visible_feedback(t["buggy"], t["visible"])
    r = guide.guidance("takeover", t["buggy"], t["visible"], err, ("pre", t["id"]))
    code = (r.get("obj") or {}).get("code") or ""
    return t["id"], run_tests(code + "\n", t["hidden"]), guide.cost(r)
with ThreadPoolExecutor(4) as ex: pres = list(ex.map(pre, keep))
g_rate = sum(p[1] for p in pres) / max(1, len(pres))
s_rate = sum(sum(filt[t["id"]]) for t in keep) / max(1, 5 * len(keep))
out["precheck"] = dict(guide_alone=g_rate, small_alone=s_rate, gap_pp=100 * (g_rate - s_rate), per_task=pres, passed=(g_rate - s_rate) >= 0.15); save()
print("precheck", out["precheck"]["gap_pp"], flush=True)
if not out["precheck"]["passed"]:
    out["verdict"] = "this pair unsuitable to test the question"; save(); sys.exit(0)
# Stage 3: snapshots
snaps = []
for t in keep:
    ok0, err0 = visible_feedback(t["buggy"], t["visible"]); s = 1000
    got = 0
    while got < 3 and s < 1040:
        code, _, _, dt = attempt(t["buggy"], t["visible"], err0, None, sd(("snap", t["id"], s), 1))
        ok, err = visible_feedback(code, t["visible"])
        if not ok: snaps.append(dict(tid=t["id"], seed=s, code=code, err=err, a1_s=dt)); got += 1
        s += 1
print("snapshots", len(snaps), flush=True)
TT = {t["id"]: t for t in T}
def gcalls(sn):
    t = TT[sn["tid"]]; key = (sn["tid"], sn["seed"])
    return {k: guide.guidance(k, sn["code"], t["visible"], sn["err"], key) for k in ("short", "long", "takeover")}
with ThreadPoolExecutor(4) as ex: G = list(ex.map(gcalls, snaps))
# Stage 4: forks
forks = []
for sn, g in zip(snaps, G):
    t = TT[sn["tid"]]; key = ("fork", sn["tid"], sn["seed"])
    base = dict(tid=sn["tid"], seed=sn["seed"])
    r = loop(t, sn["code"], sn["err"], 2, key); forks.append(dict(base, arm="A0", d=None, cost=0, **r))
    tc = (g["takeover"].get("obj") or {}).get("code") or ""
    forks.append(dict(base, arm="A1", d=None, cost=guide.cost(g["takeover"]), success=run_tests(tc + "\n", t["hidden"]),
                      exec_s=sn["a1_s"], wall=sn["a1_s"] + g["takeover"]["latency"], status="takeover", gen_tokens=0))
    for arm, kind in (("A2", "short"), ("A3", "long")):
        rec = g[kind]; txt = guide.render(rec); ai = (rec.get("obj") or {}).get("applicable_if")
        for d in (0, 1, 2):
            r = loop(t, sn["code"], sn["err"], 2, key, g=(txt, ai), deliver_at=2 + d, L=rec["latency"])
            forks.append(dict(base, arm=arm, d=d, cost=guide.cost(rec), out_tokens=(rec.get("usage") or {}).get("output_tokens"), **r))
    out["forks"] = forks; save()
    print("fork", sn["tid"], sn["seed"], flush=True)
out["guide_records"] = G; save()
print("DONE", flush=True)
