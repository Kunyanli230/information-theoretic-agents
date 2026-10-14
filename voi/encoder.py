"""Theorem-1 offline encoder interface + Blahut–Arimoto stub.

Probe uses FactorialEncoder (emit all m∈M from one z; no selection).
Full cal fits tables then BlahutArimotoEncoder / ArgmaxEncoder.
"""
import math
from voi import messages


class FactorialEncoder:
    """Probe / calibration: instantiate every family member from z (no select)."""

    def variants(self, z, h=None):
        return messages.all_variants(z)

    def select(self, z, h=None):
        raise NotImplementedError("FactorialEncoder does not select; use variants()")


class ArgmaxEncoder:
    """Deterministic decode of a fitted e*(m|z,h) table: argmax_m e."""

    def __init__(self, e_table, default_mid="m3"):
        # e_table: dict (z_id or 'pooled') -> dict mid -> prob, or callable
        self.e_table = e_table
        self.default_mid = default_mid

    def select(self, z, h=None, z_id="pooled"):
        row = self.e_table.get(z_id) or self.e_table.get("pooled") or {}
        if not row:
            return self.default_mid
        return max(row, key=row.get)

    def render(self, z, h=None, z_id="pooled"):
        mid = self.select(z, h, z_id)
        text, ai = messages.render_from_z(z, mid)
        return mid, text, ai, messages.message_cost(z, mid)


def blahut_arimoto(d, c, p_z, lam, beta, n_iter=50, mids=None):
    """Offline solve e(m|z) for one context bucket h (eqs. 7–9).

    d, c: dict[z_id][mid] -> float
    p_z: dict[z_id] -> float (sums to 1)
    Returns e[z_id][mid], q[mid], F history.
    Stub-safe: if tables empty, returns uniform.
    """
    mids = list(mids or messages.FAMILY.keys())
    zs = list(p_z.keys())
    if not zs:
        return {}, {m: 1.0 / len(mids) for m in mids}, []
    # init q uniform
    q = {m: 1.0 / len(mids) for m in mids}
    e = {z: {m: 1.0 / len(mids) for m in mids} for z in zs}
    hist = []
    for _ in range(n_iter):
        # update e
        for z in zs:
            scores = {}
            for m in mids:
                dm = d.get(z, {}).get(m, 0.0)
                cm = c.get(z, {}).get(m, 0.0)
                scores[m] = q[m] * math.exp(-(dm + lam * cm) / max(beta, 1e-9))
            s = sum(scores.values()) or 1.0
            e[z] = {m: scores[m] / s for m in mids}
        # update q
        q = {m: sum(p_z[z] * e[z][m] for z in zs) for m in mids}
        # objective
        F = 0.0
        for z in zs:
            for m in mids:
                F += p_z[z] * e[z][m] * (d.get(z, {}).get(m, 0.0) + lam * c.get(z, {}).get(m, 0.0))
        # mutual info term (discrete)
        I = 0.0
        for z in zs:
            for m in mids:
                if e[z][m] > 0 and q[m] > 0:
                    I += p_z[z] * e[z][m] * math.log(e[z][m] / q[m])
        F += beta * I
        hist.append(F)
    return e, q, hist
