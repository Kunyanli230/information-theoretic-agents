"""Confirmatory run: 7 tasks × 3 snaps × arms (prereg §6). UNDERPOWERED.

Fresh Grok-4.6 diagnoses (path A). Frozen encoder + gate from cal.
Resumable. Local only — no push/PR.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voi.calibration import CONFIRM_TASKS, make_snapshots, diagnose
from voi import guide
from voi.confirmatory import (
    ARM_SPEC, load_encoder_bundle, load_gate_bundle,
    run_c0, run_c1_takeover, run_fixed_message, run_gated,
)
from voi.gate import SHORT_MID, LONG_MID

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "confirmatory")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "confirm.json")

# Order: floor → fixed timing → ablations → full VD
ARM_ORDER = ["C0", "C1", "C2", "C3", "G_fix", "G_fixL", "VD_enc", "VD"]


def load():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {}


def save(state):
    json.dump(state, open(OUT, "w"), indent=1)


def ep_key(tid, seed, arm, d):
    return f"{tid}:{seed}:{arm}:d={d}"


def ensure_diagnosis(state, sn):
    diags = state.setdefault("diagnoses", {})
    k = f"{sn['tid']}:{sn['seed']}"
    v = diags.get(k) or {}
    ok = (
        v.get("obj")
        and not v.get("seeded_from")
        and v.get("model") == guide.MODEL
    )
    if ok:
        return v

    def _pack(rec):
        return {
            "obj": rec.get("obj"), "usage": rec.get("usage"),
            "latency": rec.get("latency"), "error": rec.get("error"),
            "text": rec.get("text"), "model": rec.get("model"),
            "backend": rec.get("backend"),
            "seeded_from": rec.get("seeded_from"),
        }

    rec = diagnose(sn)
    v = _pack(rec)
    diags[k] = v
    state["diagnoses"] = diags
    save(state)
    print("diag", k, "OK" if v.get("obj") else "FAIL", f"L={v.get('latency')}", flush=True)
    if not v.get("obj"):
        # bust empty cache + retry once
        fp = guide.cache_path("diagnosis", (sn["tid"], sn["seed"]), sn["code"])
        if os.path.exists(fp):
            try:
                old = json.load(open(fp))
                if not old.get("obj"):
                    os.remove(fp)
            except Exception:
                pass
        rec = diagnose(sn)
        v = _pack(rec)
        diags[k] = v
        state["diagnoses"] = diags
        save(state)
        print("diag-retry", k, "OK" if v.get("obj") else "FAIL", flush=True)
        if not v.get("obj"):
            raise SystemExit(f"HARD FAIL diagnosis {k}: {v.get('error')}")
    return v


def main():
    e_star, enc = load_encoder_bundle()
    gate_fit, predictor, lam, mu = load_gate_bundle()

    state = load()
    state.setdefault("meta", dict(
        prereg="v3-path-A-confirmatory",
        label="underpowered",
        n_tasks=7,
        confirm_tasks=CONFIRM_TASKS,
        n_per_task=3,
        arms=ARM_ORDER,
        delays=[0, 1, 2],
        short_mid=SHORT_MID,
        long_mid=LONG_MID,
        drop_m4=True,
        guide_model=guide.MODEL,
        guide_backend="cursor-cli-agent",
        agent_version="2026.10.01-e373342",
        encoder_commit_hint="59243b0",
        cal_commit_hint="53cf6b1",
        gate_lam=lam,
        gate_mu=mu,
        capability_gap_passed=True,
        thm1_ablation="G_fixL_vs_VD_required",
        started=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    ))
    save(state)

    if "snapshots" not in state:
        print("building confirmatory snapshots (3 attempt-1-fail / task)...", flush=True)
        snaps = make_snapshots(CONFIRM_TASKS, n_per_task=3, seed0=1000)
        state["snapshots"] = snaps
        save(state)
        print("snapshots", len(snaps), [(s["tid"], s["seed"]) for s in snaps], flush=True)
    else:
        snaps = state["snapshots"]
        print("resume snapshots", len(snaps), flush=True)

    episodes = state.get("episodes") or []
    done = {ep_key(e["tid"], e["seed"], e["arm"], e.get("d")) for e in episodes}

    def upsert(ep):
        nonlocal episodes, done
        k = ep_key(ep["tid"], ep["seed"], ep["arm"], ep.get("d"))
        episodes = [e for e in episodes if ep_key(e["tid"], e["seed"], e["arm"], e.get("d")) != k]
        episodes.append(ep)
        done.add(k)
        state["episodes"] = episodes
        save(state)

    for i, sn in enumerate(snaps):
        print(f"\n=== prefix {i+1}/{len(snaps)} {sn['tid']}:{sn['seed']} ===", flush=True)
        # Lazy diagnosis only when a message arm needs it
        diag_holder = {"rec": None}

        def get_diag():
            if diag_holder["rec"] is None:
                diag_holder["rec"] = ensure_diagnosis(state, sn)
            return diag_holder["rec"]

        for arm in ARM_ORDER:
            spec = ARM_SPEC[arm]
            kind = spec["kind"]

            if kind == "control":
                k = ep_key(sn["tid"], sn["seed"], arm, 0)
                if k in done:
                    print(f"  skip {arm}", flush=True)
                    continue
                print(f"  {arm}...", flush=True)
                ep = run_c0(sn)
                ep["arm"] = arm
                ep["q_star"] = "none"
                ep["request"] = False
                upsert(ep)
                print(f"    success={ep['success']}", flush=True)
                continue

            if kind == "takeover":
                k = ep_key(sn["tid"], sn["seed"], arm, None)
                if k in done:
                    print(f"  skip {arm}", flush=True)
                    continue
                print(f"  {arm} takeover...", flush=True)
                ep, _ = run_c1_takeover(sn)
                upsert(ep)
                print(f"    success={ep['success']}", flush=True)
                continue

            if kind == "fixed":
                mid = spec["mid"]
                for d in spec["delays"]:
                    k = ep_key(sn["tid"], sn["seed"], arm, d)
                    if k in done:
                        print(f"  skip {arm} d={d}", flush=True)
                        continue
                    print(f"  {arm} mid={mid} d={d}...", flush=True)
                    diag = get_diag()
                    ep = run_fixed_message(sn, arm, mid, d, diag)
                    upsert(ep)
                    print(f"    success={ep['success']} status={ep.get('status')}", flush=True)
                continue

            if kind == "gated":
                cands = spec["candidates"]
                # Decide once (independent of d); if no request, store a single d=0 episode
                # and mark other delays skipped-as-none to keep pairing honest.
                # First check if any delay already done
                delays = list(spec["delays"])
                # Peek decision without executor by calling choose path via run_gated d=0 first
                need = [d for d in delays if ep_key(sn["tid"], sn["seed"], arm, d) not in done
                        and ep_key(sn["tid"], sn["seed"], arm, None) not in done]
                # Also if none-decision stored under d=None
                if ep_key(sn["tid"], sn["seed"], arm, None) in done:
                    print(f"  skip {arm} (none-decision)", flush=True)
                    continue
                if not need and all(ep_key(sn["tid"], sn["seed"], arm, d) in done for d in delays):
                    print(f"  skip {arm} all d", flush=True)
                    continue

                # Run d=0 first to learn request
                d0 = 0
                if ep_key(sn["tid"], sn["seed"], arm, d0) not in done:
                    print(f"  {arm} gated d=0...", flush=True)
                    ep, _ = run_gated(
                        sn, arm, cands, predictor, lam, mu, d0, enc, get_diag,
                    )
                    if ep.get("q_star") == "takeover" or (
                        not ep.get("request") and ep.get("q_star") == "none"
                    ):
                        # collapse delay axis
                        ep["d"] = None if ep.get("q_star") == "takeover" else 0
                        # For none: only one episode; for takeover: one episode
                        if not ep.get("request"):
                            ep["d"] = None
                            ep["delay_collapsed"] = True
                        upsert(ep)
                        print(
                            f"    q*={ep.get('q_star')} success={ep['success']} "
                            f"status={ep.get('status')}",
                            flush=True,
                        )
                        # mark other delays as not applicable copies? skip running
                        continue
                    upsert(ep)
                    print(
                        f"    q*={ep.get('q_star')} success={ep['success']} "
                        f"status={ep.get('status')}",
                        flush=True,
                    )
                else:
                    # recover q* from existing d=0
                    prev = next(
                        e for e in episodes
                        if e["tid"] == sn["tid"] and e["seed"] == sn["seed"]
                        and e["arm"] == arm and e.get("d") == 0
                    )
                    if not prev.get("request"):
                        continue

                for d in delays:
                    if d == 0:
                        continue
                    k = ep_key(sn["tid"], sn["seed"], arm, d)
                    if k in done:
                        print(f"  skip {arm} d={d}", flush=True)
                        continue
                    print(f"  {arm} gated d={d}...", flush=True)
                    ep, _ = run_gated(
                        sn, arm, cands, predictor, lam, mu, d, enc, get_diag,
                    )
                    upsert(ep)
                    print(
                        f"    q*={ep.get('q_star')} success={ep['success']} "
                        f"status={ep.get('status')}",
                        flush=True,
                    )

    state["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    state["meta"]["n_episodes"] = len(episodes)
    save(state)
    print("\nCONFIRMATORY DONE", len(episodes), "episodes", flush=True)


if __name__ == "__main__":
    main()
