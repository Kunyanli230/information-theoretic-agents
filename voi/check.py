import subprocess, tempfile, os, sys
def run_tests(src, tests, timeout=5):
    """Return True iff all test snippets pass against src (each in fresh subprocess)."""
    code = src + "\n" + "\n".join(f"def _t{i}():\n" + "\n".join("    "+l for l in t.split("\n")) for i,t in enumerate(tests))
    code += "\nimport sys\nok=True\n" + "".join(f"try:\n    _t{i}()\nexcept Exception:\n    ok=False\n" for i in range(len(tests))) + "sys.exit(0 if ok else 1)\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f: f.write(code)
    try:
        r = subprocess.run([sys.executable, f.name], capture_output=True, timeout=timeout); return r.returncode == 0
    except subprocess.TimeoutExpired: return False
    finally: os.unlink(f.name)
def visible_feedback(src, test, timeout=5):
    code = src + "\n" + test + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f: f.write(code)
    try:
        r = subprocess.run([sys.executable, f.name], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stderr or "")[-600:]
    except subprocess.TimeoutExpired: return False, "TIMEOUT"
    finally: os.unlink(f.name)
