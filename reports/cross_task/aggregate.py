"""Read-only aggregation of actual cross-task and sequential 10-task trials."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCES = {
    'initial_cross_task': ROOT/'results_stage2/cross-task10-seed0.to_z1bge',
    'cross_task_prefetch': ROOT/'results_stage2/cross-task10-prefetch-seed0.6hyhjicw',
    'sequential': ROOT/'results_stage2/cross-task10-sequential-seed0.4d8_btoi',
}
LABELS = {'initial_cross_task':'跨题初版（失败后才请求指导）',
          'cross_task_prefetch':'跨题最终版（指导预取）', 'sequential':'同配置串行对照'}


def read(path):
    return json.loads(path.read_text())


def busy_seconds(events, start_event, end_events, limit):
    start = None
    total = 0.0
    for event in events:
        if event['event'] == start_event:
            assert start is None, 'overlapping resource use'
            start = event['time']
        elif event['event'] in end_events and start is not None:
            total += max(0, min(event['time'],limit)-start)
            start = None
    if start is not None:
        total += max(0,limit-start)
    return total


runs, tasks, curves = {}, [], []
for name,path in SOURCES.items():
    summary = read(path/'summary.json')
    batch = read(path/'batch.json')
    calls = [json.loads(line) for line in (path/'responses.jsonl').read_text().splitlines()]
    assert summary['tasks'] == 10 and summary['seed'] == 0
    assert all(c['payload']['seed'] == 0 for c in calls)
    assert all('heldout.py' not in c['payload']['snapshot']['files'] for c in calls)
    limit = min(summary['batch_seconds'],summary['wall_budget_seconds'])
    executor_busy = busy_seconds(batch['events'],'executor_start',{'tool_end','executor_error'},limit)
    guide_busy = busy_seconds(batch['events'],'guide_start',{'guide_returned','guide_error'},limit)
    row = dict(label=LABELS[name], tasks=10, seed=0, budget=summary['wall_budget_seconds'],
        batch_seconds=summary['batch_seconds'], qualified=summary['qualified'],
        public_pass=summary['public_pass'], guide_errors=summary['guide_errors'],
        executor_calls=sum(c['role']=='executor' for c in calls),
        guide_calls=sum(c['role']=='guide' for c in calls),
        guide_concurrency=1, executor_concurrency=1,
        executor_action_busy_seconds=executor_busy,
        executor_action_utilization=executor_busy/limit,
        guide_busy_seconds=guide_busy,
        cross_task_dispatches=summary['cross_task_dispatches'],
        guided_resumptions=summary['guided_resumptions'],
        qualified_by_seconds=summary['qualified_by_seconds'],
        source=str(path.relative_to(ROOT)))
    runs[name]=row
    for task in summary['per_task']:
        tasks.append(dict(run=name,**task))
    for seconds,count in summary['qualified_by_seconds'].items():
        curves.append(dict(run=name,seconds=float(seconds),qualified=count))

cross,seq=runs['cross_task_prefetch'],runs['sequential']
comparison=dict(quality='All hidden assertions pass; hidden outcomes evaluated only after the batch.',
    objective='Number of qualified tasks completed within the same wall-clock budget.',
    qualified_difference_by_seconds={t:cross['qualified_by_seconds'][t]-seq['qualified_by_seconds'][t]
        for t in cross['qualified_by_seconds']},
    all_ten_speed_ratio=(seq['batch_seconds']/cross['batch_seconds']
        if cross['qualified']==seq['qualified']==10 else None),
    interpretation='Fresh actual Grok calls in every arm. Guidance content and latency are not frozen; single-seed small-sample measurements.',
    timing='One batch clock includes initial public checks and local cleanup. Model load and post-batch hidden evaluation are excluded.',
    utilization='Executor action wall time (generation plus public validation), not CPU or GPU utilization.')
(OUT/'summary.json').write_text(json.dumps(dict(runs=runs,comparison=comparison),ensure_ascii=False,indent=2)+'\n')
for filename,records in [('task_results.csv',tasks),('deadline_curve.csv',curves)]:
    with (OUT/filename).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]))
        w.writeheader(); w.writerows(records)

text='''# 跨题异步执行与 10 题实测

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
'''
for name,r in runs.items():
    text+=f'| {r["label"]} | {r["batch_seconds"]:.2f} | {r["qualified"]}/10 | {r["public_pass"]}/10 | {r["guide_errors"]} |\n'
text+='\n串行组 T04 的 Grok CLI 进程退出码为 1，未返回指导；T08 公开测试通过但隐藏测试失败。这两题均不计入合格完成数。两组最终合格数量不同，因此不报告完成全部 10 道合格题的加速比。\n'
text+='\n### 相同时间预算内的合格题数\n\n| 预算秒数 | 跨题最终版 | 串行对照 |\n|---|---:|---:|\n'
for t,n in cross['qualified_by_seconds'].items():
    text+=f'| {float(t):g} | {n} | {seq["qualified_by_seconds"][t]} |\n'
if comparison['all_ten_speed_ratio']:
    ratio=comparison['all_ten_speed_ratio']
    text+=f'\n两组均 10/10 合格，完成整批的速度比为 **{ratio:.2f}×**，耗时减少 **{1-1/ratio:.1%}**。\n'
text+=f'\n最终跨题有 {cross["cross_task_dispatches"]} 次在另一题指导在途时派发本地工作、{cross["guided_resumptions"]} 次指导就绪后的恢复。执行器动作忙碌率为 {cross["executor_action_utilization"]:.1%}，串行为 {seq["executor_action_utilization"]:.1%}；这里统计生成加公开验证的动作墙钟时间，并非硬件利用率。\n'
text+='\n### 实际恢复记录\n\n| 题目 | 指导就绪后等待恢复的秒数 |\n|---|---:|\n'
for r in read(SOURCES['cross_task_prefetch']/'summary.json')['resume_wait_seconds']:
    text+=f'| {r["task_id"]} | {r["seconds"]:.2f} |\n'
text+='''
恢复等待来自当前动作尚未结束或已有指导就绪题排在前面。该策略优先保证已有候选完整执行，没有实现生成中途的缓存暂停／恢复。

## 验证与结果边界

55 项回归测试通过，包括等待 A 时执行 B、指导返回后优先恢复 A、后续指导预取、单模型与单导师并发上限、题目隔离、指导失败隔离、全局截止时间与取消清理、隐藏质量评价不回流策略。编译及 CLI 参数检查通过。

这些是同一小题集、同一 seed 的实测，不是一般任务上的稳定加速保证。两组现场请求的 Grok 指导文本与服务时延不同，本地推理延迟也会波动；初版与最终版之间的差异不能全部归因于预取。同质量按相同隐藏测试全部通过定义，主结果为相同墙钟预算内的合格完成数。

## 数据与复现

- [汇总 JSON](reports/cross_task/summary.json)
- [30 条逐题记录 CSV](reports/cross_task/task_results.csv)
- [按时间预算统计的完成数 CSV](reports/cross_task/deadline_curve.csv)
- [聚合脚本](reports/cross_task/aggregate.py)，只读取原始数据，不调用模型。
'''
for name,path in SOURCES.items():
    text+=f'- [{LABELS[name]}原始结果]({path.relative_to(ROOT)}/summary.json)；[完整时间线]({path.relative_to(ROOT)}/events.jsonl)。\n'
text+='''
真实模型复现命令（要求缓存模型已就绪、Cursor CLI 已登录）：

```bash
python examples_stage2/cross_task_benchmark.py --out results_stage2/new-cross-task --count 10 --deadline 240 --seed 0
python examples_stage2/cross_task_benchmark.py --out results_stage2/new-sequential --count 10 --deadline 240 --seed 0 --mode sequential
```

原始模型响应、答案、状态快照、源码快照和配置保存在各实验目录。详细运行目录被 git 忽略，迁移复现时需要一并保存；项目内的聚合 CSV 和本报告保留核心结果。
'''
(ROOT/'CROSS_TASK_REPORT.md').write_text(text)
print(json.dumps(dict(runs=runs,comparison=comparison),ensure_ascii=False,indent=2))
