import json, subprocess, tempfile, time, hashlib, os, re
CODEX = "/home/box/.local/bin/codex"; MODEL = "gpt-5.5"
CACHE = os.path.join(os.path.dirname(__file__), "..", "results", "guide_cache"); os.makedirs(CACHE, exist_ok=True)
SPEC = {
 "short": 'Return ONLY a JSON object {"hint": <advice of at most 40 words>, "applicable_if": <an exact substring copied verbatim from the code that your advice is about>}.',
 "long": 'Return ONLY a JSON object {"location": ..., "cause": ..., "change": ..., "verification": ..., "applicable_if": <an exact substring copied verbatim from the code that your advice is about>}. Do not write the full corrected code.',
 "diagnosis": 'Return ONLY a JSON object {"location": <where the bug is>, "cause": <why it fails>, "change": <what to change / steps>, "verification": <how to check the fix>, "applicable_if": <an exact substring copied verbatim from the code that your advice is about>}. Do not write the full corrected code. Fill every field.',
 "takeover": 'Return ONLY a JSON object {"code": <the complete corrected Python code>}.',
}
def _ask(prompt):
    with tempfile.TemporaryDirectory() as d:
        t0 = time.time()
        try:
            r = subprocess.run([CODEX, "exec", "--skip-git-repo-check", "-s", "read-only", "-m", MODEL, "-c", "model_reasoning_effort=low", "--json", prompt],
                               cwd=d, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return None, None, time.time() - t0, "timeout"
        L = time.time() - t0
    text, usage, err = None, None, None
    for line in r.stdout.splitlines():
        try: ev = json.loads(line)
        except Exception: continue
        if ev.get("type") == "item.completed" and ev["item"].get("type") == "agent_message": text = ev["item"]["text"]
        if ev.get("type") == "turn.completed": usage = ev["usage"]
        if ev.get("type") in ("error", "turn.failed"): err = line
    return text, usage, L, err
def guidance(kind, code, test, error, key):
    """Cached guide call. key identifies the snapshot."""
    h = hashlib.sha256(f"{kind}|{key}|{code}".encode()).hexdigest()[:16]
    fp = os.path.join(CACHE, f"{kind}_{h}.json")
    if os.path.exists(fp): return json.load(open(fp))
    prompt = (f"You are a senior engineer helping a junior fix a bug. Do not run tools or edit files.\nCode:\n```python\n{code}```\n"
              f"Failing test:\n```python\n{test}\n```\nError:\n{error}\n\n{SPEC[kind]}")
    for _ in range(2):
        text, usage, L, err = _ask(prompt)
        if text and usage: break
    obj = None
    if text:
        m = re.search(r"\{.*\}", text, re.S)
        try: obj = json.loads(m.group(0)) if m else None
        except Exception: obj = None
    rec = dict(kind=kind, key=key, text=text, obj=obj, usage=usage, latency=L, error=err, model=MODEL)
    if usage: json.dump(rec, open(fp, "w"))
    return rec
def cost(rec):
    u = rec.get("usage") or {}; return u.get("input_tokens", 0) + u.get("output_tokens", 0)
def render(rec):
    o = rec.get("obj") or {}
    if rec["kind"] == "short": return o.get("hint")
    if rec["kind"] in ("long", "diagnosis"):
        return "\n".join(f"{k}: {o.get(k)}" for k in ("location", "cause", "change", "verification"))
