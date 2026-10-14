# VoI-Delegate: Decision-Oriented Asynchronous Rate–Distortion Control for Small-to-Large Model Guidance in Code Repair

**Kunyan Li (Heath Li)**
*Affiliation: [placeholder]*
*Correspondence: [placeholder]*

> **Draft status (2026-10-14).** arXiv-style working draft. All confirmatory analyses are **underpowered** (seven confirmatory tasks). Claims follow `voi-delegate/results/CLAIMS_BOUNDARY.md`. Methods and Results numbers are carried over from the verified Methods+Results draft (`methods-results.md`). Theorems are theoretical statements under stated assumptions; the experiments reported here do not prove them.

---

## Abstract

Small code models can run repair loops cheaply but often fail; large models can fix the same bugs but are costly to run end to end. Existing mid-run routers escalate by letting the large model restart the task. We study a different interface: the small model keeps executing while a large model sends a compressed, possibly delayed diagnosis. We formulate this as *decision-oriented asynchronous rate–distortion control*: a scheduler decides when to request guidance from a signed intervention gain, an encoder chooses message content from a finite structured family to minimize execution-defined decision distortion, and an applicability predicate discards stale messages. Under stated assumptions we give two theoretical results: a Gibbs/Blahut–Arimoto form of the cost-sensitive encoder for a fixed receiver (Theorem 1), and a finite optimal guidance length that shrinks with staleness hazard in an exponential special case (Theorem 2). We then report a preregistered small-scale study with a frozen Qwen2.5-Coder-0.5B executor and a `grok-4.6` guide on synthetic single-function Python bugs. The capability-gap precheck passed (100% vs 56%, 44 pp). Calibration fixed short \(=m_2\), long \(=m_3\), and dropped \(m_4\). On seven confirmatory tasks (underpowered), long guidance reached 81.0%, versus 38.1% without guidance and 55.6% with short guidance. The encoder arm exceeded gated fixed-long guidance by only +3.2 pp (directional). A full variant reached 95.2% only by selecting takeover on every paid request and is not guidance evidence. Length–delay rates were non-monotonic and do not test Theorem 2. We make no cost-savings claim.

---

## 1. Introduction

Coding agents increasingly pair models of very different capability and price. A small model can afford many edit–test iterations; a large model is more reliable but expensive. The common design response is *routing*: decide, at the start or partway through a run, whether to hand the task to the large model. SWE-Router, for example, lets a small model run a few exploration steps and then decides from the partial trajectory whether to continue or have the large model restart from the original task [SWE-Router]. Using partial trajectories and escalating mid-run are therefore not new.

This paper asks a different question. Suppose the small model *remains the executor* and the large model acts only as an advisor. Then the design problem is no longer "who runs the task" but a communication problem with four coupled choices: **when** to ask, **what** to send, **how much** to send, and **what to do when the message arrives late** and the code has already changed. A message that would have helped at request time may be useless or harmful after the executor has moved on. Mid-run upgrade routers do not model message content, message length, or delivery delay, because the large model's output is the whole solution.

We name this setting *decision-oriented asynchronous rate–distortion control* and instantiate it as **VoI-Delegate**. Three ideas organize it. First, the value of a guidance request is a *signed* intervention gain on terminal success under a frozen receiver, so guidance can hurt as well as help. Second, the distortion of a message is defined by *execution outcome*: how much terminal success is lost by sending \(m\) instead of the best candidate message, not textual similarity. Third, every message carries an `applicable_if` predicate tied to the request snapshot, so stale guidance can be detected and discarded on arrival.

**Contributions.** We restrict the contribution list to what the current evidence supports.

1. **Formulation.** We model small→large guidance during code repair as a constrained sequential decision problem with delayed communication actions, a signed intervention gain, execution-defined decision distortion, and an applicability predicate for staleness (Section 3).
2. **Theory (not empirically established here).** Under stated assumptions we state (i) a cost-sensitive decision rate–distortion encoder for a fixed receiver with a Gibbs / Blahut–Arimoto solution (Theorem 1), which reuses the classic rate–distortion mathematical structure, and (ii) a falsifiable special-case prediction that staleness yields a finite optimal guidance length that decreases with the staleness hazard (Theorem 2).
3. **A preregistered small-scale study.** With a frozen 0.5B executor and a `grok-4.6` guide, we report: a passed capability-gap precheck (44 pp); a calibrated message family (short \(=m_2\), long \(=m_3\), \(m_4\) dropped); a large descriptive benefit of long guidance over no guidance and short guidance; and a small, underpowered, directional encoder increment (+3.2 pp) over a signed-gate + fixed-long ablation.
4. **Transparent negative and diagnostic findings.** The full method's high success comes entirely from selecting takeover (upgrade routing), the offline encoder nearly collapses to fixed long messages, and confirmatory length–delay rates do not support a Theorem-2 claim. We report these as findings rather than omit them.

We do **not** claim cost savings, a powered encoder effect, or empirical confirmation of either theorem.

---

## 2. Related Work

**Mid-run routing and escalation.** SWE-Router lets a small model explore and then decides from the partial trajectory whether to continue or to have the large model start the task from scratch [SWE-Router]. This shares our use of partial trajectories but differs in what the large model produces: a full restart rather than an encoded message consumed by a small executor that keeps running under delay. Our takeover arms (C1, and VD when it selects takeover) correspond to this mid-run-upgrade style of intervention and serve as references, not as our proposed mechanism.

**Stepwise gating and signed rescue/harm scores.** A natural family of baselines decides at each step whether to escalate, using uncertainty or a learned estimate of whether escalation will rescue a failing run or harm a succeeding one. We adopt a signed intervention gain (rescue minus harm) as the *starting point* of our gate and do not present it as new. Our focus is on what the escalation sends when the receiver is the small model itself.

**Value of information.** Classic value-of-information decision theory measures the expected improvement in a decision maker's utility from observing information before acting; with free information that can be ignored, this value is non-negative. Our signed gain can be negative because the receiver is a fixed, limited small model that may follow wrong or stale advice. We therefore read our quantity as a *net intervention value under a constrained receiver and an asynchronous protocol*, not as a claim that classic Bayesian information value can be negative. We also note that a large model processing the same history may provide mainly value of computation rather than new Shannon information about the environment.

**Rate–distortion and information bottleneck.** Classic rate–distortion theory (Shannon) characterizes the minimum rate needed to describe a source within a distortion budget, and the Blahut–Arimoto algorithm computes it by alternating minimization. Information-bottleneck formulations compress a variable while preserving information about a relevance variable. In our setting, the "relevance" variable—task success—is itself changed by the message, so we define distortion directly through execution outcome under a fixed receiver. Theorem 1 uses the standard Gibbs-form solution; its intended contribution is the execution-estimated distortion and the deployable encoder, not new rate–distortion mathematics.

**Asynchronous agent guidance.** Supervisory or "shepherding"-style designs, in which a stronger model advises a weaker executor, raise the question of whether advice is still applicable when it arrives. We treat applicability explicitly via an `applicable_if` predicate checked at delivery. Related ideas in task-oriented communication, event-triggered control, and rational metareasoning are relevant; we have not completed a systematic survey of those areas and make no priority claim relative to them.

---

## 3. Problem Formulation and Theory

All results in this section are **theoretical**. They hold under the stated assumptions; Section 6 does not provide powered empirical tests of them.

### 3.1 Sequential decision with delayed messages

Consider a finite horizon \(t=0,\ldots,T\) with environment state \(S_t=(W_t,E_t,\Theta)\): workspace/code \(W_t\), execution and test state \(E_t\), and unobserved task requirements or fault mechanism \(\Theta\). The state evolves as \(S_{t+1}\sim P(\cdot\mid S_t,A_t)\). The small model observes history
\[
H_t=(O_0,A_0,O_1,\ldots,A_{t-1},O_t,M^{\mathrm{received}}_{\le t})
\]
and always executes: \(A_t\sim\pi_s(\cdot\mid H_t,M_t^{\mathrm{active}})\). The large model changes \(\pi_s\)'s conditioning input but does not replace the executor.

At each boundary the scheduler chooses a communication action \(U_t\in\{0\}\cup\mathcal Q\), where \(0\) means no new request and \(q\in\mathcal Q\) specifies request context, encoder, and length cap. If a request is issued, the large model computes a structured diagnosis \(Z_t\) from the snapshot \(H_t^{\mathrm{snap}}\) and the message is \(M_t\sim e_q(\cdot\mid Z_t,H_t^{\mathrm{snap}})\). The message arrives after a random delay \(D_t\), at \(\tau_t=t+D_t\), while the small model keeps executing. On arrival, an acceptance rule \(G_t=g(H_{\tau_t},H_t^{\mathrm{snap}},M_t)\in\{0,1\}\) decides whether the message is still applicable (operationalized below as `applicable_if`). The Markov information state is augmented with pending requests and budget, \(X_t=(b_t,\mathcal P_t,B_t,t)\).

The objective is
\[
\max_\pi\ \mathbb E_\pi[Y]\quad\text{s.t.}\quad \mathbb E_\pi[N_L]\le B_N,\ \ \mathbb E_\pi[C_L]\le B_C,\ \ \mathbb E_\pi[T_{\mathrm{wall}}]\le B_D,
\]
where \(Y\) indicates that the final patch passes the task's tests, \(N_L\) counts large-model calls, and \(C_L\) is large-model cost. Semantic information, output tokens, and API cost are distinct quantities; for a uniquely decodable binary code, \(I(Z;M\mid h)\le H(M\mid h)\le \mathbb E[L_{\mathrm{bits}}\mid h]\ln 2\), which does not imply a fixed number of useful bits per natural-language token.

### 3.2 Signed intervention gain

For history \(h\), scheme \(q\), and continuation policy \(\pi\), let \(Y^{q,\pi}\) and \(Y^{0,\pi}\) be the terminal outcomes of issuing \(q\) now versus issuing nothing now, with identical termination rules. The **signed intervention gain** is
\[
\Delta^\pi(h,q)=\mathbb E[Y^{q,\pi}-Y^{0,\pi}\mid h]. \tag{1}
\]
Under a prespecified coupling of potential outcomes, with rescue \(r=P(Y^0=0,Y^q=1\mid h)\) and harm \(w=P(Y^0=1,Y^q=0\mid h)\),
\[
\Delta^\pi(h,q)=r^\pi(h,q)-w^\pi(h,q). \tag{2}
\]
Randomized forks identify \(\Delta=p_q-p_0\); rescue and harm separately are only bounded, \(\max(0,p_q-p_0)\le r\le\min(p_q,1-p_0)\). The cost-penalized net value is
\[
\mathrm{VoI}^\pi_{\lambda,\mu}(h,q)=\Delta^\pi(h,q)-\lambda\,\Delta C^\pi(h,q)-\mu\,\Delta N^\pi(h,q), \tag{3}
\]
where \(\Delta C\) and \(\Delta N\) are incremental cost and call counts over the remaining trajectory. In our implementation the continuation is a frozen no-further-call policy \(\pi_0\), so labels estimate \(\Delta^{\pi_0}\), not an optimal \(Q^\star\).

### 3.3 Decision distortion

Fix \(h\), the receiver, and the continuation. Let \(v_h(z,m)=P(Y=1\mid h,Z=z,\mathrm{do}(M=m))\), integrating over delay, intervening state changes, and receiver randomness. With \(v_h^\star(z)=\max_{m\in\mathcal M_h}v_h(z,m)\), the **decision distortion** is
\[
d_h(z,m)=v_h^\star(z)-v_h(z,m)\in[0,1], \tag{4}
\]
and the conditional rate–distortion function is \(D_h(R)=\min_{e:\,I_e(Z;M\mid h)\le R}\mathbb E_e[d_h(Z,M)]\). The reference \(v_h^\star\) is a maximum over the finite candidate family, not an oracle.

### 3.4 Theorem 1 (theoretical): cost-sensitive decision rate–distortion encoder

**Assumptions.** For fixed context \(h\): (i) the diagnosis alphabet \(\mathcal Z\) and message family \(\mathcal M\) are finite; (ii) \(p(z\mid h)\), \(d_h(z,m)\), and message cost \(c_h(z,m)\) are known; (iii) the receiver, acceptance rule, and continuation are fixed; (iv) delay effects are folded into \(d_h\); (v) encoder and receiver share \(h\).

**Theorem 1.** For \(\beta>0\), \(\lambda\ge 0\), the problem
\[
\min_e\ F_h(e)=\mathbb E_e[d_h(Z,M)]+\lambda\,\mathbb E_e[c_h(Z,M)]+\beta\, I_e(Z;M\mid h) \tag{5}
\]
is convex in the channel \(e(m\mid z,h)\). On its support the optimum satisfies
\[
e^\star(m\mid z,h)=\frac{q^\star(m\mid h)\exp\{-[d_h(z,m)+\lambda c_h(z,m)]/\beta\}}{\sum_{m'}q^\star(m'\mid h)\exp\{-[d_h(z,m')+\lambda c_h(z,m')]/\beta\}},\qquad q^\star(m\mid h)=\sum_z p(z\mid h)\,e^\star(m\mid z,h), \tag{6}
\]
together with the full KKT conditions off the support.

*Proof sketch.* Using \(I_e(Z;M)=\min_q\sum_z p(z)D_{\mathrm{KL}}(e(\cdot\mid z)\Vert q)\) with minimizer \(q=q_e\), fix \(q\) and minimize per \(z\) with a Lagrange multiplier on normalization to obtain the Gibbs form; minimizing over \(q\) gives the marginal. Mutual information is convex in the channel for a fixed source and the other terms are linear, so KKT conditions are sufficient. Alternating the two updates is a Blahut–Arimoto iteration. \(\square\)

**Estimation remark.** If \(\|\widehat d-d\|_\infty\le\varepsilon_d\), \(\|\widehat c-c\|_\infty\le\varepsilon_c\), the source is known, and \(\widehat e\) is \(\eta\)-optimal for the estimated objective, then \(F(\widehat e)-F(e^\star)\le 2(\varepsilon_d+\lambda\varepsilon_c)+\eta\). This does not cover source misestimation, distribution shift, or receiver updates.

The theorem reuses the classic rate–distortion structure; its role here is to make message selection an explicit optimization over execution-estimated \(d_h+\lambda c_h\) rather than a post hoc label on a prompt heuristic.

### 3.5 Theorem 2 (theoretical): staleness yields a finite optimal guidance length

This is a falsifiable special-case model, not a general law.

**Assumptions.** (i) A fresh message carrying \(r\ge0\) nats of useful information yields expected success gain \(G_{\mathrm{fresh}}(r)=A(1-e^{-ar})\), \(A,a>0\); (ii) delay is \(\tau(r)=\tau_0+r/v\), \(v>0\); (iii) validity after delay \(\tau\) has probability \(e^{-\rho\tau}\), \(\rho>0\); (iv) staleness is conditionally independent of the fresh gain, and stale messages are detected and discarded without harm; (v) the post-intervention policy is fixed.

**Theorem 2.** The realized gain is \(G(r)=Ae^{-\rho\tau_0}(1-e^{-ar})e^{-\rho r/v}\). Conditional on issuing a call and ignoring per-unit information cost, the unique maximizer is
\[
r^\star=\frac1a\log\!\left(1+\frac{av}{\rho}\right), \tag{7}
\]
so \(\partial r^\star/\partial\rho<0\) and \(\partial r^\star/\partial v>0\): faster-changing state implies a shorter optimal message.

*Proof sketch.* With \(b=\rho/v\), \(G'(r)=Ae^{-\rho\tau_0}e^{-br}[(a+b)e^{-ar}-b]\); the bracket decreases strictly from \(a\) to \(-b\), giving a single root \(e^{-ar^\star}=b/(a+b)\) and a global maximum. \(\square\)

With per-unit information cost \(\kappa r\) and fixed call cost \(c_0\), the objective \(J(r)=G(r)-\lambda\kappa r-\lambda c_0\) has no worthwhile positive solution if \(G'(0)\le\lambda\kappa\); otherwise the unique positive candidate lies in \((0,r^\star]\) and the call is made only if \(\max_{r>0}[G(r)-\lambda\kappa r]>\lambda c_0\).

**Qualitative prediction.** As injected delay or staleness risk rises, the success advantage of longer over shorter messages should shrink or reverse. The exponential forms are modelling assumptions, not consequences of Shannon theory; "stale is harmless" requires reliable applicability checks.

### 3.6 Remark on thresholds

The exact sequential rule calls only if \(\max_{q\neq0}[Q^\star_{\lambda,\mu}(x,q)-Q^\star_{\lambda,\mu}(x,0)]>0\); this is Bellman optimality, not a new theorem. A fixed threshold on a one-step score is not optimal in general budgeted sequential problems, because it ignores the option value of future calls. If \(|\widehat Q_t-Q^\star_t|\le\varepsilon\) uniformly, the greedy policy loses at most \(2T\varepsilon\); this uniform-error assumption is strong and is not verified by our calibration data.

---

## 4. Methods

### 4.1 Models and tasks

The executor was a frozen small code model, `Qwen2.5-Coder-0.5B-Instruct` (Hugging Face snapshot `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`), run on CPU in fp32 with sampling temperature 0.7, `top_p=0.95`, and `max_new_tokens=256`. Attempt seeds were fixed so equal seeds produced byte-identical rewrites. Each episode allowed up to \(K=4\) rewrite attempts with early stopping when a visible unit test passed; terminal success required hidden tests to pass on the final code.

The guide was invoked via Cursor Agent CLI version `2026.10.01-e373342` with the pinned headless command

```text
agent -p --mode=ask --model grok-4.6 --output-format text --workspace <empty-temp-dir> "<prompt>"
```

`--mode=ask` kept the guide read-only. The guide returned a single structured JSON diagnosis with fields `location`, `cause`, `change`, `verification`, and `applicable_if` (an exact code substring anchoring the request snapshot). Path A used a fresh `grok-4.6` diagnosis per calibration or confirmatory prefix; Codex CLI was uninstalled and was not used for these runs. Earlier Codex-era pilot and probe data were not pooled with the `grok-4.6` results.

Tasks were synthetic single-function Python bug-fix items. We reused the fifteen difficulty-filtered tasks kept from the pilot (`T09`, `T10`, `T11`, `T12`, `T14`, `T17`, `T20`, `T26`, `T28`, `T31`, `T32`, `T33`, `T37`, `T38`, `T40`). Before calibration outcomes informed encoder or gate fitting, the pool was split into eight calibration tasks (`T09`–`T26` as listed) and seven confirmatory tasks (`T28`, `T31`, `T32`, `T33`, `T37`, `T38`, `T40`). With only seven confirmatory tasks, all confirmatory efficacy and ablation contrasts are labelled **underpowered**.

A capability-gap precheck under the same Cursor CLI / `grok-4.6` guide required guide-alone success minus frozen small-alone success to be at least 15 percentage points (pp) before the confirmatory path proceeded.

### 4.2 Protocol

At each decision boundary after a failed visible attempt \(j\in\{1,2,3\}\), while no request was in flight and residual attempts remained, the scheduler scored candidate schemes \(q\in\{0\}\cup\mathcal{Q}\) using an execution-calibrated predicted intervention gain \(\widehat\Delta\) (continuation under a frozen no-further-call policy \(\pi_0\)). A guide call was paid only if \(\mathrm{score}(q^\star)>0\) and a fee reserve was available; the diagnosis \(z\) and message \(m\) were not observed before payment. At most one guide request was in flight at a time.

Messages carried `applicable_if`. At delivery, the harness checked the predicate against the current code; failure discarded the message as **stale**. Injected delivery delays \(d\in\{0,1,2\}\) (executor attempts after the request) were applied on delay-crossing arms for mechanism and length–delay description. If the visible test passed before delivery, the message was logged as not needed.

The finite structured message family was

| id | fields |
|---|---|
| \(m_1\) | locate |
| \(m_2\) | locate + cause |
| \(m_3\) | locate + cause + change/steps |
| \(m_4\) | locate + cause + change + verification |

All templates carried `applicable_if`. Nested calibration holdout later froze the default encode family with **short** \(=m_2\), **long** \(=m_3\), and **\(m_4\) dropped** (same calibration success as \(m_3\), higher post-encode message cost).

### 4.3 Calibration

On \(N=24\) recoverable prefixes (eight calibration tasks × three attempt-1-fail snapshots), each prefix shared one fresh diagnosis \(z\). Forks comprised control (no guidance), each of \(m_1\)–\(m_4\) at delays \(d\in\{0,1,2\}\), and a takeover reference, for 336 forks total under common-random-number (CRN) continuations with \(S=1\) repeat per scheme. Decision distortion followed the preregistered definition \(d_h(z,m)=v_h^\star(z)-v_h(z,m)\) (Eq. 4). Encoder cost \(\widehat c_h(z,m)\) was the **post-encode** estimated token cost of the rendered message; diagnosis output tokens were a shared baseline logged once and did not alone differentiate templates.

### 4.4 Encoder

An offline Theorem-1-style Blahut–Arimoto fit on finite tables estimated encoder \(e^\star\) from calibration forks. Nested holdout within the eight calibration tasks used fit tasks `T09`–`T17` (six tasks) and holdout `T20`, `T26`. Holdout selected the no-\(m_4\) family and hyperparameters \((\lambda,\beta)=(0.0,0.05)\). With \(\lambda=0\), the frozen argmax policy concentrated on fixed long \(m_3\) (22/24 prefixes), so the rate–distortion encoder risked collapsing toward signed-gate + fixed-long guidance; confirmatory evaluation therefore ablated that contrast explicitly. Per-delay discrete argmax tables were stored for Theorem-2 diagnostics but were not treated as a powered length–delay test.

A tabular gain predictor for \(\widehat\Delta\) was fit on the same calibration forks with nested holdout selecting gate penalties \(\lambda=0.001\), \(\mu=0.0\).

### 4.5 Confirmatory evaluation

Confirmatory evaluation used the seven held-out tasks × three snapshots (21 prefixes; 378 episodes) with frozen encoder and gate artifacts and fresh path-A diagnoses. Arms were:

| Arm | Timing | Message / scheme | Role |
|---|---|---|---|
| **C0** | — | no guidance | floor |
| **C1** | fixed after attempt-1 fail | full corrected code (takeover) | mid-upgrade reference |
| **C2** | fixed after attempt-1 fail | short \(m_2\) | fixed short |
| **C3** | fixed after attempt-1 fail | long \(m_3\) | fixed long; length×delay with C2 |
| **G_fix** | VoI gate; \(q\in\{0,q_{\mathrm{short}}\}\) | fixed short | ablation |
| **G_fixL** | VoI gate; \(q\in\{0,q_{\mathrm{long}}\}\) | fixed long | ablation |
| **VD_enc** | VoI gate; candidates \(\{\mathrm{none},\mathrm{short},\mathrm{long},\mathrm{rd}\}\) | Theorem-1 \(e^\star\) (no takeover) | Q3 encoder contrast |
| **VD** | VoI gate; candidates include takeover | full method including upgrade | reported with takeover rate |

Delays \(d\in\{0,1,2\}\) were applied on message and gated-request arms. Arm **VD_enc** was added before confirmatory outcomes specifically so the Q3 encoder contrast would not be confounded by upgrade routing.

### 4.6 Metrics and analysis

Primary efficacy was terminal hidden-test success. Primary cost meters were guide-call counts, post-encode message-side cost \(c_h(z,m)\), and available guide token or character fields; the formal total-token 20%/10% cost-savings gate was **not** restored for this guide path. Message dispositions (accepted / stale / not-needed) and stale-discard rate on delayed deliveries (\(d\ge 1\)) were logged. For gated arms, takeover selection rate among paid requests was always reported.

Preregistered primary analyses included a Q2 logistic regression `success ~ arm * delay + task_FE` comparing C3 vs C2. That logistic was **not run** for this draft; length–delay results below are descriptive rates only. Q3 used the paired success difference of **VD_enc** versus **G_fixL**. Wilson 90% intervals are reported where present in the result files. All confirmatory contrasts remain underpowered.

---

## 5. Results

### 5.1 Capability-gap precheck

Under Cursor CLI / `grok-4.6`, guide-alone success was **100%** (15/15 kept tasks) versus frozen small-alone **56%**, a gap of **44.0 pp**, which passed the ≥15 pp rule. The confirmatory path therefore proceeded (not an exploratory downgrade).

### 5.2 Calibration success rates

Pooled over delays, calibration success rates on \(N=24\) prefixes were:

| Scheme | Rate | \(k/n\) | Est. message tokens |
|---|---|---|---|
| control | 41.7% | 10/24 | — |
| \(m_1\) | 43.1% | 31/72 | 15.2 |
| \(m_2\) | 52.8% | 38/72 | 50.1 |
| \(m_3\) | 77.8% | 56/72 | 78.8 |
| \(m_4\) | 77.8% | 56/72 | 110.9 |
| takeover | 91.7% | 22/24 | — |

Because \(m_1\) was near control, the short class was set to \(m_2\). Because \(m_3\) matched \(m_4\) on success while \(m_4\) had higher message cost (estimated tokens 78.8 vs 110.9), \(m_4\) was dropped from the default encode family.

By delay, long-template rates declined directionally (\(m_3\): 83.3% / 79.2% / 70.8% at \(d=0,1,2\)); short \(m_2\) was 58.3% / 54.2% / 45.8%. Status counts included 16 stale deliveries among delayed forks (~8% of delayed deliveries in calibration)—retained as a calibration observation of the applicability mechanism.

### 5.3 Offline encoder

Nested holdout chose family \(m_1\)–\(m_3\) (no \(m_4\)) with \((\lambda,\beta)=(0.0,0.05)\). Frozen argmax counts were \(\{m_1:0,\,m_2:2,\,m_3:22\}\); the argmax policy on calibration (pooled) had success 0.806 and message cost 76.1, close to fixed \(m_3\) (0.778 / 78.8). Delay-conditional argmax did **not** shift mass toward shorter messages as \(d\) increased (\(d=0\): 2×\(m_2\)+22×\(m_3\); \(d=1\)–\(2\): 24×\(m_3\)). These calibration facts foreshadow a weak encoder increment and do not constitute a powered Theorem-2 test.

### 5.4 Confirmatory arm rates (underpowered)

On seven confirmatory tasks (21 snapshots; rates pooled over delays where applicable):

| Arm | Rate | \(k/n\) | 90% Wilson |
|-----|------|---------|------------|
| C0 | 38.1% | 8/21 | [0.23, 0.56] |
| C1 | 95.2% | 20/21 | [0.81, 0.99] |
| C2 | 55.6% | 35/63 | [0.45, 0.65] |
| C3 | 81.0% | 51/63 | [0.72, 0.88] |
| G_fix | 58.7% | 37/63 | [0.48, 0.68] |
| G_fixL | 81.0% | 51/63 | [0.72, 0.88] |
| VD_enc | 84.1% | 53/63 | [0.75, 0.90] |
| VD (full) | 95.2% | 20/21 | [0.81, 0.99] |

**Long guidance helps.** Fixed long C3 and gated fixed-long G_fixL both reached **≈81.0%**, well above control C0 **38.1%** and short C2 **≈55.6%**. Short-gated G_fix (58.7%) stayed near C2.

### 5.5 Encoder increment (Q3): VD_enc only

The Q3 encoder contrast uses **VD_enc only** versus G_fixL: **84.1%** vs **81.0%**, paired mean difference **+3.2 pp** (63 pairs). The empirical increment is present but small, underpowered, and **directional only**; it is **not** a powered primary contribution. Theorem-1 empirical support therefore remains weak on this toy pool.

Full **VD** also reached **95.2%** (20/21), but `takeover_among_paid=1.0` (21/21 paid requests chose takeover). That arm therefore collapses to upgrade routing, matching C1, and is **not** treated as guidance or encoder evidence. G_fix, G_fixL, and VD_enc each had `takeover_among_paid=0` (paid schemes were short, long, and `rd` respectively).

### 5.6 Length × delay (descriptive; logistic not run)

| Arm | \(d=0\) | \(d=1\) | \(d=2\) |
|---|---|---|---|
| C2 (short \(m_2\)) | 52.4% | 61.9% | 52.4% |
| C3 (long \(m_3\)) | 85.7% | 71.4% | 85.7% |

Descriptive C3×delay rates were **85.7% / 71.4% / 85.7%** at \(d=0,1,2\) (non-monotonic). C2×delay rates were 52.4% / 61.9% / 52.4%. We do **not** claim that optimal length shortens with delay, nor a powered Theorem-2 result, from these rates or from calibration discrete argmax. The preregistered confirmatory logistic interaction was not computed for this write-up.

### 5.7 Stale discard

On confirmatory delayed deliveries, stale rate was **4.76%** (10/210), below the 5% threshold. The applicability / stale mechanism remains in the protocol and is reported as an **engineering detail**, not a headline contribution. Calibration stale count (16 among delayed forks) is noted above as a calibration observation only.

### 5.8 Cost meters

Guide-call behavior on gated confirmatory arms was uniform at the paid-request level reported above (21 paid requests per gated arm on 21 prefixes under the fitted gate). Available mean guide-output estimates in the confirmatory summary were 0 for C0, ≈33.5 for C1 and full VD (takeover path), and ≈123.2 for C2, C3, G_fix, G_fixL, and VD_enc. Message-side calibration costs remained those in the encoder fit (\(m_2\) ≈50.1, \(m_3\) ≈78.8 estimated tokens). No total-token cost-savings gate or threshold claim is made; that gate was not restored for the Grok-era meter.

---

## 6. Discussion

### 6.1 What the evidence supports

Within this small harness, the clearest signal is that a frozen 0.5B executor can use structured guidance from a much stronger model: long guidance (\(m_3\): location, cause, and change steps) raised confirmatory success from 38.1% to about 81%, whereas location + cause alone (\(m_2\)) reached about 56%. Calibration produced a compact, interpretable family choice—short \(=m_2\), long \(=m_3\), with \(m_4\)'s verification field adding message cost without additional success. The capability-gap precheck (44 pp) shows that the guide had room to help. These are descriptive findings on an underpowered pool.

### 6.2 Limitations

1. **Seven confirmatory tasks.** All confirmatory contrasts rest on 7 tasks × 3 snapshots of synthetic single-function bugs, with \(S=1\) CRN continuations. Wilson intervals are wide and overlapping for several arms; we report no hypothesis tests or p-values.
2. **The encoder collapses toward fixed \(m_3\).** Holdout selected \(\lambda=0\), and the frozen encoder chose \(m_3\) on 22/24 calibration prefixes. The VD_enc vs G_fixL contrast (+3.2 pp) is therefore small by construction and directional only. Per the preregistered prediction-5 rule, the rate–distortion encoder is not an empirical main contribution here; Theorem 1 remains theory with weak empirical support.
3. **Full VD equals takeover.** The full method selected takeover on 21/21 paid requests, so its 95.2% is upgrade routing (equivalent to C1), not evidence for guidance or encoding. On calibration replay, takeover had tied predicted gain and lower guide-output cost, which explains the gate's choice.
4. **No powered Theorem-2 test.** The preregistered logistic interaction was not run; confirmatory C3×delay rates were non-monotonic, and the delay-conditional argmax did not shift toward shorter messages. The calibration decline of \(m_3\) with delay is directional only. The parametric model of Theorem 2 was not fitted or validated.
5. **Cost gate not restored.** The total-token cost-savings gate was suspended when the guide path changed and was not reinstated. On the available guide-output meter, diagnosis-based guidance arms (≈123.2) were not cheaper than takeover (≈33.5), so the current data provide no basis for a cost-efficiency claim.
6. **The gate did not exercise "when to ask".** Gated arms paid on all 21 prefixes, and prefixes were attempt-1-fail snapshots only; the gated arms behaved close to fixed-timing policies.
7. **Narrow setting.** One executor, one guide model, synthetic tasks, and an estimated rather than billed token meter limit external validity.

### 6.3 What remains useful

The formulation separates three questions that mid-run routers conflate—whether to intervene, what to send, and whether the message is still valid—and gives each an operational definition (signed gain, execution-defined distortion, `applicable_if`). The preregistered harness, including the VD_enc arm added to keep the encoder contrast free of takeover, and the reporting of takeover rates, provide a template for testing such claims without letting upgrade routing masquerade as guidance. The stale-discard mechanism ran with a low confirmatory stale rate (4.76%) and is a practical engineering component. Larger and more realistic task pools, a gate with genuine abstention, a message family with real length–quality trade-offs, the preregistered logistic analysis, and a restored cost meter are the next steps needed before any of the theoretical predictions can be tested with adequate power.

---

## 7. Conclusion

We framed small→large model guidance during code repair as decision-oriented asynchronous rate–distortion control and stated two theoretical results: a Gibbs/Blahut–Arimoto encoder for a fixed receiver and a finite optimal guidance length under an exponential staleness model. In a preregistered, underpowered study, long structured guidance substantially improved a frozen 0.5B executor's success, while the rate–distortion encoder added only a small directional increment over fixed long guidance, the full method's success came from takeover, and length–delay predictions were not tested with adequate power. The theory remains a hypothesis-generating framework; establishing its empirical value requires larger studies.

---

## References

- [SWE-Router] SWE-Router. arXiv:2607.00053v1. https://arxiv.org/html/2607.00053v1

*(Other related areas are discussed by named concept only; no further bibliographic entries are given in this draft.)*

---

## Appendix A. Artifacts and preregistration

- Preregistration: `/workspace/voi-delegate/PREREGISTRATION.md`
- Deviations log: `/workspace/voi-delegate/DEVIATIONS.md`
- Claim boundary: `/workspace/voi-delegate/results/CLAIMS_BOUNDARY.md`
- Capability gap: `/workspace/voi-delegate/results/capability_gap_grok46.md`
- Calibration: `/workspace/voi-delegate/results/calibration/cal_summary.md`
- Encoder fit: `/workspace/voi-delegate/results/encoder/summary.md`
- Gate fit: `/workspace/voi-delegate/results/gate/summary.md`
- Confirmatory: `/workspace/voi-delegate/results/confirmatory/summary.md`, `ABLATION_NOTE.md`
- Theory note: `/workspace/proposals/delegation/voi-delegate-theory-astra.md`
