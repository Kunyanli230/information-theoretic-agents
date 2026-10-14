"""Fresh capability-gap precheck under Cursor CLI / grok-4.6.

Reuses frozen small-alone rates from results/pilot.json (executor unchanged).
Re-runs guide-alone takeover on kept tasks only. Does NOT start N=24.
Avoids importing voi.harness / executor (torch) — guide-alone needs only check+guide.
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from voi.tasks import T
from voi.check import run_tests, visible_feedback
from voi import guide

R = os.path.join(os.path.dirname(__file__), "..", "results")
OUT_JSON = os.path.join(R, "capability_gap_grok46.json")
OUT_MD = os.path.join(R, "capability_gap_grok46.md")
PILOT = os.path.join(R, "pilot.json")


def main():
    pilot = json.load(open(PILOT))
    filt = pilot["filter"]
    kept_ids = pilot["kept"]
    TT = {t["id"]: t for t in T}
    keep = [TT[i] for i in kept_ids]

    # Frozen small-alone (same formula as run_pilot Stage 2)
    s_rate = sum(sum(filt[t["id"]]) for t in keep) / max(1, 5 * len(keep))

    def pre(t):
        ok, err = visible_feedback(t["buggy"], t["visible"])
        r = guide.guidance("takeover", t["buggy"], t["visible"], err, ("pre", t["id"]))
        code = (r.get("obj") or {}).get("code") or ""
        succ = bool(run_tests(code + "\n", t["hidden"])) if code else False
        return dict(
            tid=t["id"],
            success=succ,
            cost=guide.cost(r),
            latency=r.get("latency"),
            error=r.get("error"),
            model=r.get("model"),
            backend=r.get("backend"),
            has_obj=r.get("obj") is not None,
        )

    print(f"guide-alone precheck: n={len(keep)} model={guide.MODEL}", flush=True)
    t0 = time.time()
    pres = []
    with ThreadPoolExecutor(2) as ex:
        futs = {ex.submit(pre, t): t["id"] for t in keep}
        for fut in as_completed(futs):
            row = fut.result()
            pres.append(row)
            lat = row["latency"] if row["latency"] is not None else -1
            print(f"  {row['tid']} ok={row['success']} err={row['error']} L={lat:.1f}s", flush=True)

    order = {tid: i for i, tid in enumerate(kept_ids)}
    pres.sort(key=lambda r: order[r["tid"]])

    g_rate = sum(1 for p in pres if p["success"]) / max(1, len(pres))
    gap_pp = 100 * (g_rate - s_rate)
    passed = (g_rate - s_rate) >= 0.15

    out = dict(
        model=guide.MODEL,
        backend="cursor-cli-agent",
        agent_bin=guide.AGENT,
        agent_version="2026.10.01-e373342",
        n_tasks=len(pres),
        kept=kept_ids,
        guide_alone=g_rate,
        small_alone=s_rate,
        small_alone_source="results/pilot.json filter (frozen executor)",
        gap_pp=gap_pp,
        pass_rule_pp=15,
        passed=passed,
        per_task=pres,
        wall_s=time.time() - t0,
        note="Codex guide-alone 100% not reused; path-A capability-gap recheck only.",
    )
    json.dump(out, open(OUT_JSON, "w"), indent=1)
    n_ok = sum(1 for p in pres if p["success"])
    md = "\n".join([
        "# Capability-gap precheck (Grok 4.6 / Cursor CLI)",
        "",
        f"- Model: `{out['model']}` via Cursor CLI `{out['agent_version']}`",
        f"- Tasks: {out['n_tasks']} (pilot kept)",
        f"- **guide-alone**: {100*g_rate:.1f}% ({n_ok}/{len(pres)})",
        f"- **small-alone** (frozen): {100*s_rate:.1f}%",
        f"- **gap**: {gap_pp:.1f} pp (pass rule ≥ 15 pp)",
        f"- **passed**: {passed}",
        f"- Wall: {out['wall_s']:.1f}s",
        "",
        "| tid | success | latency_s | cost |",
        "|---|:---:|---:|---:|",
        *[
            f"| {p['tid']} | {p['success']} | "
            f"{(p['latency'] if p['latency'] is not None else -1):.1f} | {p['cost']} |"
            for p in pres
        ],
        "",
    ])
    open(OUT_MD, "w").write(md)
    print("RESULT", json.dumps(dict(guide_alone=g_rate, small_alone=s_rate, gap_pp=gap_pp, passed=passed)), flush=True)
    print(f"wrote {OUT_JSON} {OUT_MD}", flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
