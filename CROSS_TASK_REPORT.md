# 跨题异步执行与 10 题实测

实现入口为 `voi_async/batch.py`，CLI 为 `python -m voi_async batch`。真实模型测试入口为 `examples_stage2/cross_task_benchmark.py`。

## 调度逻辑

1. 冻结 A 的公开状态，发起 Grok 指导并挂起 A；Qwen 转去执行 B。
2. 任意时刻最多一个 Grok 请求、一个 Qwen 动作。代码、反馈、指导和尝试次数按题隔离。
3. 指导就绪的题优先恢复，但当前另一题的生成和公开测试先结束；不因切题丢弃另一题的候选。
4. 导师优先处理独立尝试失败的题，空闲时为尚未执行的题预取指导，避免整条导师流水线空闲。
5. 公开测试通过后提交；失败回滚。默认每题最多一次无指导动作、一次有指导动作、一次指导请求。指导失败不阻塞其他题。
6. 全批共享 240 秒；结束后统一跑隐藏测试。隐藏结果不影响优先级、重试或终止。信息论门控不参与调度。

切换发生在动作边界，不是在生成中途保存 token 状态后恢复。模型权重常驻；各题保留的是代码、公开观察和指导状态。

## 测试设置

固定任务为 `voi.tasks.T[:10]`。Qwen 为固定 revision 的 Qwen2.5-Coder-0.5B-Instruct，CPU float32、4 threads；每次调用 seed 都为 0。指导为真实 Grok-4.6 CLI 请求，无指导回放、无 API 调用重试、无基于隐藏结果的单题重跑、无种子替换。两组使用相同完整代码输出接口、相同验证标准、相同并发上限和整批时间预算。

初版跨题调度仅在独立尝试失败后请求指导，出现导师空闲；该轮结果完整保留。最终版增加指导预取，随后用相同 10 题和 seed 重新跑一整批。串行对照采用最终代码的 `--mode sequential`，每题先等指导再执行，不切题。

## 实测结果

| 运行 | 整批墙钟秒数 | 240 秒内合格完成 | 公开通过 | 指导错误 |
|---|---:|---:|---:|---:|
| 跨题初版（失败后才请求指导） | 240.03 | 8/10 | 8/10 | 0 |
| 跨题最终版（指导预取） | 112.87 | 10/10 | 10/10 | 0 |
| 同配置串行对照 | 196.57 | 8/10 | 9/10 | 1 |

串行组 T04 的 Grok CLI 进程退出码为 1，未返回指导；T08 公开测试通过但隐藏测试失败。这两题均不计入合格完成数。两组最终合格数量不同，因此不报告完成全部 10 道合格题的加速比。

### 相同时间预算内的合格题数

| 预算秒数 | 跨题最终版 | 串行对照 |
|---|---:|---:|
| 30 | 2 | 1 |
| 60 | 5 | 3 |
| 90 | 7 | 3 |
| 120 | 10 | 5 |
| 180 | 10 | 7 |
| 240 | 10 | 8 |

最终跨题有 10 次在另一题指导在途时派发本地工作、6 次指导就绪后的恢复。执行器动作忙碌率为 99.8%，串行为 17.5%；这里统计生成加公开验证的动作墙钟时间，并非硬件利用率。

### 实际恢复记录

| 题目 | 指导就绪后等待恢复的秒数 |
|---|---:|
| T01 | 18.67 |
| T02 | 8.63 |
| T06 | 5.76 |
| T05 | 14.66 |
| T09 | 25.70 |
| T10 | 13.90 |

恢复等待来自当前动作尚未结束或已有指导就绪题排在前面。该策略优先保证已有候选完整执行，没有实现生成中途的缓存暂停／恢复。

## 验证与结果边界

55 项回归测试通过，包括等待 A 时执行 B、指导返回后优先恢复 A、后续指导预取、单模型与单导师并发上限、题目隔离、指导失败隔离、全局截止时间与取消清理、隐藏质量评价不回流策略。编译及 CLI 参数检查通过。

这些是同一小题集、同一 seed 的实测，不是一般任务上的稳定加速保证。两组现场请求的 Grok 指导文本与服务时延不同，本地推理延迟也会波动；初版与最终版之间的差异不能全部归因于预取。同质量按相同隐藏测试全部通过定义，主结果为相同墙钟预算内的合格完成数。

## 数据与复现

- [汇总 JSON](reports/cross_task/summary.json)
- [30 条逐题记录 CSV](reports/cross_task/task_results.csv)
- [按时间预算统计的完成数 CSV](reports/cross_task/deadline_curve.csv)
- [聚合脚本](reports/cross_task/aggregate.py)，只读取原始数据，不调用模型。
- [跨题初版（失败后才请求指导）原始结果](results_stage2/cross-task10-seed0.to_z1bge/summary.json)；[完整时间线](results_stage2/cross-task10-seed0.to_z1bge/events.jsonl)。
- [跨题最终版（指导预取）原始结果](results_stage2/cross-task10-prefetch-seed0.6hyhjicw/summary.json)；[完整时间线](results_stage2/cross-task10-prefetch-seed0.6hyhjicw/events.jsonl)。
- [同配置串行对照原始结果](results_stage2/cross-task10-sequential-seed0.4d8_btoi/summary.json)；[完整时间线](results_stage2/cross-task10-sequential-seed0.4d8_btoi/events.jsonl)。

真实模型复现命令（要求缓存模型已就绪、Cursor CLI 已登录）：

```bash
python examples_stage2/cross_task_benchmark.py --out results_stage2/new-cross-task --count 10 --deadline 240 --seed 0
python examples_stage2/cross_task_benchmark.py --out results_stage2/new-sequential --count 10 --deadline 240 --seed 0 --mode sequential
```

原始模型响应、答案、状态快照、源码快照和配置保存在各实验目录。详细运行目录被 git 忽略，迁移复现时需要一并保存；项目内的聚合 CSV 和本报告保留核心结果。
