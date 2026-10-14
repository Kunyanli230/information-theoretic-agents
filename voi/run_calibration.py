"""Full N=24 path-A calibration (prereg §4): 8 cal tasks × 3 snaps.

Fresh Cursor CLI / grok-4.6 diagnosis per prefix; control + m1–m4 × d∈{0,1,2}
(+ optional takeover). Resumable. Does not mix Codex caches (model-keyed).
"""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from voi.calibration import (
    CAL_TASKS, make_snapshots, diagnose, cal_forks_for_snapshot,
)
from voi.encoder import FactorialEncoder
from voi import guide

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "calibration")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "cal.json")


def load():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {}


def save(state):
    json.dump(state, open(OUT, "w"), indent=1)


def main():
    state = load()
    state.setdefault("meta", dict(
        prereg="v3-path-A",
        N=24, n_per_task=3, delays=[0, 1, 2],
        arms=["control", "m1", "m2", "m3", "m4", "takeover"],
        cal_tasks=CAL_TASKS,
        guide_model=guide.MODEL,
        guide_backend="cursor-cli-agent",
        agent_version="2026.10.01-e373342",
        capability_gap=dict(
            guide_alone=1.0, small_alone=0.56, gap_pp=44.0, passed=True,
            source="results/capability_gap_grok46.json",
        ),
        started=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    ))
    save(state)

    if "snapshots" not in state:
        print("building N=24 snapshots (3 attempt-1-fail / cal task)...", flush=True)
        snaps = make_snapshots(CAL_TASKS, n_per_task=3, seed0=1000)
        state["snapshots"] = snaps
        save(state)
        print("snapshots", len(snaps), [(s["tid"], s["seed"]) for s in snaps], flush=True)
    else:
        snaps = state["snapshots"]
        print("resume snapshots", len(snaps), flush=True)

    # Fresh diagnoses (serial; cache keyed by model — no Codex reuse)
    diags = state.get("diagnoses") or {}
    need = []
    for sn in snaps:
        k = f"{sn['tid']}:{sn['seed']}"
        v = diags.get(k) or {}
        ok = (
            v.get("obj")
            and not v.get("seeded_from")
            and v.get("model") == guide.MODEL
        )
        if not ok:
            need.append(sn)

    if need:
        print(f"fresh diagnosis for {len(need)}/{len(snaps)} prefixes...", flush=True)
        for sn in need:
            rec = diagnose(sn)
            k = f"{sn['tid']}:{sn['seed']}"
            v = {
                "obj": rec.get("obj"), "usage": rec.get("usage"),
                "latency": rec.get("latency"), "error": rec.get("error"),
                "text": rec.get("text"), "model": rec.get("model"),
                "backend": rec.get("backend"),
                "seeded_from": rec.get("seeded_from"),
            }
            diags[k] = v
            state["diagnoses"] = diags
            save(state)
            print("diag", k, "OK" if v.get("obj") else "FAIL",
                  f"L={v.get('latency')}", flush=True)
            if not v.get("obj"):
                print("BLOCKER: diagnosis failed; retry once", flush=True)
                # bust cache file if empty/fail
                from voi.tasks import T
                TT = {t["id"]: t for t in T}
                t = TT[sn["tid"]]
                fp = guide.cache_path("diagnosis", (sn["tid"], sn["seed"]), sn["code"])
                if os.path.exists(fp):
                    try:
                        old = json.load(open(fp))
                        if not old.get("obj"):
                            os.remove(fp)
                    except Exception:
                        pass
                rec = diagnose(sn)
                v = {
                    "obj": rec.get("obj"), "usage": rec.get("usage"),
                    "latency": rec.get("latency"), "error": rec.get("error"),
                    "text": rec.get("text"), "model": rec.get("model"),
                    "backend": rec.get("backend"),
                    "seeded_from": rec.get("seeded_from"),
                }
                diags[k] = v
                state["diagnoses"] = diags
                save(state)
                print("diag-retry", k, "OK" if v.get("obj") else "FAIL", flush=True)
                if not v.get("obj"):
                    print("HARD FAIL diagnosis", k, v.get("error"), flush=True)
                    save(state)
                    raise SystemExit(2)
    else:
        print("all diagnoses present", len(diags), flush=True)

    enc = FactorialEncoder()
    done = {
        (f["tid"], f["seed"])
        for f in state.get("forks", [])
        if f.get("arm") == "control"
    }
    forks = state.get("forks") or []
    for i, sn in enumerate(snaps):
        key = (sn["tid"], sn["seed"])
        if key in done:
            print(f"skip forks {key} ({i+1}/{len(snaps)})", flush=True)
            continue
        print(f"forking {key} ({i+1}/{len(snaps)})...", flush=True)
        new_forks, rec, take = cal_forks_for_snapshot(
            sn, delays=(0, 1, 2), enc=enc, include_takeover=True,
        )
        forks = [f for f in forks if not (f["tid"] == sn["tid"] and f["seed"] == sn["seed"])]
        forks.extend(new_forks)
        state["forks"] = forks
        save(state)
        n_ok = sum(1 for f in new_forks if f.get("success"))
        print(f"  forks={len(new_forks)} success={n_ok}", flush=True)
        for f in new_forks:
            tag = f.get("mid") or f["arm"]
            d = f.get("d")
            print(f"    {tag} d={d}: success={f['success']} status={f.get('status')}", flush=True)

    state["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    state["meta"]["n_forks"] = len(forks)
    save(state)
    print("CALIBRATION DONE", len(forks), "forks", flush=True)


if __name__ == "__main__":
    main()
