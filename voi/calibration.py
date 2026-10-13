"""Calibration / probe fork helpers: snapshots, control + message forks."""
import hashlib
from voi.tasks import T
from voi.check import visible_feedback, run_tests
from voi.executor import attempt
from voi.harness import loop, sd
from voi import guide, messages
from voi.encoder import FactorialEncoder

CAL_TASKS = ["T09", "T10", "T11", "T12", "T14", "T17", "T20", "T26"]
CONFIRM_TASKS = ["T28", "T31", "T32", "T33", "T37", "T38", "T40"]
TT = {t["id"]: t for t in T}


def make_snapshots(task_ids, n_per_task=1, seed0=1000, seed_lim=1040):
    """Attempt-1-fail snapshots: first n seeds from seed0 with visible fail after a1."""
    snaps = []
    for tid in task_ids:
        t = TT[tid]
        ok0, err0 = visible_feedback(t["buggy"], t["visible"])
        s, got = seed0, 0
        while got < n_per_task and s < seed_lim:
            code, _, _, dt = attempt(t["buggy"], t["visible"], err0, None, sd(("snap", tid, s), 1))
            ok, err = visible_feedback(code, t["visible"])
            if not ok:
                snaps.append(dict(tid=tid, seed=s, code=code, err=err, a1_s=dt, attempt=1))
                got += 1
            s += 1
    return snaps


def diagnose(sn):
    """ONE structured diagnosis z per prefix (cached)."""
    t = TT[sn["tid"]]
    key = (sn["tid"], sn["seed"])
    return guide.guidance("diagnosis", sn["code"], t["visible"], sn["err"], key)


def fork_control(sn):
    t = TT[sn["tid"]]
    key = ("fork", sn["tid"], sn["seed"])
    r = loop(t, sn["code"], sn["err"], 2, key)
    return dict(tid=sn["tid"], seed=sn["seed"], arm="control", mid=None, d=0, **r,
                guide_out=0, guide_in=0, message_cost=0.0, diag_cost_shared=0)


def fork_message(sn, mid, text, ai, msg_cost, diag_usage, latency, d=0):
    t = TT[sn["tid"]]
    key = ("fork", sn["tid"], sn["seed"])  # CRN across schemes
    r = loop(t, sn["code"], sn["err"], 2, key, g=(text, ai), deliver_at=2 + d, L=latency or 0.0)
    u = diag_usage or {}
    return dict(
        tid=sn["tid"], seed=sn["seed"], arm="msg", mid=mid, d=d, **r,
        guide_out=u.get("output_tokens", 0),
        guide_in=u.get("input_tokens", 0),
        guide_cached=u.get("cached_input_tokens", 0),
        guide_reasoning=u.get("reasoning_output_tokens", 0),
        message_cost=msg_cost if msg_cost is not None else 0.0,
        diag_cost_shared=u.get("output_tokens", 0),
    )


def probe_forks_for_snapshot(sn, enc=None):
    """Control + m1–m4 at d=0 from one diagnosis. Returns (forks, diag_rec)."""
    enc = enc or FactorialEncoder()
    rec = diagnose(sn)
    z = rec.get("obj") or {}
    variants = enc.variants(z)
    forks = [fork_control(sn)]
    usage, lat = rec.get("usage") or {}, rec.get("latency") or 0.0
    for mid, v in variants.items():
        if v["text"] is None:
            forks.append(dict(
                tid=sn["tid"], seed=sn["seed"], arm="msg", mid=mid, d=0,
                success=False, exec_s=0.0, wall=0.0, status="render_fail",
                gen_tokens=0, guide_out=usage.get("output_tokens", 0),
                guide_in=usage.get("input_tokens", 0), message_cost=0.0,
                diag_cost_shared=usage.get("output_tokens", 0),
                error="missing_fields",
            ))
            continue
        forks.append(fork_message(sn, mid, v["text"], v["applicable_if"], v["message_cost"], usage, lat, d=0))
    return forks, rec


def cal_forks_for_snapshot(sn, delays=(0, 1, 2), enc=None, include_takeover=True):
    """Full-cal forks: control + m1–m4 × delays + optional takeover.
    Returns (forks, diag_rec, takeover_rec_or_None).
    """
    enc = enc or FactorialEncoder()
    rec = diagnose(sn)
    z = rec.get("obj") or {}
    variants = enc.variants(z)
    usage, lat = rec.get("usage") or {}, rec.get("latency") or 0.0
    forks = [fork_control(sn)]
    for mid, v in variants.items():
        for d in delays:
            if v["text"] is None:
                forks.append(dict(
                    tid=sn["tid"], seed=sn["seed"], arm="msg", mid=mid, d=d,
                    success=False, exec_s=0.0, wall=0.0, status="render_fail",
                    gen_tokens=0, guide_out=usage.get("output_tokens", 0),
                    guide_in=usage.get("input_tokens", 0), message_cost=0.0,
                    diag_cost_shared=usage.get("output_tokens", 0),
                    error="missing_fields",
                ))
                continue
            forks.append(fork_message(
                sn, mid, v["text"], v["applicable_if"], v["message_cost"],
                usage, lat, d=d,
            ))
    take_rec = None
    if include_takeover:
        t = TT[sn["tid"]]
        key = (sn["tid"], sn["seed"], "takeover")
        take_rec = guide.guidance("takeover", sn["code"], t["visible"], sn["err"], key)
        tc = (take_rec.get("obj") or {}).get("code") or ""
        forks.append(dict(
            tid=sn["tid"], seed=sn["seed"], arm="takeover", mid=None, d=None,
            success=run_tests(tc + "\n", t["hidden"]) if tc else False,
            exec_s=sn.get("a1_s", 0.0),
            wall=(sn.get("a1_s", 0.0) or 0.0) + (take_rec.get("latency") or 0.0),
            status="takeover", gen_tokens=0,
            guide_out=(take_rec.get("usage") or {}).get("output_tokens")
                      or (take_rec.get("usage") or {}).get("est_output_tokens", 0),
            guide_in=(take_rec.get("usage") or {}).get("input_tokens") or 0,
            message_cost=0.0,
            diag_cost_shared=0,
            cost=guide.cost(take_rec),
        ))
    return forks, rec, take_rec
