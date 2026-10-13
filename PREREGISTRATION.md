# VoI-Delegate — Phase-1 mechanism experiment: PREREGISTRATION (v3)

Status: written 2026-10-13 (Asia/Shanghai) **BEFORE** any v3 harness changes or new runs. Amended same day (still pre-implementation) for (i) message-side \(c_h(z,m)\) vs shared diagnosis baseline and (ii) mandatory VD takeover-rate reporting — see `DEVIATIONS.md`. Supersedes v2 fixed-timing four-arm protocol for the next confirmatory cycle. Source: `/workspace/proposals/delegation/voi-delegate-theory-astra.md` §§3–5 (Theorems 1–2, execution calibration, pseudocode ll.751–793) plus Heath via dr eggbot (2026-10-13): true VoI request timing, Theorem-1 encoder, Theorem-2 length–delay test, logistic primary, CLI cost as measurement limitation.

Pilot v2 (commits through `59d9979`) remains directional evidence only; it is not decisive for any gate. This document does **not** claim VoI-gate *training beyond a tabular/light predictor fit on fork data*, and does **not** claim low-overhead cost savings under Codex CLI until a separate amendment changes the guide path.

## Contribution coverage (hard checklist)

Each bullet is a claim that **may appear in the paper only if the corresponding experiment/report below is actually run and reported**. Missing any item ⇒ that contribution must not be claimed in the write-up.

1. **Applicable-if + stale discard (async vs Shepherding / SAG).** Messages carry `applicable_if` (exact code substring / version from the request snapshot). At delivery the harness checks the predicate against current code; fail ⇒ **discard as stale** (logged). Report **stale-discard rate** over delayed deliveries (\(d\ge 1\)). This mechanism is **not optional** for any async/guidance arm. If rate \(< 5\%\), label the mechanism an engineering detail (as in v2), but still keep it in the protocol and still report the rate.

2. **True VoI gate (execution-calibrated \(\widehat\Delta\)).** Request timing is **not** fixed after attempt 1. At each decision boundary the scheduler scores candidate schemes \(q\in\{0\}\cup\mathcal Q\) using predicted intervention gain from **execution-calibrated** forks (**not** free look-ahead at the big-model output). Pre-call scoring uses only \(\phi\) and scheme \(q\); **payment / guide call happens only after** \(\mathrm{score}(q^\star)>0\) and budget reserve. After return, a lightweight encoder maps structured diagnosis \(z\) to message \(m\).

3. **Theorem 1 enters the implementation.** Finite structured message family; offline estimates \(\widehat d_h(z,m)\), \(\widehat c_h(z,m)\); offline solve encoder \(e^\star\) (Blahut–Arimoto / convex, eqs. 7–9). Deploy path: one big-model diagnosis \(z\), then lightweight field/length selection — **never** online-call the big model to generate/score many candidates. **Required ablation (theory prediction 5):** signed gate + **fixed-length** instruction vs full rate–distortion encoding. If gate+fixed-length captures essentially all gains, the information-theoretic encoder is **theory only**, not an empirical main contribution.

4. **Theorem 2 falsifiable length–delay prediction.** As injected delay / staleness risk rises, **optimal length falls** (eqs. 14–15 qualitative prediction \(\partial r^\star/\partial\rho<0\)). Primary confirmatory test remains **long vs short × delay** via **preregistered logistic** with task fixed effects. If the exponential special case (eqs. 11–15) cannot be fit / validated on held-out data, **reject that parametric model**; do not keep only a favorable qualitative gloss.

## 0. Questions

- **Q0 (VoI timing):** Does an execution-calibrated signed-gain gate (request iff \(\widehat\Delta-\lambda\Delta C-\mu\Delta N>0\)) improve the success–cost frontier vs fixed request-after-attempt-1, under the same message family and delay mechanism?
- **Q1 (cheap-guidance benefit):** Does guidance under the frozen small executor raise terminal success vs no guidance, at big-model cost below takeover (efficacy primary; cost secondary under CLI — see §9)?
- **Q2 (length–delay / Theorem 2):** Does the success gain of longer vs shorter messages shrink (or reverse) as injected delay grows? Primary: logistic interaction. Secondary: whether fitted \(r^\star(\rho)\) matches eq. (15) on held-out data (reject model if not).
- **Q3 (encoder increment / Theorem 1 + prediction 5):** Does the offline decision rate–distortion encoder improve over signed-gate + fixed-length messages matched for mean length / token budget?

## 1. Hardware & models

Carries forward v2 amendments (Heath-approved Codex CLI guide; Qwen2.5-Coder-0.5B executor).

- Box: 8 CPU cores, 16 GB RAM, no GPU.
- **Executor (small, frozen):** `Qwen/Qwen2.5-Coder-0.5B-Instruct` (HF snapshot `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`), transformers CPU fp32, sampling T=0.7, top_p=0.95, max_new_tokens=256, torch seed fixed per attempt (byte-identical for equal seed).
- **Guide (big):** Codex CLI 0.161.0 (`/home/box/.local/bin/codex`), `codex exec --skip-git-repo-check -s read-only -m gpt-5.5 -c model_reasoning_effort=low --json`, empty temp dir, ChatGPT-account login (no new login). Model pinned `gpt-5.5`. Text-only; never edits files. **Same invocation constraints as v2.**
- **Cost reporting (CLI measurement limit):** every guide call logs `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_output_tokens` from `turn.completed` separately. **Primary cost claims for this phase use output-side tokens** (and separately report totals). Input is dominated by ~14k CLI fixed prompt overhead per call (pilot: ~14.2k mean); **total-token “savings vs pure-strong / takeover” are not interpretable as method savings under this meter** — see §9 and Blockers. Cached guide responses keyed by (snapshot, diagnosis-kind); billed once per fork that consumes them under the per-fork accounting rule (unique-cache-once sums only as secondary contrast, as in `results/cost_compare.*`).
- A0 big-model tokens = 0 means **big-model billing only**; small-model CPU/tokens are always reported and must not be described as a free baseline.

## 2. Tasks / filter (amendment: reuse pilot pool)

- Task bank: 40 synthetic single-function Python bug-fix tasks (`voi/tasks.py`), unchanged.
- **Reuse** the v2 difficulty-filtered kept set (executor-alone success in [0.2, 0.8] on 5 seeds), without re-filter:
  `T09,T10,T11,T12,T14,T17,T20,T26,T28,T31,T32,T33,T37,T38,T40` (15 tasks).
- **Capability-gap precheck:** reuse pilot result (guide-alone 100% vs small-alone 56%, gap 44 pp ≥ 15 pp). Do not re-spend guide calls unless models/versions change.
- **Justification:** avoids re-burning CLI budget; pool is already gap-qualified. **Risk:** 15 tasks cannot supply the v2-style \(n\approx 269\) paired forks for a powered non-inferiority gate — confirmatory analyses on this pool are **labelled underpowered** unless the task bank is expanded by a later amendment (Blockers).
- Task split for v3 (fixed before calibration outcomes are used for encoder/gate fitting):
  - **Calibration tasks (8):** `T09,T10,T11,T12,T14,T17,T20,T26` — forks used to estimate \(\widehat d,\widehat c\), fit encoder \(e^\star\), fit tabular/light \(\widehat\Delta\) predictor, choose \(\lambda,\mu,\beta\) and message-family members on a nested held-out slice of these 8.
  - **Confirmatory tasks (7):** `T28,T31,T32,T33,T37,T38,T40` — frozen artifacts from calibration; no refitting. All primary Q0–Q3 tests that claim generalization are on this set (underpowered; report CIs honestly).

## 3. Agent loop + VoI request timing

- Executor: code + visible test + error (+ any active guidance) → rewrite; up to \(K=4\) attempts; early stop when visible test passes. Terminal success = hidden tests pass on final code.
- **Protocol limit:** at most **one in-flight** guide request (theory §4 explicit limit).
- **Decision boundaries:** after each failed visible attempt \(j\in\{1,2,3\}\) while no pending request and remaining attempts exist (and residual budget allows a reserve).
- Features \(\phi_t=\phi(H_t,\mathcal P_t,B_t)\) (minimal v3 set; frozen before confirmatory):
  - attempt index \(j\); whether visible test failed; error-class hash; code length / edit distance from previous attempt;
  - executor self-consistency proxy: logprob margin or 1-sample confidence of last rewrite (no extra multi-sample unless calibration shows need — extra samples billed separately);
  - pending age / remaining attempts / remaining attempt budget;
  - rough staleness risk proxy: edits since last snapshot (0 if none).
- Candidate schemes \(\mathcal Q\) (pre-call; each \(q\) specifies encoder / length class, not a concrete string):
  - \(q=0\): no call;
  - \(q_{\mathrm{short}}\): call + encode with short family member(s);
  - \(q_{\mathrm{long}}\): call + encode with long family member(s);
  - \(q_{\mathrm{rd}}\): call + full offline \(e^\star\) (Theorem 1);
  - \(q_{\mathrm{takeover}}\): call for full corrected code (mid-upgrade; same as pilot A1 semantics when chosen).
- Score (eq. 3 style, frozen continuation \(\pi_0\) = “thereafter never call the guide again” for labels — honesty: this is \(\Delta^{\pi_0}\), not full \(Q^\star\)):

\[
\mathrm{score}(q)=\widehat\Delta(\phi,q)-\lambda\,\widehat{\Delta C}(\phi,q)-\mu\,\widehat{\Delta N}(\phi,q).
\]

Request \(q^\star=\arg\max_q\mathrm{score}(q)\) iff \(\mathrm{score}(q^\star)>0\) and max fee can be reserved. **Do not** observe \(z\) or \(m\) before committing to pay.

- Snapshot \(S\): (code, error, version / `applicable_if` anchor) at request time. Continuations use CRN: attempt seeds `hash(snapshot, attempt_idx)` shared across paired forks.
- Injected delay for **mechanism / Theorem-2 arms**: \(d\in\{0,1,2\}\) executor attempts after request (full factorial where the arm is delay-crossing). Delivery before attempt \(2+d\) relative to request attempt when using fixed-timing baselines; under VoI timing, delay is measured in executor attempts after the request boundary. Stale check at delivery. If visible passes before delivery ⇒ “not needed”.

## 4. Execution calibration for \(\Delta\) / \(d_h\)

Goal: estimate intervention effects under frozen executor + frozen \(\pi_0\) (no further guide calls after the experimental message).

On each calibration prefix:

1. Save code, error, RNG, attempt index.
2. Fork **control:** continue with no guidance to terminal.
3. Fork **treatments:** deliver message \(m\) from family \(\mathcal M\) (instantiated from one shared diagnosis \(z\)) at injected delay \(d\in\{0,1,2\}\); continue under \(\pi_0\).
4. Record \(Y\), guide tokens (in/out/cached/reasoning), wall time, accept / stale / not-needed.

**Decision distortion (eq. 5)** for context bucket \(h\) (group prefixes by coarse \(\phi\): attempt index × error class):

\[
v_h(z,m)=P(Y=1\mid h,Z=z,\operatorname{do}(M=m)),\quad
v_h^\star(z)=\max_{m\in\mathcal M_h}v_h(z,m),\quad
d_h(z,m)=v_h^\star(z)-v_h(z,m).
\]

**Cost \(\widehat c_h(z,m)\) (post-review amendment, before v3 code):** because diagnosis \(z\) is computed **once per prefix** and each \(m\) is a field subset of the same \(z\), the diagnosis call's output tokens are a **shared baseline** \(c^{\mathrm{diag}}\) (logged once; input/total reported secondarily) and **must not** alone serve as the \(m\)-differentiating cost inside the Theorem-1 encoder — otherwise \(\lambda c\) is nearly constant across \(m\) and cannot select length. Primary \(\widehat c_h(z,m)\) for encoding is the **post-encode message cost**: field count in the chosen template, and/or rendered character length / estimated tokens of the delivered string (frozen recipe before confirmatory: prefer estimated tokens of rendered \(m\), with field-count as a parallel/ablation cost). Fork-level billing still reports diagnosis in/out/cached/reasoning plus this message cost. Diagnosis once; no per-template guide re-call.

### Concrete calibration plan (N, K, S, T)

| Symbol | Meaning | v3 proposal |
|---|---|---|
| \(N\) | recoverable prefixes | **24** = 8 cal tasks × 3 attempt-1-fail snapshots (same seed rule as pilot: first 3 seeds from 1000… with attempt-1 visible fail). Optional stretch: + prefixes at attempt 2 on a subset if budget allows (Blockers). |
| \(n_m\) | message family size | **4** templates (see §5); chosen/ pruned on nested holdout within the 8 cal tasks. |
| delays | injected \(d\) | \(\{0,1,2\}\) |
| \(K\) | schemes per prefix in full cal | \(1\) (control) \(+\,4\times 3\) (messages × delays) \(=\) **13** paired forks; takeover optional once/prefix for reference (**+1** ⇒ 14). |
| \(S\) | repeats per (prefix, scheme) | **1** (CRN across schemes; expand to \(S=2\) only if discordance variance too high — Blockers). |
| \(T\) | mean remaining attempts | \(\approx 3\) |

Order-of-magnitude executor continuations: \(O(NKST)\approx 24\times 13\times 1\times 3 \approx 900\) attempt-steps; guide diagnosis calls \(\approx N=24\) (plus optional takeover \(N\)).

**Two-stage spend (mandatory):**

1. **Signal probe (cheap):** \(N_0=8\) (one snapshot/cal task), \(d=0\) only, control + 4 messages ⇒ \(8\times 5=40\) forks. Stop and report if no Q1-style lift of any message over control (Blockers — do not silently shrink family; report null).
2. **Full cal:** expand to \(N=24\), all delays, if probe shows signal.

**Sample-size separation (do not conflate):**

- **Gate-fitting / distortion sample:** calibration forks above (used only for \(\widehat d,\widehat c,e^\star,\widehat\Delta\)).
- **Confirmatory interaction sample:** confirmatory tasks × snapshots × arms; sized separately; with 7 tasks currently **underpowered** relative to pilot’s \(n\approx 269\) paired-fork target.

## 5. Message family & Theorem-1 encoder

**Finite structured family** (theory §4 examples; exact subset chosen on nested cal holdout):

| id | fields |
|---|---|
| \(m_1\) | locate |
| \(m_2\) | locate + cause |
| \(m_3\) | locate + cause + change/steps |
| \(m_4\) | locate + cause + change + verification |

All carry `applicable_if` / version. Length classes for Q2: **short** \(=\{m_1\}\) (or \(m_1\cup m_2\) if holdout prefers), **long** \(=\{m_3\}\) (or \(m_3\cup m_4\)).

**Encoder cost term:** \(c_h(z,m)\) in eqs. 7–9 is the **message cost** defined in §4 (rendered/estimated tokens or field count), **not** the one-shot diagnosis output alone. Diagnosis output remains a shared additive baseline outside the \(m\)-argmin when comparing templates from one \(z\).

Offline objective (eqs. 7–9):

\[
\min_e F_h(e)=\mathbb E_e[d_h(Z,M)]+\lambda\mathbb E_e[c_h(Z,M)]+\beta I_e(Z;M\mid h),
\]

with alternating updates

\[
e^{(k+1)}(m\mid z,h)\propto q^{(k)}(m\mid h)\exp\{-(d_h(z,m)+\lambda c_h(z,m))/\beta\},
\quad
q^{(k+1)}(m\mid h)=\sum_z p(z\mid h)e^{(k+1)}(m\mid z,h).
\]

Finite tables: Blahut–Arimoto or a small convex solver. Group by coarse \(h\); cross-group fallback = pooled table. **Deploy:** one Codex diagnosis \(z\) (JSON fields for the full family) → apply \(e^\star\) (or argmax deterministic decode of \(e^\star\)) to select fields/length → attach `applicable_if`.

Honesty: \(p(z\mid h)\) estimated empirically from cal diagnoses; estimation error bounds of eq. (10) cover \(\widehat d,\widehat c\) only under stated assumptions — source-distribution error is **out of scope** of that guarantee and is noted as a limitation.

## 6. Arms / conditions (confirmatory)

All arms share executor, \(K=4\), hidden-test success, stale mechanism for any delivered guidance, ≤1 in-flight request.

| Arm | Timing | Message | Role |
|---|---|---|---|
| **C0** No guidance | — | — | floor / A0 continuity |
| **C1** Takeover | fixed: after attempt-1 fail | full corrected code | mid-upgrade / A1 continuity; cost reference |
| **C2** Short, fixed timing | fixed: after attempt-1 fail | short template | Shepherding-style / A2 continuity |
| **C3** Long, fixed timing | fixed: after attempt-1 fail | long template | A3 continuity; **primary length×delay with C2** |
| **G_fix** Signed gate + fixed short | VoI gate; \(q\in\{0,q_{\mathrm{short}}\}\) | fixed short | ablation |
| **G_fixL** Signed gate + fixed long | VoI gate; \(q\in\{0,q_{\mathrm{long}}\}\) | fixed long | ablation |
| **VD** Full VoI-Delegate | VoI gate; \(q\) includes \(q_{\mathrm{rd}}\) | Theorem-1 \(e^\star\) | **full method** |
| **C1-gap** Pure-strong from scratch | (descriptive) | guide-alone on original buggy code | cost **upper bound** only (precheck reuse); not a mid-trajectory arm |

Delays \(d\in\{0,1,2\}\) on **C2, C3** (full factorial, paired) for Q2. Gate arms (G_fix, G_fixL, VD): natural stochastic latency + the same injected-delay factor on a paired subset so Theorem-2 and stale rates remain estimable; exact factorial for gate arms may be capped if Blockers fire — **cap must be reported, not silent**.

## 7. Metrics & analyses

- Terminal success (hidden tests).
- Guide tokens: input / output / cached / reasoning separately; **primary cost metric = output tokens** per fork (failures included). Totals reported with CLI-overhead footnote.
- Wall-clock (measured + simulated asynchrony as in v2).
- Message disposition: accepted / stale / not-needed; whether next edit touched indicated location.
- Stale-discard rate on \(d\ge 1\).
- **Takeover selection rate** on gated arms (G_fix, G_fixL, VD): fraction of decision boundaries (and of episodes) where \(q^\star=q_{\mathrm{takeover}}\) is chosen and paid. Always report; see decision rule below.

**Primary analyses (confirmatory tasks):**

- **Q2:** logistic regression `success ~ arm * delay + task_FE` comparing C3 vs C2 (long vs short); test interaction slope. 95% CIs; task-clustered bootstrap as **robustness** (pilot used bootstrap-only — deviation; logistic restored as primary).
- **Q0:** VD (or best gated arm) vs best fixed-timing guidance on success; paired by task.
- **Q3:** VD vs G_fix / G_fixL on success and output-token cost; if no increment ⇒ encoder not an empirical main claim.
- **Q1:** gated or fixed guidance vs C0 success.

Secondary: fit eqs. (11)–(15) on cal; validate \(r^\star\) on confirmatory — reject parametric model if misspecified.

## 8. Sample size / power / underpowered labeling

- Pilot discordance implied \(\sigma_d^2\approx 0.109\), \(n\approx 269\) paired forks for 5 pp non-inferiority (v2). With 7 confirmatory tasks × ≤3 snapshots = ≤21 snapshots, **confirmatory is underpowered** for the old 20% cost gate and for tight non-inferiority vs takeover.
- This phase therefore **labels confirmatory results underpowered** for cost non-inferiority. Efficacy / interaction CIs are reported without upgrading to a powered gate claim unless tasks are expanded.
- Calibration \(N=24\) is for estimation, not for the confirmatory gate.

## 9. Decision rules (updated for CLI cost limitation)

**Efficacy is primary** for go / no-go in this phase. Cost under Codex CLI is a **measurement limitation**, not a method failure by itself.

1. **Q2 (must report):** long−short × delay interaction from logistic; if CI excludes 0 in the predicted direction, Theorem-2 qualitative prediction supported on this harness; parametric (15) accepted only if holdout fit passes pre-specified tolerance (to be fixed at cal time on nested holdout RMSE / sign of \(\partial r^\star/\partial\rho\)).
2. **Q3:** if VD does not improve over G_fix/G_fixL on success (point estimate) with non-worse output-token cost, **do not claim** RD encoder as empirical main contribution; keep Theorem 1 as theory + negative/ablation result.
3. **Q0:** if gated arms do not beat fixed-timing C2/C3 on the success–output-token Pareto (descriptive underpowered CIs), report null on timing; do not silently revert to fixed timing in the method claim.
4. **Cost / saving vs C1 or pure-strong:** report output-token ratios and total-token ratios with footnote that totals are CLI-overhead-dominated (~0.98–0.99× in pilot cost_compare). **Do not** apply the v2 “\(s<10\%\) ⇒ stop scheme” rule to **total** tokens under CLI. Re-enable a formal 20%/10% total-cost gate only after a Heath-approved amendment to a low-fixed-overhead guide path (direct API or persistent cached session).
5. Non-inferiority vs takeover on **success** remains informative but underpowered; report CI vs −5 pp margin without claiming confirmation.
6. Stale rate: always report; \(<5\%\) ⇒ engineering-detail label for contribution text, mechanism still required.
7. **VD / gated takeover rate:** always report \(P(q^\star=q_{\mathrm{takeover}})\). If takeover is the modal paid choice on confirmatory (or rate is high enough that gains vs C0 are driven by mid-upgrade rather than guidance), **do not** claim guidance-protocol success in the write-up — novelty collapses to upgrade routing; report as such. Pre-specified soft flag for discussion: takeover rate \(>50\%\) of paid requests on VD ⇒ method claim defaults to upgrade-routing unless a sensitivity excluding takeover still shows guidance gains (must be preregistered before unblinding confirmatory).
8. No arm / threshold edits after seeing confirmatory outcomes; deviations → `DEVIATIONS.md`.

## 10. Blockers & risks to report (before / during implementation)

Do **not** silently shrink the algorithm. If any item bites, Coder reports to the group and waits.

1. **Distortion estimation cost \(O(NKST)\).** Full cal ~900 attempt-steps + ~24 diagnosis calls may exceed box/CLI budget or wall time. Mitigation already in protocol: signal probe first; then full cal. If probe is null, report and stop expansion — do not delete message family from the design doc.
2. **15-task pool / 7 confirmatory tasks underpowered** for non-inferiority and for stable encoder-vs-ablation separation. Need Heath decision to expand tasks or accept underpowered confirmatory + cal-only mechanism evidence.
3. **CLI ~14k input overhead** makes total-token savings unmeasurable; output-side only. Cost gate suspended pending pathway amendment.
4. **Encoder vs ablation:** if G_fix/G_fixL matches VD, information-theoretic communication stays theoretical — must be surfaced, not spun.
5. **Gate training honesty:** v3 fits a **tabular or light** predictor on cal forks (\(\widehat\Delta^{\pi_0}\)); not RL/SFT of models; not full Bellman \(Q^\star\). Do not claim otherwise.
6. **Attempt-2+ prefixes** may be needed for a non-trivial gate; if only attempt-1 prefixes are affordable, the gate is little more than a rebranded fixed-timing policy — report as Blocker if that collapse happens.
7. **Diagnosis once vs family:** if Codex refuses structured multi-field JSON reliably, field ablation for \(m_1\ldots m_4\) breaks; report before inventing online multi-calls (forbidden).

## 11. Runtime estimate (v3)

- Signal probe: ~40 executor forks + 8 guide calls ≈ 0.5–1.5 h.
- Full cal: ~24×13 forks + 24 guide calls ≈ 4–10 h wall (CPU-bound executor; guide serial/parallel limited by CLI).
- Confirmatory (7 tasks × 3 snapshots × arms × delays): depends on final arm set; order 3–8 h if full factorial on C2/C3 plus gated arms once.
- Encoder solve: negligible (\(O(J n_z n_m)\) table).

## 12. Diff vs pilot v2

- Request timing: **fixed after attempt-1** → **VoI gate** on execution-calibrated \(\widehat\Delta\) (pre-pay scheme scoring).
- Messages: fixed short/long strings from Codex → **finite family + offline Theorem-1 encoder**; one diagnosis \(z\), lightweight field select.
- Arms: A0–A3 → C0–C3 continuity **plus** G_fix, G_fixL ablation **plus** full VD.
- Primary Q2 analysis: bootstrap-only (pilot deviation) → **logistic with task FE restored**; bootstrap robustness.
- Cost: v2 total-token 20%/10% gate → **suspended under CLI**; report output tokens; total with overhead footnote; pure-strong vs takeover columns kept as in cost_compare.
- Tasks: same 15 kept; explicit **8/7 cal/confirm split**; confirmatory labelled underpowered.
- New: Contribution coverage checklist; Blockers section; ≤1 in-flight; stale mechanism retained as mandatory.
- Still out of scope: SFT/RL of either model; claiming classic EVSI non-negativity for signed \(\Delta\); TwinRouterBench static labels as intervention proof.
