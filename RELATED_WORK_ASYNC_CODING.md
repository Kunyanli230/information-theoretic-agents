# 异步算法与 coding agent：相关工作及当前方案的创新边界

检索日期：2026-10-15。比较对象是本项目当前 `voi_async/batch.py` 的跨题调度版本；本文是定向相关工作检索，不是系统综述，也不能作为不存在其他先例的证明。

## 结论

**已有多篇实质相关工作。“异步 + coding agent”“等待 A 时执行 B”“强模型异步给弱模型建议”分别已有先例。** 当前实现应先作为工程基线，不能仅凭使用异步、保存任务状态和恢复执行就声称新的算法。

最需要对照的是 **AsyncTool、AsyncFC、CoMIC、SICA、Agentix/Autellix、ThunderAgent、Coda**。其中 AsyncTool 的任务切换例子几乎就是我们讨论的 A/B 流程；AsyncFC 已经在 SWE-agent 上测量异步执行的速度与解题质量；CoMIC 和 SICA 分别覆盖了大小模型异步指导、coding agent 异步监督。

在本次已核对的论文中，尚未看到完整复现我们当前全部约束的方案：**一个小模型执行槽、一个黑盒大模型指导槽、多个独立代码任务、动作边界切换、指导预取、以固定总时间内通过验证的任务数为目标。** 这只是尚未找到完全相同组合，不能直接转化为创新性结论；这些机制的简单组合也未必足以构成论文贡献。

## 我们当前究竟实现了什么

根据 `voi_async/batch.py` 核对：

1. 每题维护独立的代码环境、观察、指导消息和状态；整个批次共用一个截止时间。
2. 最多同时运行一个 Qwen 执行动作和一个 Grok 指导请求。A 等指导时，Qwen 可以处理独立题 B。
3. 指导返回后，A 进入 `ready_guided`。Qwen 当前动作完成并执行公开测试后，再优先选择已获指导的题；不打断正在进行的生成。
4. 无指导尝试未通过公开测试的题进入求助队列；导师空闲且没有待求助题时，可提前指导尚未开始的小模型任务。
5. 候选修改经公开测试后提交；隐藏测试在批次结束后审计，不参与在线调度。

这里的“恢复”是恢复任务及其代码/观察状态并发起下一次生成，**不是**恢复被中断 token 生成的 KV 状态。当前优先级主要是固定规则，没有实现学习式或具有最优性保证的调度策略。

论文主指标应是 `Q(T)`：截至实际墙钟时间 T 已完成、且在独立质量审计中合格的任务数量，同时报告最终通过率和完成整批的时间。不能把输出吞吐率、动作数或任务切换频率直接当作合格任务吞吐率；不以 token 消耗作为本研究的讨论目标。

## 最接近的工作

“arXiv”表示本次只核实了预印本状态，不表示断言其未在任何会议录用。日期为首次预印本日期；阅读的版本及作者见配套书目。

| 工作与来源 | 核对到的机制和评估 | 与我们的重合及差异 |
|---|---|---|
| **[AsyncTool](https://arxiv.org/abs/2605.27995)**，2026-05-27，arXiv | §2.1 明确描述：任务 A 的工具结果未返回时切换到独立任务 B；结果就绪后恢复 A。由 BFCLv3/NESTFUL 构建多任务 benchmark，模拟工具延迟，测正确性、任务状态维护和交错行为。 | **跨题等待/切换/恢复的直接先例。** 主要评价模型自身协调工具调用的能力；我们由外部调度器隔离任务状态，并加入异构导师，且要实际测量代码任务完成吞吐。 |
| **[AsyncFC: Concurrency without Model Changes](https://arxiv.org/abs/2605.15077)**，2026-05-14，arXiv | 执行层把长耗时调用表示为 symbolic futures，解码无需阻塞；在轮次边界注入结果，按读写依赖调度函数。§3.5 将外部 LLM 思考也作为异步工具。§5.3/图5：SWE-bench Lite 300题，SWE-agent 原始基线解题率79.0%，AsyncFC79.3%，报告相对原始基线1.40×端到端加速。 | **最直接的异步 coding agent 加速对照之一。** 不能把“推理模型也是异步工具”作为独有机制。其核心是 future-aware 上下文和依赖执行器；我们是跨独立任务、单小模型与单导师的队列调度。 |
| **[CoMIC](https://arxiv.org/abs/2606.00756)**，2026-05-30，arXiv | §4.3–4.4：本地弱 agent 执行，云端强 critic 异步评估上传的轨迹、蒸馏经验，并回传按语义子目标索引的 Global Guidance；不更新模型权重。实验包括 Mistral-7B 弱 agent、deepseek-chat 云端 critic，五类长程 AgentBoard 环境。 | **大小模型异步指导的直接先例。** 重点是已完成子目标的经验与跨 agent 指导流转，本地不阻塞；不是等待某题诊断时切去另一题的 coding 调度。不能声称首次无训练的云端导师/本地执行者架构。 |
| **[SICA: A Self-Improving Coding Agent](https://arxiv.org/abs/2504.15228)**，2025-04-21，arXiv | §3.1 的 asynchronous overseer 在并发线程中周期运行，默认每30秒检查执行轨迹，可向执行 agent 上下文插入建议，严重时取消执行。论文主体研究 agent 自我改进，包含 SWE-bench Verified 等评估。 | **coding agent 接受异步 LLM 监督已有实现。** 不是专门优化独立题队列的吞吐，也不等于固定一大一小的跨题求助恢复。其投稿说明不能当作正式录用证明。 |
| **[Agentix / Autellix](https://arxiv.org/abs/2502.13965)**，**NSDI 2026** | 以整个多次调用的 agent 程序作为调度单位，跟踪程序历史、执行服务量和关键路径，支持程序间调度与抢占，研究给定延迟下程序完成吞吐。arXiv 原题为 Autellix；[NSDI 论文页面](https://www.usenix.org/conference/nsdi26/presentation/luo)使用 Agentix。 | **程序级调度而非孤立请求调度已有强先例。** 主要位于服务引擎与资源调度层；我们还需解决代码质量、求助路由、指导预取对任务完成数的影响。 |
| **[ThunderAgent](https://arxiv.org/abs/2602.13692)**，2026-02-14，arXiv | §4 将 agent 抽象为 LLM Programs；全局等待队列、Pause/Restore、KV 管理及工具环境异步准备。评估包含 SWE-Agent/OpenHands 在 SWE-bench 上的 coding 工作负载。 | **coding workflow 的暂停、恢复、资源重叠和吞吐优化都有先例。** 重点在推理后端与工具资源；我们的恢复不包含 KV 恢复，不能拿应用层任务状态保存与其当作同一实现能力。 |
| **[Coda](https://arxiv.org/abs/2610.03088)**，2026-10-02，arXiv | 最新相关工作。针对 coding-agent session 在 LLM/工具阶段间交替，采用分层 aging 准入、兼容性感知执行和状态感知路由；区分“请求已就绪”和“现在应进入执行”。正文明确使用 trace 分析与 trace-driven replay。 | **coding agent 的何时恢复、何时准入已被专门研究。** 优化对象主要是 KV/注意力/服务资源，不能把其回放中的服务吞吐直接理解为新题通过率或我们真实 Grok 调用的结果。 |
| **[CAID: Effective Strategies for Asynchronous Software Engineering Agents](https://arxiv.org/abs/2603.21489)**，2026-03-23，arXiv | 中央 manager 按依赖规划，多 engineer 在隔离工作区并行，实现 branch/commit/merge 与可执行测试整合；评估 Commit0 和 PaperBench。 | **异步软件工程协作的直接同领域先例。** 同一大任务的依赖子任务、多执行者，与我们一个执行者轮转多个独立题不同。论文质量提升也不能自动当作所有设置下的墙钟加速。 |

AsyncFC 的图5及 SWE-agent 实验来自 **2026-10-09 的 v2**，在本次检索截止日之前。其“准确率无显著差异”不是统计学上的等效性证明，也不是形式化无损保证；本文引用的是作者报告的实验结果。

## 已正式发表的基础工作也必须引用

| 工作 | 已核实状态 | 应如何比较 |
|---|---|---|
| **[AIOS: LLM Agent Operating System](https://arxiv.org/abs/2403.16971)** | **COLM 2025**，arXiv 明示 full paper | §3.3–3.4 包括 FIFO/RR、上下文 snapshot/restore；单 LLM 服务多个 agent，附录也有 HumanEval 调度实验。说明 OS 式队列和上下文切换不是新概念。其可以中断生成，我们当前只能动作边界切换。 |
| **[Speculative Actions](https://arxiv.org/abs/2510.04371)** | **ICLR 2026 Oral**，[官方页面](https://iclr.cc/virtual/2026/poster/10009726) | 快模型预测慢模型动作并提前执行，慢模型动作与预测匹配才提交，得到特定语义下的 lossless 加速。我们跨题推进 B 不要求预测 A 的指导；公开测试通过也不足以称我们的流程 lossless。 |
| **[LLMCompiler](https://arxiv.org/abs/2312.04511)** | **ICML 2024** | 规划器构建工具调用依赖 DAG，执行器并行执行独立节点。先明确跨请求/跨任务异步与单任务内部函数并行的区别。 |
| **[Parrot](https://arxiv.org/abs/2405.19888)** | **OSDI 2024** | semantic variables 暴露 LLM 应用调用依赖，支持应用层联合调度。说明保留应用语义和跨调用调度已有系统研究。 |

Agentix/Autellix 的 NSDI 状态同时核对了[作者论文列表](https://michaelzhiluo.github.io/publications.html)。USENIX 正文页面在本环境返回403，机制分析使用作者 arXiv 正文；不将未能读取的会议终版与旧预印本实验数字混用。

## 期刊检索的具体结果

本轮额外定向查询了 **IEEE TSE、ACM TOSEM、ACM Computing Surveys、JAIR、Nature Machine Intelligence** 的 Crossref 题录，并用 OpenAlex 与 arXiv 交叉核验候选。各刊仅做关键词相关性检索，没有逐篇穷尽全文；本领域还需要同时查主要会议，不能把会议论文称为期刊论文。

- **[Large Language Model-Based Agents for Software Engineering: A Survey](https://doi.org/10.1145/3796507)**，**TOSEM，2026-03-05**。Crossref 核对了标题、作者、期刊、日期和摘要。适合梳理软件工程 agent 相关工作，本身不是异步调度算法。
- **[SCG-Agent: A Scheduler-Driven Code Generation Framework with Multi-Checker](https://doi.org/10.1109/TSE.2026.3725731)**，**IEEE TSE，2026**。Crossref 核对到正式期刊题录，DOI 记录创建于2026-08-20。**本次未取得可读全文或摘要，不能据标题判断它是否异步，也不能声称它与我们相同/不同。** 应保留为后续全文核验候选；OpenAlex 给出的占位日期不能当作精确出版日期。
- Computing Surveys、JAIR、Nature Machine Intelligence 本轮返回的候选中，未确认比上述工作更接近的具体算法。这仅是此次检索结果，不意味着这些期刊不存在相关论文。

## 其他值得保留的线索

| 工作 | 用途与边界 |
|---|---|
| [MORI](https://arxiv.org/abs/2606.00866)，2026 | 利用工具调用的空闲窗口做状态卸载和准入，说明隐藏等待的系统机会；主要优化内存与服务资源。 |
| [CacheWise](https://arxiv.org/abs/2606.16824)，2026 | coding agent 的 KV 管理、前缀复用和调度；对扩展本地服务后端有价值。 |
| [SMetric](https://arxiv.org/abs/2607.08565)，2026 | session 级缓存与负载平衡，不是导师指导策略。 |
| [TraceLab](https://arxiv.org/abs/2606.30560)，2026 | 真实 coding agent 工作负载与轨迹，有助于分析等待窗口；轨迹回放不能替代实际模型解新题的质量实验。 |
| [AsynCodeBench](https://arxiv.org/abs/2609.32662)，2026 | 真实仓库的跨 agent 依赖与可执行 dependency checkers；关注协作依赖，不是独立题吞吐，适合作为扩展方向。 |
| [Asynchronous Tool Usage for Real-Time Agents](https://arxiv.org/abs/2410.21620)，2024 | 早期异步工具与事件驱动 agent 先例。 |
| [Speculative Interaction Agents](https://arxiv.org/abs/2605.13360)，2026 | 解耦推理、环境等待与推测工具调用，主要面向交互任务。 |
| [LLMs are General Asynchronous Agents](https://arxiv.org/abs/2609.35427)，2026 | AsyncLLM 支持共享记忆状态的推理协程与异步输入；主要演示视频、游戏、监控，不是黑盒导师与独立代码任务队列。 |
| [SAGA](https://arxiv.org/abs/2605.00528)，2026 | workflow-atomic GPU 调度。注意单任务延迟与总体吞吐可能冲突，不能把所有 latency 优化都视为符合本项目目标。 |

以上补充线索本轮只确认 arXiv 来源，不能一概写成已发表论文。异步训练、在线蒸馏、机器人 fast/slow control 等工作也不能不加区分地作为 coding 推理阶段的直接对照。

## 对论文定位和下一轮实验的建议

### 不宜作为主要创新声明

- 首次将异步用于 coding agent。
- 首次等待一个任务的外部结果时处理其他任务，或首次使用 ready/wait 队列恢复任务。
- 首次让强模型异步指导弱模型，或首次不训练权重就运行异步 agent。
- 因为公开测试通过，整个流程就与纯导师执行等价、具有 lossless 保证。

### 值得继续验证的研究问题

**在执行者与导师各有固定并发额度、任务难度和导师延迟不确定、且必须保持解题质量的条件下，如何在线决定独立尝试、请求指导、预取和恢复顺序，最大化截止时间内合格任务数？**

这比“异步运行两个模型”更明确，但目前只是研究问题。需要给出能胜过简单队列的策略及证据，而不是换一种说法包装现有优先级。

当前真正需要解释的决策包括：导师是先指导已失败任务，还是预取未开始任务；执行者是优先消化已返回指导，还是先完成预计很快的独立题；在临近截止时间时，哪些指导仍来得及转化为合格提交。策略可以从可测的延迟、公开反馈、任务进度出发，本轮不依赖信息论门控。

### 最小可信实验对照

1. 同一个导师模型独立串行解题；同一个小模型独立解题。
2. 大小模型同步协作；与异步版本保持相同的模型、初始任务集合、并发额度、生成参数和质量评估口径。
3. 简单 work-conserving 跨题队列；再分别增加指导优先、预取及新的调度策略，拆开测量增益。固定单个执行槽时，“有多个上下文”不能等同于“多个小模型并行推理”。
4. 对最接近的 AsyncTool/AsyncFC 机制设计可运行对照，明确移植条件；服务引擎方案若无法复现，应说明所需后端条件，不能声称已实验击败。
5. 主图报告多个墙钟预算下的 `Q(T)` 和质量。记录本地执行者空闲、导师空闲、指导就绪后等待执行的时间，区分节省等待与改变求解路径带来的效果。
6. 在更多题与真实仓库问题上做固定配置的重复实测，不靠挑 seed。远程服务延迟波动可通过交错运行/重复批次估计；保留模型版本、失败调用、超时和事件时间线。隐藏评估耗时若置于批次之后，所有方法一致处理并另外列出。
7. 回放可以诊断调度，必须单列；真实端到端实验用于验证质量和实际吞吐，不能把两者混为同一证据。

目前112.87秒与纯 Grok 154.37秒的10题结果只支持“这组实际运行中跨题流水线有收益”。十题、单次测量、不同求解路径，尚不足以证明稳定加速、普遍同质量，或相对上述研究存在新算法贡献。

## 检索与证据边界

检索词包括 asynchronous agent/tool calling、coding-agent scheduling、small/large model asynchronous guidance、program/session-aware serving、software engineering asynchronous agents。使用 arXiv API/摘要/HTML 正文、Crossref、OpenAlex、会议官方题录及作者页面核验。通用搜索仅用于发现线索，关键结论回到一手来源。

AsyncFC、AsyncTool、CoMIC、SICA、Autellix、ThunderAgent、Coda、CAID、AIOS、Speculative Actions 等核对了正文中的对应机制；期刊综述只核对题录与摘要，SCG-Agent 仅核对题录。未取得全文、页面受限、检索索引不全均会影响覆盖，本文不作“全网没有同类工作”的断言。

配套机器可读书目：[papers.json](research/async_coding_agents/papers.json)；BibTeX：[references.bib](research/async_coding_agents/references.bib)。保留所读版本号，以免把后续版本结果误认为最早版本已有的结果。
