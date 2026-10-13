"""Signal probe (prereg §4): N0=8, d=0, control + m1–m4. Resumable."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from voi.calibration import CAL_TASKS, make_snapshots, probe_forks_for_snapshot, diagnose
from voi.encoder import FactorialEncoder

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "probe")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "probe.json")


def load():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {}


def save(state):
    json.dump(state, open(OUT, "w"), indent=1)


def main():
    state = load()
    state.setdefault("meta", dict(
        prereg="v3", N0=8, d=[0], arms=["control", "m1", "m2", "m3", "m4"],
        cal_tasks=CAL_TASKS, started=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    ))
    # Snapshots: one attempt-1-fail per cal task
    if "snapshots" not in state:
        print("building snapshots...", flush=True)
        snaps = make_snapshots(CAL_TASKS, n_per_task=1, seed0=1000)
        state["snapshots"] = snaps
        save(state)
        print("snapshots", [(s["tid"], s["seed"]) for s in snaps], flush=True)
    else:
        snaps = state["snapshots"]
        print("resume snapshots", len(snaps), flush=True)

    # Pre-warm diagnoses (parallel, one per prefix)
    enc = FactorialEncoder()
    diags = state.get("diagnoses") or {}
    need = [sn for sn in snaps if f"{sn['tid']}:{sn['seed']}" not in diags]
    if need:
        print(f"diagnosing {len(need)} prefixes...", flush=True)
        def _d(sn):
            rec = diagnose(sn)
            return f"{sn['tid']}:{sn['seed']}", {
                "obj": rec.get("obj"), "usage": rec.get("usage"),
                "latency": rec.get("latency"), "error": rec.get("error"),
                "text": rec.get("text"), "model": rec.get("model"),
            }
        with ThreadPoolExecutor(4) as ex:
            for k, v in ex.map(_d, need):
                diags[k] = v
                state["diagnoses"] = diags
                save(state)
                print("diag", k, "obj" if v.get("obj") else "FAIL", v.get("usage"), flush=True)

    # Forks resumable by (tid, seed)
    done = {(f["tid"], f["seed"]) for f in state.get("forks", []) if f.get("arm") == "control"}
    forks = state.get("forks") or []
    for sn in snaps:
        key = (sn["tid"], sn["seed"])
        if key in done:
            print("skip forks", key, flush=True)
            continue
        print("forking", key, flush=True)
        # ensure diagnosis cached (probe_forks_for_snapshot calls diagnose → cache hit)
        new_forks, rec = probe_forks_for_snapshot(sn, enc=enc)
        # drop any prior partial for this snap
        forks = [f for f in forks if not (f["tid"] == sn["tid"] and f["seed"] == sn["seed"])]
        forks.extend(new_forks)
        state["forks"] = forks
        save(state)
        for f in new_forks:
            print(f"  {f.get('mid') or f['arm']}: success={f['success']} status={f['status']} msg_cost={f.get('message_cost')}", flush=True)
    state["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save(state)
    print("PROBE DONE", len(forks), "forks", flush=True)


if __name__ == "__main__":
    main()
