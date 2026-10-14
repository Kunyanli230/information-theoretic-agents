"""Confirmatory episode runners (prereg §6).

Arms: C0, C1, C2, C3, G_fix, G_fixL, VD.
Family: short=m2, long=m3 (m4 dropped). Encoder e* from frozen results/encoder.
Fresh path-A diagnoses via Cursor CLI / grok-4.6 (no Codex caches).
"""
from __future__ import annotations

import json
import os

from voi.tasks import T
from voi.check import run_tests
from voi.harness import loop
from voi import guide, messages
from voi.calibration import diagnose, fork_control, fork_message, make_snapshots, CONFIRM_TASKS, TT
from voi.gate import (
    TabularGainPredictor, make_phi, choose,
    SHORT_MID, LONG_MID, CAND_G_FIX, CAND_G_FIXL, CAND_VD, CAND_VD_ENC,
)
from voi.encoder import ArgmaxEncoder

E_STAR_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "encoder", "e_star.json")
GATE_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "gate", "fit.json")


def load_encoder_bundle(path=E_STAR_PATH):
    e = json.load(open(path))
    mids = e.get("mids") or ["m1", "m2", "m3"]
    q = e.get("q_star") or {m: 1.0 / len(mids) for m in mids}
    # Unseen-z deploy: ArgmaxEncoder on pooled q* (λ=0 ⇒ m3).
    enc = ArgmaxEncoder(e_table={"pooled": q}, default_mid=LONG_MID)
    return e, enc


def load_gate_bundle(path=GATE_PATH):
    fit = json.load(open(path))
    pred = TabularGainPredictor.from_jsonable(fit["predictor"])
    return fit, pred, float(fit["lam"]), float(fit["mu"])


def render_scheme(z, q, enc: ArgmaxEncoder):
    """Map scheme q → (mid, text, applicable_if, message_cost) or takeover sentinel."""
    if q == "short":
        mid = SHORT_MID
        text, ai = messages.render_from_z(z, mid)
        return mid, text, ai, messages.message_cost(z, mid)
    if q == "long":
        mid = LONG_MID
        text, ai = messages.render_from_z(z, mid)
        return mid, text, ai, messages.message_cost(z, mid)
    if q == "rd":
        mid, text, ai, cost = enc.render(z, z_id="pooled")
        return mid, text, ai, cost
    raise ValueError(f"not a message scheme: {q}")


def run_c0(sn):
    return fork_control(sn)


def run_c1_takeover(sn):
    t = TT[sn["tid"]]
    key = (sn["tid"], sn["seed"], "takeover")
    take_rec = guide.guidance("takeover", sn["code"], t["visible"], sn["err"], key)
    tc = (take_rec.get("obj") or {}).get("code") or ""
    u = take_rec.get("usage") or {}
    return dict(
        tid=sn["tid"], seed=sn["seed"], arm="C1", mid=None, d=None,
        success=run_tests(tc + "\n", t["hidden"]) if tc else False,
        exec_s=sn.get("a1_s", 0.0),
        wall=(sn.get("a1_s", 0.0) or 0.0) + (take_rec.get("latency") or 0.0),
        status="takeover",
        gen_tokens=0,
        guide_out=u.get("output_tokens") or u.get("est_output_tokens", 0) or 0,
        guide_in=u.get("input_tokens") or 0,
        message_cost=0.0,
        diag_cost_shared=0,
        q_star="takeover",
        request=True,
        cost=guide.cost(take_rec),
        guide_error=take_rec.get("error"),
    ), take_rec


def run_fixed_message(sn, arm, mid, d, diag_rec):
    z = diag_rec.get("obj") or {}
    text, ai = messages.render_from_z(z, mid)
    cost = messages.message_cost(z, mid)
    usage, lat = diag_rec.get("usage") or {}, diag_rec.get("latency") or 0.0
    if text is None:
        return dict(
            tid=sn["tid"], seed=sn["seed"], arm=arm, mid=mid, d=d,
            success=False, exec_s=0.0, wall=0.0, status="render_fail",
            gen_tokens=0, guide_out=usage.get("output_tokens") or usage.get("est_output_tokens", 0) or 0,
            guide_in=usage.get("input_tokens") or 0, message_cost=0.0,
            diag_cost_shared=usage.get("est_output_tokens", 0) or 0,
            q_star=None, request=True, error="missing_fields",
        )
    r = fork_message(sn, mid, text, ai, cost, usage, lat, d=d)
    r["arm"] = arm
    r["q_star"] = None
    r["request"] = True
    # fix guide_out from est if zero
    if not r.get("guide_out"):
        r["guide_out"] = usage.get("output_tokens") or usage.get("est_output_tokens", 0) or 0
    return r


def run_gated(sn, arm, candidates, predictor, lam, mu, d, enc, diag_cache_get):
    """One gated episode. diag_cache_get() → diagnosis rec (lazy)."""
    phi = make_phi(attempt=1, err=sn.get("err") or "")
    dec = choose(phi, candidates, predictor, lam=lam, mu=mu)
    q = dec["q_star"]
    base = dict(
        tid=sn["tid"], seed=sn["seed"], arm=arm, d=d,
        q_star=q, request=dec["request"], scores=dec["scores"],
        phi_key=str(dec.get("phi")),
    )
    if not dec["request"] or q == "none":
        r = fork_control(sn)
        r.update(base)
        r["mid"] = None
        r["arm"] = arm
        return r, None

    if q == "takeover":
        r, take_rec = run_c1_takeover(sn)
        r.update(base)
        r["arm"] = arm
        r["d"] = None  # takeover not delay-factorial
        return r, take_rec

    # message schemes: short / long / rd
    diag_rec = diag_cache_get()
    z = diag_rec.get("obj") or {}
    mid, text, ai, msg_cost = render_scheme(z, q, enc)
    usage, lat = diag_rec.get("usage") or {}, diag_rec.get("latency") or 0.0
    if text is None:
        r = dict(
            success=False, exec_s=0.0, wall=0.0, status="render_fail",
            gen_tokens=0,
            guide_out=usage.get("output_tokens") or usage.get("est_output_tokens", 0) or 0,
            guide_in=usage.get("input_tokens") or 0,
            message_cost=0.0, diag_cost_shared=usage.get("est_output_tokens", 0) or 0,
            mid=mid, error="missing_fields",
        )
        r.update(base)
        return r, diag_rec
    r = fork_message(sn, mid, text, ai, msg_cost, usage, lat, d=d)
    r.update(base)
    r["arm"] = arm
    r["mid"] = mid
    if not r.get("guide_out"):
        r["guide_out"] = usage.get("output_tokens") or usage.get("est_output_tokens", 0) or 0
    return r, diag_rec


ARM_SPEC = {
    "C0": dict(kind="control"),
    "C1": dict(kind="takeover"),
    "C2": dict(kind="fixed", mid=SHORT_MID, delays=(0, 1, 2)),
    "C3": dict(kind="fixed", mid=LONG_MID, delays=(0, 1, 2)),
    "G_fix": dict(kind="gated", candidates=CAND_G_FIX, delays=(0, 1, 2)),
    "G_fixL": dict(kind="gated", candidates=CAND_G_FIXL, delays=(0, 1, 2)),
    "VD": dict(kind="gated", candidates=CAND_VD, delays=(0, 1, 2)),
    "VD_enc": dict(kind="gated", candidates=CAND_VD_ENC, delays=(0, 1, 2)),
}
