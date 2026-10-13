"""VoI request-timing gate stub (prereg §3).

Probe does not use the gate (fixed factorial). Confirmatory G_fix / VD will.
Pre-pay scoring uses only phi and scheme q — never z or m.
"""
SCHEMES = ("none", "short", "long", "rd", "takeover")


class TabularGainPredictor:
    """Light tabular Δ̂(φ,q) fit on calibration forks. Stub until cal data exists."""

    def __init__(self, table=None):
        # table: frozenset/tuple features -> {q: (delta, delta_c, delta_n)}
        self.table = table or {}

    def predict(self, phi, q):
        key = _phi_key(phi)
        row = self.table.get(key) or self.table.get("pooled") or {}
        return row.get(q, (0.0, 0.0, 0.0))


def score(phi, q, predictor, lam=0.0, mu=0.0):
    """score(q) = Δ̂ - λ ΔĈ - μ ΔN̂. q='none' → 0."""
    if q == "none" or q == 0:
        return 0.0
    d, dc, dn = predictor.predict(phi, q)
    return d - lam * dc - mu * dn


def choose(phi, candidates, predictor, lam=0.0, mu=0.0, budget_ok=True):
    """Return q* and scores. Request only if score(q*)>0 and budget_ok."""
    scores = {q: score(phi, q, predictor, lam, mu) for q in candidates}
    q_star = max(scores, key=scores.get)
    request = budget_ok and scores[q_star] > 0 and q_star not in (0, "none")
    return dict(q_star=q_star if request else "none", scores=scores, request=request)


def _phi_key(phi):
    if phi is None:
        return "pooled"
    if isinstance(phi, dict):
        return tuple(sorted((k, phi[k]) for k in ("attempt", "error_class") if k in phi)) or "pooled"
    return phi
