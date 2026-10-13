# VoI-Delegate — Phase-1 mechanism experiment: PREREGISTRATION

Status: written 2026-10-13 (Asia/Shanghai) BEFORE any harness code or run. Source: `/workspace/proposals/delegation/voi-delegate-theory-astra.md` §6 final recommendation (fixed request timing; no guidance / big-model takeover / guidance of different lengths; random injected delay). No VoI gate is trained here.

## 0. Questions
- Q1 (cheap-guidance benefit): does the frozen small executor's terminal success rise under short/long guidance vs. no guidance, at big-model cost below takeover?
- Q2 (length–delay tradeoff): does the success gain of long vs. short guidance shrink (or reverse) as injected delay grows, i.e. is there a delay-dependent finite optimal length?

## 1. Hardware & models (feasibility survey, 2026-10-13)
- Box: 8 CPU cores, 16 GB RAM (~3 GB free at survey time), **no GPU**, 112 GB disk free, HF reachable.
- Local models: only `Qwen/Qwen2.5-0.5B-Instruct` cached; torch 2.14.1+cpu / transformers 5.19 exist in `/workspace/deltareplay-toy/.venv`. No ollama/llama.cpp installed. No LLM API key in env (only an unrelated `TYPESAFE_API_KEY`). `codex` CLI 0.161 at `~/.local/bin/codex` (NOT /usr/local/bin), logged in via ChatGPT subscription.
- **Executor (small, frozen):** Qwen2.5-Coder-0.5B-Instruct (fallback: cached Qwen2.5-0.5B-Instruct), transformers CPU, fp32, seeded sampling T=0.7, top_p=0.95.
- **Guide (big):** Qwen2.5-Coder-3B-Instruct, GGUF Q4_K_M via llama.cpp (≈2 GB RAM), greedy (T=0) so guidance is a deterministic function of the snapshot.
  - Rationale: only pair that fits RAM with full local token accounting and exact reproducibility. A 7B guide does not fit available RAM. Codex/ChatGPT is NOT used as primary: non-local, no per-token billing visible, not reproducible; at most an exploratory side arm if Heath approves.
  - Known weakness: 3B vs 0.5B is a narrow capability gap; results speak only to this pair.

## 2. Task subset
- 40 synthetic, self-contained Python bug-fix tasks (`tasks/T01..T40`), each: one module (20–80 lines) with one seeded bug from fixed families (off-by-one, wrong comparator, missing edge case, wrong var, wrong return, mutable default, integer/float division, string slicing), hidden pytest suite (5–10 tests), plus a visible failing test.
- Task set frozen and hashed (sha256 in `tasks/MANIFEST`) before any model run. Filter applied once, before arms: keep tasks where executor-alone success over 5 seeds is in [0.1, 0.9] (avoid floor/ceiling); if <24 survive, regenerate with the same generator, logged.
- Rationale over SWE-bench subsets: CPU-only 0.5B model cannot make progress on real repos; synthetic tasks give exact snapshots (directory copy + RNG state + transcript) and cheap deterministic verification.

## 3. Agent loop, snapshot, fork
- Executor loop: ≤ 8 steps; actions = {VIEW file, EDIT (full-function rewrite), RUN visible test, SUBMIT}. Terminal success = hidden suite passes.
- **Fixed request timing:** guidance is requested at step k=2 (after the executor has viewed and run the failing test once). Snapshot S = (working dir tarball, transcript, executor RNG seed, step counter). All four arms fork from the identical S; executor seeds per fork are shared across arms (common random numbers).
- Restore check: re-running the no-guidance arm from S with the same seed must reproduce the transcript byte-for-byte; any mismatch invalidates that snapshot (reported).

## 4. Arms
- A0 No guidance: executor continues.
- A1 Takeover: guide model acts as executor from S to termination (same tools/step cap).
- A2 Short guidance: ≤ 40 output tokens, free text, one hint.
- A3 Long structured guidance: fields `location`, `cause`, `change`, `verification`, ≤ 200 output tokens.
- Every guidance message (A2, A3) carries `applicable_if`: a machine-checkable condition (sha256 of target file + target function name at time S). On delivery the harness checks it; if the file changed since S (stale), the message is **discarded** and logged as rejected-stale.
- **Injected delay:** message delivered after d executor steps, d ~ Uniform{0,1,2,3} drawn per fork with a seed fixed in advance; same d shared across A2/A3 for a given fork (paired). Delay also adds to wall-clock as d × measured executor step time (simulated asynchrony; the executor keeps acting meanwhile).

## 5. Metrics
- Terminal success (hidden tests).
- Fully billed big-model cost: guide input + output tokens across ALL guide calls (diagnosis prompt incl. snapshot context, any retries). Compute-equivalent $: tokens × reference price of a 3B-class API model fixed here as $0.10/M input, $0.10/M output (sensitivity: also report raw tokens and guide CPU-seconds). Small-model tokens/CPU-s also reported (to detect cost shifting).
- Wall-clock per fork (measured + simulated delay).
- Message acceptance: delivered & applicable / discarded stale; and whether the executor's next edit touched the indicated location.

## 6. Sample size & power
- Unit = fork (task × snapshot seed). Pilot: 24 tasks × 3 snapshot seeds × 4 delays → for A2/A3 each delay level ~72 forks; A0/A1 run once per (task, seed) = 72 forks each. Pilot is for variance and harness validation only; **pilot data are not used for the decision**.
- Main run size fixed from pilot by paired non-inferiority power: n = (z_{0.95}+z_{0.80})² · σ_d² / (δ − Δ_exp)², δ = 0.01. Honest expectation: with discordance ≈10% (σ_d² ≈ 0.1) and Δ_exp=0, n ≈ 6,200 paired forks per comparison — **not feasible on this CPU box** (see estimate). If the pilot-derived n exceeds 2,000 forks, we pre-commit to: run the maximal feasible n (cap 2,000 forks/arm), report the achieved one-sided lower bound, and classify any outcome whose CI cannot establish the 1 pp margin as "non-inferiority not established" — not as success.

## 7. Strongest baseline (rule fixed now)
Among A0 and A1, the strongest baseline is the one with the higher success rate; ties (|Δ| ≤ 1 pp) broken by lower big-model cost. If A0 is strongest, the cost comparison is moot (A0 costs 0 big-model tokens): the guidance arm must beat A0 on success; cost criterion then is vs A1.

## 8. Decision rules (fixed before running)
For the best guidance arm G ∈ {A2, A3} (chosen by the rule: highest success averaged over delays; ties → lower cost), vs strongest baseline B (normally A1):
1. Non-inferiority: one-sided 95% lower bound of (succ_G − succ_B) ≥ −0.01 (paired bootstrap over tasks, 10,000 resamples).
2. Saving s = 1 − cost_G / cost_B (mean billed big-model $ per fork, failures included).
   - Non-inferior AND lower CI bound of s ≥ 20% → **continue**.
   - Non-inferior AND point s ≥ 20% but CI below → promising, not confirmed (report; no extra sampling).
   - 10% ≤ s < 20% → **gray zone**, report, no main claim.
   - s < 10% → **stop** current scheme.
   - Success clearly worse (upper CI < −0.01) → fails regardless of cost.
- Q1 signal: succ(A2 or A3) − succ(A0) > 0 with one-sided 95% bootstrap CI excluding 0.
- Q2 signal: interaction (succ_A3 − succ_A2) slope over d < 0 with 95% CI excluding 0 (logistic regression success ~ arm × d, task fixed effects).
- If neither Q1 nor Q2 signal: report null honestly; per theory §6 do not proceed to VoI-gate training.
- No arm/tolerance/threshold edits after seeing main-run outcomes; any deviation logged in `DEVIATIONS.md`.

## 9. Runtime estimate (pilot)
0.5B CPU ≈ 10–20 tok/s gen, ~150 tok/step × ≤8 steps ≈ 1–2 min/fork; 3B Q4 ≈ 5–8 tok/s.
Pilot ≈ 72 (A0) + 72 (A1, slower) + 2×288 (A2/A3) ≈ 720 forks ≈ 12–24 h single process; ~2 parallel workers fit RAM → ≈ 6–12 h. Main run at the 2,000-fork cap is several days.
