# Stage 2：信息论编码与异步委派的可执行实现

这里交付完整的 Python 实现：消息编码、执行分叉校准、逐步调用门控、真实并发执行、推测修改、消息融合，以及配对实验。论文指标是固定截止时间下的成功率、完成时间和信息论机制与异步机制的交互效应。代码没有把 token 节约作为研究目标。

要求 Python 3.11+、Linux/macOS。核心实现和测试只使用标准库，不修改 Stage 1 代码。命令在仓库根目录运行。

## 1. 立即运行

~~~bash
python -m unittest discover -s tests_stage2 -v
python -m voi_async demo --out results_stage2/demo
~~~

demo 会实际创建代码工作区、执行 Python 测试、采集每条完整消息的反事实分叉、拟合预测器，再运行四个实验分支。结果保存在 calibration.json、values.json、四份逐事件轨迹和 summary.json。

**demo 使用确定性的合成模型，不下载或调用真实大模型。它证明运行链路和并发机制可执行，不证明论文效果。** 为隔离运行机制，demo 显式使用固定请求时点和 argmax 编码消融；正式 evaluate 默认使用随机 Gibbs 编码。

## 2. 代码入口

| 文件 | 已实现内容 |
|---|---|
| voi_async/information.py | 完整载荷前缀码、稳定 Gibbs 编码、有限字母表 Blahut–Arimoto、互信息分解 |
| voi_async/learning.py | 请求侧特征、岭回归、任务级交叉拟合、到达价值和调用增益预测器 |
| voi_async/calibration.py | 多个公开决策前缀、控制延迟、相同续执行种子下的消息／无消息执行分叉 |
| voi_async/planning.py | 贝叶斯诊断信念、期望信息增益、推测动作排序、锚点融合判定 |
| voi_async/runtime.py | 非阻塞请求、持续小模型执行、工具边界融合、截止时间、取消和事件记录 |
| voi_async/environment.py | 隔离工作目录、精确匹配修改、多文件原子补丁、推测修改提交／回滚 |
| voi_async/models.py | 大小模型进程接口、严格 JSON 协议、超时和进程组清理 |
| voi_async/hf_backend.py / hf_worker.py | 常驻独立 Transformers 进程、模型预加载、种子固定、可取消生成 |
| voi_async/http_worker.py | 可直接使用的 OpenAI 兼容 HTTP 接口，支持本地模型服务 |
| voi_async/evaluation.py | 同步／异步 × 固定／信息论消息的配对实验、任务簇 bootstrap |
| tests_stage2/ | 数学解、完整载荷、并发、不泄漏、事务、真实进程及 HTTP 协议测试 |

没有以 TODO、NotImplementedError 或随机成功标签替代算法。Protocol 中的抽象类型声明对应下方实际适配器；Fixture 类明确只用于合成集成验证。

## 3. 信息论算法对应的目标

令 x 为请求时公开状态，z 为大模型诊断，m 为包含字段内容、锚点和版本的完整消息。预测器估计

\[
\widehat V(x,m,\tau,b)
\approx
\Pr(Y=1\mid x,\operatorname{do}(m\text{ 延迟 }\tau\text{ 到达}),
\pi_{\rm async},b).
\]

它从真正执行的续轨迹得到标签；不读取接收端尚未发生的状态。异步期间的工作、消息过期、融合和剩余时间对成功的影响都进入这个条件结果。当前特征模型是可替换的轻量基线，不假设它已准确恢复条件概率。

用同一候选集的最佳预测值作共同参照：

\[
\widehat d(x,z,m,\tau,b)
=\max_{m'}\widehat V(x,m',\tau,b)-\widehat V(x,m,\tau,b).
\]

部署编码器求解

\[
\min_{e:\operatorname{supp}(e)\subseteq\mathcal M(x,z)}
\sum_m e(m)\widehat d(m)
+\beta D_{\rm KL}(e\Vert q).
\]

其中 q 是定义在所有有限字节串上的完整参考分布。实现使用 Elias gamma 长度头加原始消息字节的可解码前缀码：

\[
\ell(m)=2\lfloor\log_2(|m|+1)\rfloor+1+8|m|,
\qquad q(m)=2^{-\ell(m)}.
\]

固定参考分布时，精确解是

\[
e^*(m)=
\frac{q(m)\exp[-\widehat d(m)/\beta]}
{\sum_{m'\in\mathcal M(x,z)}q(m')\exp[-\widehat d(m')/\beta]}.
\]

代码使用 log-sum-exp，默认从分布采样，并实际编码／解码所选完整载荷。对于任意可行 e，将其代入目标并减去最优目标，恰好得到 \(\beta D_{\rm KL}(e\Vert e^*)\geq0\)，因此这是固定候选集与预测失真下的最优解。**该结论不意味着整个序贯委派策略最优。**

互信息与所用代理目标的区别也保留在代码中：

\[
\mathbb E_{z\mid x}D_{\rm KL}(e(\cdot\mid x,z)\Vert q)
=I(Z;M\mid X=x)+D_{\rm KL}(p_M(\cdot\mid x)\Vert q).
\]

日志中的 rate_upper_bound 是参考 KL 上界，单位 nat，不能改称实测互信息。wire_bits 是完整载荷的码长，不是大模型生成 token 数。通用字节参考分布比较保守，本身具有长度偏好；需要通过等载荷对照、beta 扫描与消融证明到达失真项有贡献。

blahut_arimoto 是另一个完整实现：输入固定公开状态下的诊断源分布和完整消息失真矩阵，交替优化条件信道和边缘分布，求解 \(E[d]+\beta I(Z;M)\)。它支持不可用消息的无穷失真。部署时使用上面的固定参考版本，不把有限表上的 BA 结果冒充开放文本信道的精确解。

### 调用门控与校准

每个可决策的公开状态都计算

\[
\widehat\Delta(x,\hat\tau,b)
\approx \mathbb E_{m\sim e_\beta}[Y_m\mid x]-\mathbb E[Y_0\mid x].
\]

这是“救回概率减改坏概率”的净结果差估计，不需要假装能够观察单次任务的两个潜在结果。代码在可执行分叉中估计期望差；共享随机种子是降方差方式，不使真实模型服务必然确定。

调用条件为预测增益超过 threshold 且剩余时间超过延迟预测。调用前看不到诊断；请求后，大模型只见冻结的请求快照。编码使用已观测的大模型服务时长，不将未来服务时间偷用于调用门控。

fit_values 按任务留一交叉拟合：使用其他任务训练编码价值模型，在留出任务上以其输出分布加权实际消息分叉结果，再构造门控标签。这里的 cross-fitting 减少同任务选择偏差，**不是无偏性或校准性的保证**；仍需验证集校准和任务／仓库隔离。

默认每个任务最多调用一次，但调用时点是逐步决策的；Config 支持多个请求，单个 guide 请求在途。现有校准目标是单次请求续策略，不能将其直接宣称为多次请求最优价值。多次请求实验需要重新采集对应续策略数据。

## 4. 完整异步执行协议

1. 在动作边界估计增益，创建独立 guide task，并冻结请求状态。
2. guide 在后台运行；executor proposal 和工具任务继续执行。主循环用 asyncio.wait(FIRST_COMPLETED)，不是预先写好的延迟回放。
3. 工作选择使用保留概率 × 进展值 + 期望信息增益 − 冲突风险。未提供离线工作标签时，使用明确记录的依赖启发式，信息增益为零；不会用手填概率假装已校准。
4. 在途修改暂存；公共主状态保持可核验。原子 patch 可同时修改多个文件，避免必须让每个中间修改单独通过全部测试。
5. 消息返回时取消依据旧指令生成中的 proposal，等待当前工具的修改边界，再验证暂存补丁。通过公开测试后提交，否则回滚或报告冲突。
6. 锚点仍唯一时应用或重定位消息；锚点过期时重新测试，已解决则丢弃，否则丢弃过期消息。融合器不假装具备语义正确性 oracle。
7. 后续 executor 同时读取当前代码和已融合指令。大模型不直接覆盖代码、不接管执行。
8. 截止时间取消并回收本地模型／工具进程；日志明确区分本地取消和未确认的远程服务取消。隐藏测试仅在提交后评价，结果不返回策略。

read、test、edit、patch、wait、submit 都实际实现。修改使用唯一旧文本的 compare-and-swap；跨文件修改用一个 patch 原子提交。当前环境处理给定任务的文本文件和测试命令，不是完整 SWE-bench Docker harness，也不提供 OS 级安全沙箱。任务测试在临时目录的副本中执行，依赖须已安装。

## 5. 连接真实大小模型

**默认实验组合与仓库既有模型对齐：Cursor CLI 的 grok-4.6 + 本地 Transformers 的 Qwen/Qwen2.5-Coder-0.5B-Instruct。** 配置入口为 examples_stage2/models.cursor-qwen.json。

~~~bash
python -m pip install -e '.[local]'
agent --version
~~~

Cursor 需要已安装并完成认证；运行器直接复用现有登录或 CURSOR_API_KEY，不自动启动登录。默认从 PATH 解析 agent；如使用原实验机器的安装路径，设置 VOI_GUIDE_BIN=/home/box/.local/bin/agent，或在 guide 配置添加 binary。实际调用固定为：

~~~text
agent -p --mode=ask --model grok-4.6 --output-format text \
  --workspace <empty-temp-dir> --trust "<JSON prompt>"
~~~

进程 cwd 和 --workspace 都是同一个新建空临时目录，ask 模式只生成诊断。任务代码由公开快照放入提示，不将仓库作为 Cursor 工作目录。--trust 信任的是这个临时工作目录。Cursor 的 seed 仅进入提示；其采样使用 CLI 默认值，不能宣称与相同种子必然字节一致。

本地 Qwen 的模型与快照固定为：

~~~text
Qwen/Qwen2.5-Coder-0.5B-Instruct
revision: ea3f2471cf1b1f0db85067f1ef93848e38e88c25
CPU float32, threads=6, temperature=0.7, top_p=0.95, max_new_tokens=256
~~~

上述模型 ID、快照和采样参数对齐原实验。**Stage 2 的动作 JSON 提示与原实验的完整代码重写提示不同，不能直接复用旧成功率或旧校准值。** 0.5B 生成无效或截断 JSON 时会记录 executor_error，不用合成答案兜底；应先检查真实模型协议成功率，再跑正式实验。

HFProcessModel 在独立常驻进程中加载 tokenizer／权重并执行采样；主 asyncio 进程只负责通信与调度。CLI 在任务计时前预加载一次，日志记录模型参数和实际 torch／transformers 版本。取消过时 proposal 时发送 SIGUSR1，StoppingCriteria 在 token 边界终止并排空旧响应，保留已加载权重；超过 cancel_grace 未响应则杀死并回收进程，下次调用重新加载。后者若发生在任务中，重新加载时间计入任务预算。任务结束及异常退出都会关闭模型进程。

配置 local_files_only=true 可限制使用已缓存的权重；默认 false 允许首次获取固定快照。首次准备耗时不进入单任务完成时间，应作为独立部署初始化成本记录。deadline、expected_delay 和超时需要根据真实 Cursor 服务延迟及 CPU 推理速度设定，示例中的数值不是实测延迟。

examples_stage2/models.openai.json 是可选部署：小模型使用 OpenAI 兼容的本地 0.5B 服务，大模型仍使用 Cursor Grok 4.6。key_env 只指环境变量名，不在配置、消息或日志写密钥。

HTTP 适配器已经实现请求、响应解析、超时及本地取消；不需要另外写桥接脚本。协议要求服务支持 chat/completions 及配置中的参数。服务不支持 JSON response_format 时，保持 json_mode=false；不支持其他参数时需在 http_worker.py 对应 provider 调整。

也支持现成 CLI：

~~~json
{
  "executor": {"kind": "command", "argv": ["/absolute/path/to/small-model-json-cli"], "mode": "stdin", "timeout": 120},
  "guide": {"kind": "command", "argv": ["/absolute/path/to/large-model-json-cli"], "mode": "stdin", "timeout": 120}
}
~~~

stdin 模式接收一个 JSON 对象，argument 模式把相同 JSON 作为最后一个参数。进程 stdout 必须返回一个 JSON 对象。模型输入含 instruction、seed、snapshot；executor 另有 guidance。模型应该只生成 JSON，由本运行器执行工具。

大模型输出 location、cause、change、verification 四个非空字符串及 anchors 字典。小模型输出 actions 列表，每个动作对应上述六种类型。详细字段由 models.py 中的实际提示与 types.py 校验定义。

### 采集、拟合、部署与评估

示例任务文件包含真实可执行的小程序，但仍只是接口示例。论文应替换为按仓库／任务族拆分的数据。

~~~bash
python -m voi_async collect \
  --tasks examples_stage2/calibration.tasks.json \
  --models examples_stage2/models.cursor-qwen.json \
  --prefix-steps 0 2 4 --delays 0.5 2 5 --seeds 0 1 2 \
  --deadline 60 --max-steps 50 \
  --out results_stage2/calibration.jsonl

python -m voi_async fit \
  --data results_stage2/calibration.jsonl \
  --beta 0.0001 --threshold 0.01 \
  --out results_stage2/values.json

python -m voi_async run \
  --tasks examples_stage2/evaluation.tasks.json \
  --models examples_stage2/models.cursor-qwen.json \
  --values results_stage2/values.json \
  --mode async --message-mode info --deadline 60 \
  --expected-delay 2 --out results_stage2/live

python -m voi_async evaluate \
  --tasks examples_stage2/evaluation.tasks.json \
  --models examples_stage2/models.cursor-qwen.json \
  --values results_stage2/values.json \
  --deadlines 30 60 120 --seeds 0 1 2 \
  --expected-delay 2 --out results_stage2/factorial
~~~

collect 在公开测试失败之后，以及指定数量的小模型公开动作之后采样状态。每个状态先获取一个真实诊断，再缓存这个诊断，对五种完整消息做控制到达延迟的真实 executor 续执行。每个状态／延迟／种子约运行六条续轨迹，必须把它的计算量算入校准实验。teacher_service_time 单独记录；控制延迟不被误报为真实大模型速度。

collect 的 deadline 是该前缀之后的剩余预算。默认固定一个剩余预算；需要覆盖多种预算时分别采集后合并 JSONL。collect 在不同前缀调用真实 guide，不能从 hidden_test 读取诊断。

run 使用门控策略；evaluate 为隔离两个机制使用相同起始请求时点、相同一请求预算，随机化四个分支的执行顺序。其主报告是：

\[
J=[S_{\rm async,info}-S_{\rm async,fixed}]
  -[S_{\rm sync,info}-S_{\rm sync,fixed}].
\]

同时报告每个截止时间下的成功率、将失败记为截止时间的受限成功等待时间，以及大模型在途期间完成的非 wait 工具数量。后者只是重叠工作量，不能自动等同于有效进展。置信区间按任务簇 bootstrap，不把多个随机种子当独立任务；样本不足时不生成区间。

evaluate 检验消息机制与异步机制的交互；它不替代门控质量实验或外部方法复现。SWE-Router、STEPGATE 等命名基线没有被伪造为已复现的算法。

### 工作信息增益的校准输入

run 可加 --work-records 指向 JSON 数组。每条记录需要：

~~~json
{"hypothesis":"boundary_error","family":"test:","outcome":"test:fail","keep":1.0,"progress":0.2,"conflict":0.0}
~~~

hypothesis 是离线诊断标签，outcome 必须是实际可观测的 kind:ok 或 kind:fail。keep／progress／conflict 必须来自另行定义并测量的执行分叉指标，范围 [0,1]。示例只是格式，不能充当论文标注。Belief.fit 进行平滑似然估计，在线用实际工具观察做贝叶斯更新并计算期望信息增益。

## 6. 复杂度与实验边界

每个请求 K 个候选、D 维特征、总消息字节数 L：价值打分 O(KD+L)，Gibbs O(K)，编码 O(L)。当前 K≤5、D=48。BA 在 Z 个源符号、M 个完整消息、T 轮下为 O(TZM)。岭回归 N 条样本开销 O(ND²+D³)；按 J 个任务留一拟合当前实现约放大 J 倍。

每个运行器同时最多一个 guide、一个 executor proposal 和一个工具任务；可变状态只在工具／融合边界更新。运行日志与代码、测试输出大小相关；所有事件均保存输入／状态哈希及消息载荷，便于核对顺序。

需要明确保留的研究边界：

- 当前到达价值是轻量预测器；未证明能在真实大任务泛化，也未验证比不确定性阈值更优。
- 默认通用字节参考分布很保守，实际消息候选来自五种字段组合；更丰富的语义消息生成与参考分布可通过同一接口替换，但现有结果不能声称已实现语义最小充分编码。
- 推测工作启发式、精确锚点融合、公开测试通过均不是全局语义正确性保证。
- 相同任务 ID 被禁止同时用于校准与评价；相似任务、仓库泄漏仍需要数据划分者处理。
- 当前提供核心调度器与测试执行环境；接入 TwinRouterBench 必须有可执行快照和续执行接口，仅有逐步档位标签不足以离线识别新异步策略的因果收益。
- 实测模型效果以新 collect/run/evaluate 的输出为准。仓库中的合成 demo 不支持“成功率提高”或“显著交互”的论文陈述。
