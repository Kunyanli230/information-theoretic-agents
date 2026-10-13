"""Finite structured message family m1–m4 and post-encode message cost."""
import math

# Field order for nested templates (prereg §5).
FIELDS = ("location", "cause", "change", "verification")
FAMILY = {
    "m1": ("location",),
    "m2": ("location", "cause"),
    "m3": ("location", "cause", "change"),
    "m4": ("location", "cause", "change", "verification"),
}
SHORT_IDS = ("m1",)  # default short class; holdout may expand to m1∪m2
LONG_IDS = ("m3", "m4")


def render_from_z(z, mid):
    """Render message text + applicable_if from structured diagnosis z.
    Returns (text, applicable_if) or (None, None) if required fields missing.
    """
    if not z or mid not in FAMILY:
        return None, None
    parts = []
    for k in FAMILY[mid]:
        v = z.get(k)
        if v is None or v == "":
            return None, None
        parts.append(f"{k}: {v}")
    ai = z.get("applicable_if") or ""
    return "\n".join(parts), ai


def message_cost(z, mid, recipe="est_tokens"):
    """Post-encode message cost c_h(z,m) — differentiates templates.
    recipe:
      - est_tokens: ceil(len(rendered)/4)  (frozen default)
      - field_count: number of content fields in template
      - chars: character length of rendered text
    Diagnosis-call tokens are NOT included here (shared baseline).
    """
    text, _ = render_from_z(z, mid)
    if text is None:
        return None
    if recipe == "field_count":
        return float(len(FAMILY[mid]))
    if recipe == "chars":
        return float(len(text))
    # est_tokens
    return float(math.ceil(len(text) / 4))


def all_variants(z):
    """Map mid -> (text, applicable_if, message_cost) for all family members."""
    out = {}
    for mid in FAMILY:
        text, ai = render_from_z(z, mid)
        c = message_cost(z, mid)
        out[mid] = dict(text=text, applicable_if=ai, message_cost=c, fields=list(FAMILY[mid]))
    return out
