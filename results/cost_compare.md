# VoI-Delegate pilot：大模型 token 成本对比 / Big-model token cost compare

来源：既有 `pilot.json` + `guide_cache/`，**未新跑 Codex**。计费按预注册：`input_tokens + output_tokens`；同一 snapshot 的指导缓存生成一次，但每个消费该指导的 fork 按预注册计一次费。

Source: existing pilot data only; no new Codex calls. Billing follows prereg (per-fork consumes cached guide bill).

---

## 1. 两列分开：成本上界 vs 中途升级

### 列 A｜纯强模型从零解题（成本上界）

- **定义**：能力差预检 guide-alone；`kind=takeover`, `key=["pre", tid]`；无小模型。
- **n** = 15 tasks；**成功率** = 100%（15/15）

| 指标 | input | output | **total** | cached_input | reasoning_out |
|---|---:|---:|---:|---:|---:|
| sum | 216,307 | 955 | **217,262** | 168,576 | 278 |
| mean / task | 14,420.5 | 63.7 | **14,484.1** | 11,238.4 | 18.5 |
| median / task | 14,171 | 59 | **14,234** | 13,696 | 13 |

### 列 B｜大模型接管 A1（中途升级）

- **定义**：snapshot 上小模型 attempt-1 失败后，guide 返回完整修正代码；`arm=A1`。
- **n** = 45 snapshot forks；**成功率** = 95.6%（43/45）

| 指标 | input | output | **total** | cached_input | reasoning_out |
|---|---:|---:|---:|---:|---:|
| sum | 638,623 | 3,140 | **641,763** | 600,960 | 928 |
| mean / fork | 14,191.6 | 69.8 | **14,261.4** | 13,354.7 | 20.6 |
| median / fork | 14,170 | 61 | **14,231** | 13,696 | 13 |

---

## 2. 主表：各臂 mean billed tokens 与相对「纯强从零」的比率（显眼）

**比率** = 该臂 mean guide tokens（per fork）÷ 纯强从零 mean tokens（per task）。

| 臂 | 单位 | n | 成功率 | mean input | mean output | **mean total** | **÷ 纯强从零** |
|---|---|---:|---:|---:|---:|---:|---:|
| A0 不指导 | per fork | 45 | 40.0% | 0.0 | 0.0 | **0.0** | **0.000×** |
| A1 大模型接管 | per fork | 45 | 95.6% | 14,191.6 | 69.8 | **14,261.4** | **0.985×** |
| A2 短提示 (dany) | per fork | 135 | 60.0% | 14,346.7 | 63.2 | **14,409.9** | **0.995×** |
| A3 长结构化 (dany) | per fork | 135 | 73.3% | 14,200.6 | 133.2 | **14,333.8** | **0.990×** |
| 纯强从零 (precheck) | per task | 15 | 100.0% | 14,420.5 | 63.7 | **14,484.1** | **1.000×** |

解读：A1 / A2 / A3 相对纯强从零的比率均在 **0.98–0.99×**，几乎无节省——见下方脚注。

---

## 3. 唯一缓存调用（对照，非预注册主口径）

若同一 snapshot 的指导只计费一次（跨 fork 共享生成）：

| 调用类型 | n unique | sum total | mean total |
|---|---:|---:|---:|
| 纯强从零 | 15 | 217,262 | 14,484.1 |
| A1 takeover | 45 | 641,763 | 14,261.4 |
| A2 short | 45 | 648,446 | 14,409.9 |
| A3 long | 45 | 645,023 | 14,333.8 |

主表仍以预注册 per-fork 计费为准；本表仅说明「生成一次、多 fork 复用」时的真实 API 调用量。

---

## 脚注：CLI 固定开销（测量工具问题，不是方法失败）

- 每次 `codex exec` 的 **input ≈ 14k–15k**，其中绝大部分是 CLI 固定开销（各臂 input mean：纯强 14420、A1 14192、A2 14347、A3 14201）。
- output 只有约 50–100 tokens；可变部分被固定开销淹没。
- **因此「指导臂相对纯强从零测不到 token 节省」应记为测量工具局限（Codex CLI），不要写成方法失败的证据。**
- 若要测成本门槛，需改用低固定开销的 guide 通路（直连 API / 持久会话），属预注册修订，需 Heath 批准。

---

## 元信息

- rerun_needed: **False**（15/15 pre 任务均在 cache；45/45 A1 均匹配）
- 文件：`results/cost_compare.json`（机器可读）、本 `cost_compare.md`
