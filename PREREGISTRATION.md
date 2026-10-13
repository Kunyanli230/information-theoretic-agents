# VoI-Delegate — Phase-1 mechanism experiment: PREREGISTRATION

Status: written 2026-10-13 (Asia/Shanghai) BEFORE any harness code or run. Source: `/workspace/proposals/delegation/voi-delegate-theory-astra.md` §6 final recommendation (fixed request timing; no guidance / big-model takeover / guidance of different lengths; random injected delay). No VoI gate is trained here.

## 0. Questions
- Q1 (cheap-guidance benefit): does the frozen small executor's terminal success rise under short/long guidance vs. no guidance, at big-model cost below takeover?
- Q2 (length–delay tradeoff): does the success gain of long vs. short guidance shrink (or reverse) as injected delay grows, i.e. is there a delay-dependent finite optimal length?

## 1. Hardware & models (amended v2, 2026-10-13 ~14:00 CST, approved by Heath; supersedes v1 §1–4)
- Box: 8 CPU cores, 16 GB RAM, no GPU. No local big model fits, so the guide is a remote model via Codex CLI (Heath approved).
- **Executor (small, frozen):** `Qwen/Qwen2.5-Coder-0.5B-Instruct` (HF snapshot `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`), transformers CPU fp32, sampling T=0.7, top_p=0.95, max_new_tokens=256, torch seed fixed per attempt (verified byte-identical re-generation for equal seed).
- **Guide (big):** Codex CLI 0.161.0 (`/home/box/.local/bin/codex`; `/usr/local/bin/codex` does not exist), invoked as `codex exec --skip-git-repo-check -s read-only -m gpt-5.5 -c model_reasoning_effort=low --json`, run in an empty temp dir, ChatGPT-account login (no new login attempted). Model pinned to `gpt-5.5`. It only returns text; it never edits files.
- Guide cost = `input_tokens + output_tokens` from the `turn.completed` usage event, summed over every guide call (cached_input_tokens and reasoning_output_tokens reported separately). Every guide response is cached on disk keyed by (snapshot, kind); all arms/delays from one snapshot reuse the same cached message, and each cached message is billed once per fork that consumes it (i.e. cost per fork as if generated for that fork).

## 2. Task subset
- 40 synthetic single-function Python bug-fix tasks (`voi/tasks.py`), each one seeded bug (off-by-one, comparator, operator, mutable default, missing guard, wrong return, etc.), one visible failing test and 2–4 hidden tests. Verified: fixed source passes hidden; buggy fails hidden and visible.
- **Difficulty filter (once, before any guide call):** executor-alone full loop (§3, no guidance), 5 seeds per task; keep tasks with success in [0.2, 0.8] (i.e. 1–4 of 5).
- **Capability-gap precheck (before arms):** on filtered tasks, guide-alone (one takeover call on the original buggy code, applied directly) vs executor-alone success from the filter run. Required: guide − small ≥ 15 pp. Otherwise record "this pair is unsuitable to test the question" (not a method failure) and stop.

## 3. Agent loop, request timing, snapshot, fork
- Executor gets code + visible test + error (+ any delivered guidance) and rewrites the code; up to K=4 attempts; stop early when the visible test passes. Terminal success = hidden tests pass on the final code.
- **Fixed request timing:** guidance is requested right after attempt 1 if it fails the visible test. Snapshot S = (code after attempt 1, its error). Snapshot seeds per task: the first 3 seeds from 1000,1001,... whose attempt 1 fails visible.
- All arms fork from the identical S; attempt j uses seed hash(snapshot, j), identical across arms (common random numbers).

## 4. Arms
- A0 No guidance: attempts 2–4 unchanged.
- A1 Takeover: guide returns full corrected code for S; that code is final (no executor attempts).
- A2 Short guidance: one hint of ≤ 40 words.
- A3 Long structured guidance: JSON fields `location`, `cause`, `change`, `verification`.
- A2/A3 messages carry `applicable_if`: an exact code substring of S the advice refers to. At delivery the harness checks the substring is still in the current code; if not, the message is **discarded as stale** (logged).
- **Injected delay:** d ∈ {0,1,2} executor attempts, all three levels run for every snapshot (full factorial, paired). Delivery happens before attempt 2+d (d=0: executor waits for the guide). Once delivered, guidance stays in the prompt. If the visible test passes before delivery, the message is "not needed" (neither accepted nor stale).
- Wall-clock (simulated asynchrony): executor compute is measured; guide latency L runs in parallel from request: wall = executor time + max(0, L − executor time spent before delivery). A1: attempt-1 time + L.

## 5. Metrics
- Terminal success (hidden tests).
- Fully billed big-model cost: guide input + output tokens across ALL guide calls (diagnosis prompt incl. snapshot context, any retries). Compute-equivalent $: tokens × reference price of a 3B-class API model fixed here as $0.10/M input, $0.10/M output (sensitivity: also report raw tokens and guide CPU-seconds). Small-model tokens/CPU-s also reported (to detect cost shifting).
- Wall-clock per fork (measured + simulated delay).
- Message acceptance: delivered & applicable / discarded stale; and whether the executor's next edit touched the indicated location.

## 6. Sample size & power (amended v2: non-inferiority margin δ = 5 pp)
- Pilot: all filtered tasks × 3 snapshots; A0, A1 once per snapshot, A2/A3 × 3 delays. Pilot is for harness validation and variance estimation; **it is not decisive** for the 20%/10% gate. Its numbers are reported descriptively with CIs.
- Main run: n = (z_0.95 + z_0.80)² · σ_d² / δ² paired forks, σ_d² from pilot discordance. Example: σ_d² = 0.1 → n ≈ 6.18·0.1/0.0025 ≈ 248 paired forks; σ_d² = 0.2 → ≈ 495. If the filtered pool cannot supply n snapshots at ≤ 10 snapshots/task, main run is capped there and labelled underpowered.

## 7. Strongest baseline (rule fixed now)
Among A0 and A1, the strongest baseline is the one with the higher success rate; ties (|Δ| ≤ 1 pp) broken by lower big-model cost. If A0 is strongest, the cost comparison is moot (A0 costs 0 big-model tokens): the guidance arm must beat A0 on success; cost criterion then is vs A1.

## 8. Decision rules (fixed before running)
For the best guidance arm G ∈ {A2, A3} (chosen by the rule: highest success averaged over delays; ties → lower cost), vs strongest baseline B (normally A1):
1. Non-inferiority: one-sided 95% lower bound of (succ_G − succ_B) ≥ −0.05 (paired bootstrap over tasks, 10,000 resamples).
2. Saving s = 1 − cost_G / cost_B (mean billed big-model $ per fork, failures included).
   - Non-inferior AND lower CI bound of s ≥ 20% → **continue**.
   - Non-inferior AND point s ≥ 20% but CI below → promising, not confirmed (report; no extra sampling).
   - 10% ≤ s < 20% → **gray zone**, report, no main claim.
   - s < 10% → **stop** current scheme.
   - Success clearly worse (upper CI < −0.05) → fails regardless of cost.
- Q1 signal: succ(A2 or A3) − succ(A0) > 0 with one-sided 95% bootstrap CI excluding 0.
- Q2 signal: interaction (succ_A3 − succ_A2) slope over d < 0 with 95% CI excluding 0 (logistic regression success ~ arm × d, task fixed effects).
- If neither Q1 nor Q2 signal: report null honestly; per theory §6 do not proceed to VoI-gate training.
- No arm/tolerance/threshold edits after seeing main-run outcomes; any deviation logged in `DEVIATIONS.md`.

- **Staleness threshold:** if the stale-discard rate over delayed messages (d ≥ 1, delivered or discarded) is < 5% in the pilot/main run, the staleness mechanism is declared an engineering detail, not a contribution.
- Acceptance = delivered & applicable; additionally logged whether the executor's next code differs from the code at delivery.

## 9. Runtime estimate (v2)
Executor ≈ 2–6 s/attempt on CPU; guide ≈ 5–15 s/call (4 calls in parallel). Filter 40×5 loops ≈ 30 min; pilot ≈ 1–2 h.
