"""List N=24 calibration prefixes needing fresh Cursor/grok-4.6 diagnosis cache entries.

Does NOT call the guide. Prints JSONL of {tid,seed,cache_path,prompt} for missing keys.
Requires executor (torch) to rebuild attempt-1-fail snapshot code.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from voi.calibration import CAL_TASKS, make_snapshots
from voi import guide
from voi.tasks import T

TT = {t["id"]: t for t in T}

# Pilot attempt-1-fail seeds (3 per cal task) — same as make_snapshots(n=3) expectation
def main():
    snaps = make_snapshots(CAL_TASKS, n_per_task=3, seed0=1000)
    print(f"# N={len(snaps)} prefixes", file=sys.stderr)
    missing = []
    for sn in snaps:
        t = TT[sn["tid"]]
        key = (sn["tid"], sn["seed"])
        fp = guide.cache_path("diagnosis", key, sn["code"])
        if os.path.exists(fp):
            rec = json.load(open(fp))
            if rec.get("backend") == "cursor-cli-agent" and rec.get("obj") and not rec.get("seeded_from"):
                print(f"# HIT {sn['tid']}:{sn['seed']} {os.path.basename(fp)}", file=sys.stderr)
                continue
        prompt = guide.build_prompt("diagnosis", sn["code"], t["visible"], sn["err"])
        row = dict(
            tid=sn["tid"], seed=sn["seed"], kind="diagnosis",
            cache_path=fp, prompt=prompt,
            model=guide.MODEL, backend="cursor-cli-agent",
        )
        missing.append(row)
        print(json.dumps(row, ensure_ascii=False))
    print(f"# missing={len(missing)}/{len(snaps)}", file=sys.stderr)
    return 0 if missing else 0

if __name__ == "__main__":
    raise SystemExit(main())
