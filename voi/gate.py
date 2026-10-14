"""VoI request-timing gate (prereg §3).

Pre-pay scoring uses only phi and scheme q — never z or m.
TabularGainPredictor is fit on calibration forks (Δ̂^{π0}), not RL/SFT.
"""
from __future__ import annotations

import json
import os

SCHEMES = ("none", "short", "long", "rd", "takeover")

# Frozen before confirmatory (prereg §3 minimal φ).
SHORT_MID = "m2"
LONG_MID = "m3"


def error_class(err: str) -> str:
    e = (err or "").lower()
    if "assertion" in e or "assert" in e:
        return "assert"
    if "typeerror" in e:
        return "type"
    if "indexerror" in e or "keyerror" in e:
        return "index"
    if "nameerror" in e:
        return "name"
    if "zerodivision" in e or "division by zero" in e:
        return "math"
    return "other"


def make_phi(attempt: int, err: str, **extra) -> dict:
    phi = dict(
        attempt=int(attempt),
        error_class=error_class(err),
        failed=True,
    )
    phi.update(extra)
    return phi


def _phi_key(phi):
    if phi is None:
        return "pooled"
    if isinstance(phi, dict):
        parts = []
        if "attempt" in phi:
            parts.append(("attempt", int(phi["attempt"])))
        if "error_class" in phi:
            parts.append(("error_class", str(phi["error_class"])))
        return tuple(parts) if parts else "pooled"
    return phi


def _key_to_str(key):
    if key == "pooled":
        return "pooled"
    if isinstance(key, tuple):
        return "|".join(f"{k}={v}" for k, v in key)
    return str(key)


def _str_to_key(s):
    if s == "pooled":
        return "pooled"
    parts = []
    for tok in s.split("|"):
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        if k == "attempt":
            v = int(v)
        parts.append((k, v))
    return tuple(parts) if parts else "pooled"


class TabularGainPredictor:
    """Light tabular Δ̂(φ,q), Δ̂C, Δ̂N fit on calibration forks.

    table maps phi-key -> {q: (delta, delta_c, delta_n)}.
    Missing cells back off to 'pooled'.
    """

    def __init__(self, table=None, min_cell=3):
        self.table = table or {}
        self.min_cell = min_cell
        self.cell_n = {}  # optional counts for honesty

    def predict(self, phi, q):
        if q in (0, "none", None):
            return (0.0, 0.0, 0.0)
        key = _phi_key(phi)
        row = self.table.get(key)
        n = self.cell_n.get(key, 999)
        if row is None or n < self.min_cell:
            row = self.table.get("pooled") or {}
        return tuple(row.get(q, (0.0, 0.0, 0.0)))

    def to_jsonable(self):
        out = {}
        for k, row in self.table.items():
            out[_key_to_str(k)] = {q: list(v) for q, v in row.items()}
        return dict(table=out, cell_n={_key_to_str(k): n for k, n in self.cell_n.items()},
                    min_cell=self.min_cell)

    @classmethod
    def from_jsonable(cls, obj):
        table = {}
        for ks, row in (obj.get("table") or {}).items():
            table[_str_to_key(ks)] = {q: tuple(v) for q, v in row.items()}
        p = cls(table=table, min_cell=int(obj.get("min_cell", 3)))
        p.cell_n = {_str_to_key(k): int(n) for k, n in (obj.get("cell_n") or {}).items()}
        return p

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        json.dump(self.to_jsonable(), open(path, "w"), indent=2)

    @classmethod
    def load(cls, path):
        return cls.from_jsonable(json.load(open(path)))


def score(phi, q, predictor, lam=0.0, mu=0.0):
    """score(q) = Δ̂ - λ ΔĈ - μ ΔN̂. q='none' → 0."""
    if q in (0, "none", None):
        return 0.0
    d, dc, dn = predictor.predict(phi, q)
    return d - lam * dc - mu * dn


def choose(phi, candidates, predictor, lam=0.0, mu=0.0, budget_ok=True):
    """Return q* and scores. Request only if score(q*)>0 and budget_ok."""
    cands = []
    for q in candidates:
        if q in (0, "none", None):
            cands.append("none")
        else:
            cands.append(q)
    if "none" not in cands:
        cands = ["none"] + cands
    scores = {q: score(phi, q, predictor, lam, mu) for q in cands}
    q_star = max(scores, key=scores.get)
    request = bool(budget_ok and scores[q_star] > 0 and q_star not in (0, "none"))
    return dict(
        q_star=q_star if request else "none",
        scores=scores,
        request=request,
        phi=_phi_key(phi) if isinstance(phi, dict) else phi,
    )


# Candidate sets frozen for confirmatory arms (prereg §6).
CAND_G_FIX = ("none", "short")
CAND_G_FIXL = ("none", "long")
CAND_VD = ("none", "short", "long", "rd", "takeover")
# Q3 / prediction-5 encoder ablation (no takeover): gate + RD vs G_fixL.
# Frozen before confirmatory outcomes; full VD retains takeover for method arm.
CAND_VD_ENC = ("none", "short", "long", "rd")
