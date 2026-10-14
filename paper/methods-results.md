# VoI-Delegate — Methods and Results

> Draft sections only. Confirmatory analyses are **underpowered** (7 tasks). Claims follow `CLAIMS_BOUNDARY.md` (2026-10-14).

---

## Methods

### Models and tasks

The executor was a frozen small code model, `Qwen2.5-Coder-0.5B-Instruct` (Hugging Face snapshot `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`), run on CPU in fp32 with sampling temperature 0.7, `top_p=0.95`, and `max_new_tokens=256`. Attempt seeds were fixed so equal seeds produced byte-identical rewrites. Each episode allowed up to \(K=4\) rewrite attempts with early stopping when a visible unit test passed; terminal success required hidden tests to pass on the final code.

The guide was invoked via Cursor Agent CLI version `2026.10.01-e373342` with the pinned headless command

```text
agent -p --mode=ask --model grok-4.6 --output-format text --workspace <empty-temp-dir> "<prompt>"
```

`--mode=ask` kept the guide read-only. The guide returned a single structured JSON diagnosis with fields `location`, `cause`, `change`, `verification`, and `applicable_if` (an exact code substring anchoring the request snapshot). Path A used a fresh `grok-4.6` diagnosis per calibration or confirmatory prefix; Codex CLI was uninstalled and was not used for these runs.

Tasks were synthetic single-function Python bug-fix items. We reused the fifteen difficulty-filtered tasks kept from the pilot (`T09`, `T10`, `T11`, `T12`, `T14`, `T17`, `T20`, `T26`, `T28`, `T31`, `T32`, `T33`, `T37`, `T38`, `T40`). Before calibration outcomes informed encoder or gate fitting, the pool was split into eight calibration tasks (`T09`–`T26` as listed) and seven confirmatory tasks (`T28`, `T31`, `T32`, `T33`, `T37`, `T38`, `T40`). With only seven confirmatory tasks, all confirmatory efficacy and ablation contrasts are labelled **underpowered**.

A capability-gap precheck under the same Cursor CLI / `grok-4.6` guide required guide-alone success minus frozen small-alone success to be at least 15 percentage points (pp) before the confirmatory path proceeded.

### Protocol

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

### Calibration

On \(N=24\) recoverable prefixes (eight calibration tasks × three attempt-1-fail snapshots), each prefix shared one fresh diagnosis \(z\). Forks comprised control (no guidance), each of \(m_1\)–\(m_4\) at delays \(d\in\{0,1,2\}\), and a takeover reference, for 336 forks total under common-random-number (CRN) continuations with \(S=1\) repeat per scheme. Decision distortion followed the preregistered definition \(d_h(z,m)=v_h^\star(z)-v_h(z,m)\). Encoder cost \(\widehat c_h(z,m)\) was the **post-encode** estimated token cost of the rendered message; diagnosis output tokens were a shared baseline logged once and did not alone differentiate templates.

### Encoder

An offline Theorem-1-style Blahut–Arimoto fit on finite tables estimated encoder \(e^\star\) from calibration forks. Nested holdout within the eight calibration tasks used fit tasks `T09`–`T17` (six tasks) and holdout `T20`, `T26`. Holdout selected the no-\(m_4\) family and hyperparameters \((\lambda,\beta)=(0.0,0.05)\). With \(\lambda=0\), the frozen argmax policy concentrated on fixed long \(m_3\) (22/24 prefixes), so the rate–distortion encoder risked collapsing toward signed-gate + fixed-long guidance; confirmatory evaluation therefore ablated that contrast explicitly. Per-delay discrete argmax tables were stored for Theorem-2 diagnostics but were not treated as a powered length–delay test.

A tabular gain predictor for \(\widehat\Delta\) was fit on the same calibration forks with nested holdout selecting gate penalties \(\lambda=0.001\), \(\mu=0.0\).

### Confirmatory evaluation

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

### Metrics

Primary efficacy was terminal hidden-test success. Primary cost meters were guide-call counts, post-encode message-side cost \(c_h(z,m)\), and available guide token or character fields; the formal total-token 20%/10% cost-savings gate was **not** restored for this guide path. Message dispositions (accepted / stale / not-needed) and stale-discard rate on delayed deliveries (\(d\ge 1\)) were logged. For gated arms, takeover selection rate among paid requests was always reported.

Preregistered primary analyses included a Q2 logistic regression `success ~ arm * delay + task_FE` comparing C3 vs C2. That logistic was **not run** for this draft; length–delay results below are descriptive rates only. Q3 used the paired success difference of **VD_enc** versus **G_fixL**. Wilson 90% intervals are reported where present in the result files. All confirmatory contrasts remain underpowered.

---

## Results

### Capability-gap precheck

Under Cursor CLI / `grok-4.6`, guide-alone success was **100%** (15/15 kept tasks) versus frozen small-alone **56%**, a gap of **44.0 pp**, which passed the ≥15 pp rule. The confirmatory path therefore proceeded (not an exploratory downgrade).

### Calibration success rates

Pooled over delays, calibration success rates on \(N=24\) prefixes were: control **41.7%** (10/24), \(m_1\) **43.1%** (31/72), \(m_2\) **52.8%** (38/72), \(m_3\) **77.8%** (56/72), \(m_4\) **77.8%** (56/72), and takeover **91.7%** (22/24). Because \(m_1\) was near control, short class was set to \(m_2\). Because \(m_3\) matched \(m_4\) on success while \(m_4\) had higher message cost (estimated tokens 78.8 vs 110.9), \(m_4\) was dropped from the default encode family.

By delay, long-template rates declined directionally (\(m_3\): 83.3% / 79.2% / 70.8% at \(d=0,1,2\)); short \(m_2\) was 58.3% / 54.2% / 45.8%. Status counts included 16 stale deliveries among delayed forks (~8% of delayed deliveries in calibration)—retained as a calibration observation of the applicability mechanism.

### Offline encoder

Nested holdout chose family \(m_1\)–\(m_3\) (no \(m_4\)) with \((\lambda,\beta)=(0.0,0.05)\). Frozen argmax counts were \(\{m_1:0,\,m_2:2,\,m_3:22\}\); the argmax policy on calibration (pooled) had success 0.806 and message cost 76.1, close to fixed \(m_3\) (0.778 / 78.8). Delay-conditional argmax did **not** shift mass toward shorter messages as \(d\) increased (\(d=0\): 2×\(m_2\)+22×\(m_3\); \(d=1\)–\(2\): 24×\(m_3\)). These calibration facts foreshadow a weak encoder increment and do not constitute a powered Theorem-2 test.

### Confirmatory arm rates (underpowered)

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

### Encoder increment (Q3): VD_enc only

The Q3 encoder contrast uses **VD_enc only** versus G_fixL: **84.1%** vs **81.0%**, paired mean difference **+3.2 pp** (63 pairs). The empirical increment is present but small, underpowered, and **directional only**; it is **not** a powered primary contribution. Theorem-1 empirical support therefore remains weak on this toy pool.

Full **VD** also reached **95.2%** (20/21), but `takeover_among_paid=1.0` (21/21 paid requests chose takeover). That arm therefore collapses to upgrade routing, matching C1, and is **not** treated as guidance or encoder evidence. G_fix, G_fixL, and VD_enc each had `takeover_among_paid=0` (paid schemes were short, long, and `rd` respectively).

### Length × delay (descriptive; logistic not run)

Descriptive C3×delay rates were **85.7% / 71.4% / 85.7%** at \(d=0,1,2\) (non-monotonic). C2×delay rates were 52.4% / 61.9% / 52.4%. We do **not** claim that optimal length shortens with delay, nor a powered Theorem-2 result, from these rates or from calibration discrete argmax. The preregistered confirmatory logistic interaction was not computed for this write-up.

### Stale discard

On confirmatory delayed deliveries, stale rate was **4.76%** (10/210), below the 5% threshold. The applicability / stale mechanism remains in the protocol and is reported as an **engineering detail**, not a headline contribution. Calibration stale count (16 among delayed forks) is noted above as a calibration observation only.

### Cost meters

Guide-call behavior on gated confirmatory arms was uniform at the paid-request level reported above (21 paid requests per gated arm on 21 prefixes under the fitted gate). Available mean guide-output estimates in the confirmatory summary were 0 for C0, ≈33.5 for C1 and full VD (takeover path), and ≈123.2 for C2, C3, G_fix, G_fixL, and VD_enc. Message-side calibration costs remained those in the encoder fit (\(m_2\) ≈50.1, \(m_3\) ≈78.8 estimated tokens). No total-token cost-savings gate or threshold claim is made; that gate was not restored for the Grok-era meter.
