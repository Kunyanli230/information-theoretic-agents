"""Guide LLM calls via Cursor CLI (`agent`) + grok-4.6. No Codex dependency."""
import json, subprocess, tempfile, time, hashlib, os, re, math

AGENT = os.environ.get("VOI_GUIDE_BIN", "/home/box/.local/bin/agent")
MODEL = os.environ.get("VOI_GUIDE_MODEL", "grok-4.6")
# Pin: agent -p --mode=ask --model grok-4.6 --output-format text
CACHE = os.path.join(os.path.dirname(__file__), "..", "results", "guide_cache")
os.makedirs(CACHE, exist_ok=True)

SPEC = {
    "short": 'Return ONLY a JSON object {"hint": <advice of at most 40 words>, "applicable_if": <an exact substring copied verbatim from the code that your advice is about>}.',
    "long": 'Return ONLY a JSON object {"location": ..., "cause": ..., "change": ..., "verification": ..., "applicable_if": <an exact substring copied verbatim from the code that your advice is about>}. Do not write the full corrected code.',
    "diagnosis": 'Return ONLY a JSON object {"location": <where the bug is>, "cause": <why it fails>, "change": <what to change / steps>, "verification": <how to check the fix>, "applicable_if": <an exact substring copied verbatim from the code that your advice is about>}. Do not write the full corrected code. Fill every field.',
    "takeover": 'Return ONLY a JSON object {"code": <the complete corrected Python code>}.',
}


class GuideAuthError(RuntimeError):
    """CURSOR_API_KEY missing / agent not logged in — do not attempt device login here."""


def _usage_from_text(text, raw_usage=None):
    """Build usage dict: prefer CLI-reported tokens; else char estimates."""
    u = dict(raw_usage or {})
    if text is not None:
        u.setdefault("output_chars", len(text))
        if "output_tokens" not in u and text:
            u["est_output_tokens"] = math.ceil(len(text) / 4)
        if "input_tokens" not in u:
            u["input_tokens"] = None  # N/A under Cursor CLI unless reported
    return u


def _ask(prompt):
    """One headless Cursor CLI ask-mode call. Returns (text, usage, latency, err)."""
    if not os.path.isfile(AGENT) and not os.path.islink(AGENT):
        return None, None, 0.0, f"agent_binary_missing:{AGENT}"
    # Auth gate: require CURSOR_API_KEY or existing login — do not run agent login.
    has_key = bool(os.environ.get("CURSOR_API_KEY") or os.environ.get("CURSOR_AUTH_TOKEN"))
    # Cheap precheck: if neither key nor known auth, still try once and surface auth error.
    with tempfile.TemporaryDirectory(prefix="voi-guide-") as d:
        t0 = time.time()
        cmd = [
            AGENT, "-p", "--mode=ask", f"--model={MODEL}",
            "--output-format", "text",
            "--workspace", d,
            "--trust",
            prompt,
        ]
        try:
            r = subprocess.run(
                cmd, cwd=d, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=300,
                env={**os.environ},
            )
        except subprocess.TimeoutExpired:
            return None, None, time.time() - t0, "timeout"
        L = time.time() - t0
    out = (r.stdout or "").strip()
    err_txt = (r.stderr or "").strip()
    combined = (out + "\n" + err_txt).lower()
    if "authentication required" in combined or "not logged in" in combined:
        return None, None, L, "auth_required"
    if r.returncode != 0 and not out:
        return None, None, L, err_txt or f"exit_{r.returncode}"
    # Prefer last JSON object in stdout if present; else full text.
    text = out or None
    usage = _usage_from_text(text)
    return text, usage, L, None if text else (err_txt or "empty_output")


def cache_path(kind, key, code):
    h = hashlib.sha256(f"{kind}|{key}|{code}".encode()).hexdigest()[:16]
    return os.path.join(CACHE, f"{kind}_{h}.json")


def build_prompt(kind, code, test, error):
    return (
        f"You are a senior engineer helping a junior fix a bug. "
        f"Do not run tools or edit files. Reply with JSON only.\n"
        f"Code:\n```python\n{code}```\n"
        f"Failing test:\n```python\n{test}\n```\n"
        f"Error:\n{error}\n\n{SPEC[kind]}"
    )


def guidance(kind, code, test, error, key):
    """Cached guide call. key identifies the snapshot. Live backend = Cursor CLI only."""
    fp = cache_path(kind, key, code)
    if os.path.exists(fp):
        return json.load(open(fp))
    # Refuse to proceed without auth rather than hanging on login prompts.
    if not (os.environ.get("CURSOR_API_KEY") or os.environ.get("CURSOR_AUTH_TOKEN")):
        # Still allow cache writes only after a successful call; surface clear error.
        raise GuideAuthError(
            "CURSOR_API_KEY / CURSOR_AUTH_TOKEN not set; "
            "set the key or run `agent login` in 1:1 with Heath before live diagnosis"
        )
    prompt = build_prompt(kind, code, test, error)
    text, usage, L, err = None, None, 0.0, None
    for _ in range(2):
        text, usage, L, err = _ask(prompt)
        if err == "auth_required":
            raise GuideAuthError("agent reports authentication required")
        if text:
            break
    obj = None
    if text:
        m = re.search(r"\{.*\}", text, re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
        except Exception:
            obj = None
    rec = dict(
        kind=kind, key=key, text=text, obj=obj, usage=usage, latency=L,
        error=err, model=MODEL, backend="cursor-cli-agent",
        agent_bin=AGENT, agent_argv=[
            "-p", "--mode=ask", f"--model={MODEL}", "--output-format", "text",
        ],
    )
    # Persist only successful parses with usable text (path-A fresh).
    if text and obj is not None:
        json.dump(rec, open(fp, "w"))
    return rec


def cost(rec):
    u = rec.get("usage") or {}
    out = u.get("output_tokens")
    if out is None:
        out = u.get("est_output_tokens", 0) or 0
    inp = u.get("input_tokens") or 0
    return (inp or 0) + (out or 0)


def render(rec):
    o = rec.get("obj") or {}
    if rec["kind"] == "short":
        return o.get("hint")
    if rec["kind"] in ("long", "diagnosis"):
        return "\n".join(f"{k}: {o.get(k)}" for k in ("location", "cause", "change", "verification"))
