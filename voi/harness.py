import json, sys, os, time, hashlib, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from voi.tasks import T
from voi.check import run_tests, visible_feedback
from voi.executor import attempt
from voi import guide
K = 4
R = os.path.join(os.path.dirname(__file__), "..", "results"); os.makedirs(R, exist_ok=True)
def sd(*a): return int(hashlib.sha256("|".join(map(str, a)).encode()).hexdigest()[:8], 16)
def loop(t, code, err, start, seedkey, g=None, deliver_at=None, L=0.0):
    """Run attempts start..K. g=(text, applicable_if). Returns dict."""
    ex_t, delivered, status, before = 0.0, False, "none", 0.0
    gen = 0
    for j in range(start, K + 1):
        if g and not delivered and j == deliver_at:
            if g[1] and g[1] in code: delivered, status = True, "accepted"
            else: status = "stale"; g = None
            before = ex_t
        prev = code
        code, n, _, dt = attempt(code, t["visible"], err, g[0] if delivered else None, sd(seedkey, j)); ex_t += dt; gen += n
        ok, err = visible_feedback(code, t["visible"])
        if delivered and j == deliver_at: changed = code != prev
        if ok: break
    if g and not delivered and status == "none": status = "not_needed"; before = ex_t
    wall = ex_t + (max(0.0, L - before) if (g or status == "stale") else 0.0)
    return dict(success=run_tests(code, t["hidden"]), exec_s=ex_t, wall=wall, status=status, gen_tokens=gen)
def full_alone(t, seed):
    ok, err = visible_feedback(t["buggy"], t["visible"])
    return loop(t, t["buggy"], err, 1, ("alone", t["id"], seed))
