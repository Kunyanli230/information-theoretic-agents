import re, time, torch
from transformers import AutoTokenizer, AutoModelForCausalLM
MID = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
torch.set_num_threads(6)
_tok = AutoTokenizer.from_pretrained(MID)
_m = AutoModelForCausalLM.from_pretrained(MID, dtype=torch.float32).eval()
SYS = "You fix bugs in Python code. Reply with the complete corrected code in one ```python block and nothing else."
def prompt(src, test, err, guidance=None):
    u = f"Code:\n```python\n{src}```\nThis test fails:\n```python\n{test}\n```\nError:\n{err}\n"
    if guidance: u += f"\nA senior engineer sent this advice:\n{guidance}\n"
    u += "Fix the code."
    return [{"role": "system", "content": SYS}, {"role": "user", "content": u}]
def attempt(src, test, err, guidance, seed, max_new=256):
    """One executor attempt. Deterministic given seed (CPU). Returns (new_src, gen_tokens, in_tokens, secs)."""
    ids = _tok.apply_chat_template(prompt(src, test, err, guidance), add_generation_prompt=True, return_tensors="pt", return_dict=True)
    torch.manual_seed(seed); t0 = time.time()
    with torch.no_grad():
        out = _m.generate(**ids, do_sample=True, temperature=0.7, top_p=0.95, max_new_tokens=max_new, pad_token_id=_tok.eos_token_id)
    gen = out[0, ids["input_ids"].shape[1]:]
    txt = _tok.decode(gen, skip_special_tokens=True)
    mm = re.search(r"```(?:python)?\n(.*?)```", txt, re.S)
    code = (mm.group(1) if mm else txt).rstrip() + "\n"
    return code, int(gen.shape[0]), int(ids["input_ids"].shape[1]), time.time() - t0
