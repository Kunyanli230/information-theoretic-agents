"""Read-only aggregation of the single actual Grok-only trial."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN=ROOT/'results_stage2/grok-only10-seed0.ap6u8ss0'
CROSS=ROOT/'results_stage2/cross-task10-prefetch-seed0.6hyhjicw'
s=json.loads((RUN/'summary.json').read_text())
cross=json.loads((CROSS/'summary.json').read_text())
requests=[json.loads(x) for x in (RUN/'requests.jsonl').read_text().splitlines()]
responses=[json.loads(x) for x in (RUN/'responses.jsonl').read_text().splitlines()]
assert len(requests)==len(responses)==s['tasks']==10
assert all(r['payload']['seed']==0 for r in requests)
assert len({r['task_id'] for r in requests})==10
assert all('heldout.py' not in r['payload']['snapshot']['files'] for r in requests)
cutoff=cross['batch_seconds']
qualified_at_cross_time=sum(r['public_pass'] and r['hidden_pass'] and r['finished_at']<=cutoff
                           for r in s['per_task'])
comparison=dict(cross_task_seconds=cutoff,cross_task_qualified=cross['qualified'],
    grok_qualified_at_cross_task_time=qualified_at_cross_time,
    grok_to_cross_time_ratio=s['batch_seconds']/cutoff if s['qualified']==cross['qualified']==10 else None,
    interpretation='One fresh real trial per strategy at different times; provider latency and sampling vary.',
    source=str(RUN.relative_to(ROOT)))
(OUT/'summary.json').write_text(json.dumps(dict(grok_only=s,comparison=comparison),ensure_ascii=False,indent=2)+'\n')
(OUT/'task_results.csv').write_bytes((RUN/'task_results.csv').read_bytes())
text=f'''# 纯 Grok 解题基线：同一批 10 题

使用 Grok-4.6 CLI 直接生成修复后的完整 Python 代码，每题一次真实请求、10 题串行执行。没有 Qwen、指导／时延回放、答案缓存、API 重试或根据隐藏结果重跑单题。提示中固定 seed=0；该提示不能控制远端模型的采样随机性。

公开输入与跨题实验相同：错误源代码、可见测试及初始失败反馈。Grok 输出完整代码，由同一隔离测试环境验证和提交。CLI 为 ask 模式，要求模型不运行工具或修改文件。

整批计时包含初始公开测试、CLI 启动和真实响应等待、代码解析与公开验证。隐藏评测在全部提交后执行，单独计时，不向模型返回反馈。每次调用最多等待 120 秒；为测完整 10 题耗时，不设置整批硬截止，另统计相同时间预算内的合格完成数。

## 结果

| 策略 | 整批秒数 | 合格题数 |
|---|---:|---:|
| 纯 Grok 直接解题 | {s['batch_seconds']:.2f} | {s['qualified']}/10 |
| Qwen 0.5B + Grok 跨题版 | {cross['batch_seconds']:.2f} | {cross['qualified']}/10 |

纯 Grok 的 CLI 响应等待合计 {s['model_wait_seconds']:.2f} 秒；隐藏评测另用 {s['evaluation_seconds']:.3f} 秒。模型错误 {s['model_errors']} 次，公开测试通过 {s['public_pass']}/10，全部隐藏测试通过 {s['qualified']}/10。

在跨题版结束的同一时间截点（{cutoff:.2f} 秒），纯 Grok 已合格完成 {qualified_at_cross_time} 题，跨题版完成 {cross['qualified']} 题。

## 逐题记录

| 题目 | CLI 响应秒数 | 公开通过 | 隐藏通过 | 累计完成秒数 |
|---|---:|---|---|---:|
'''
for r in s['per_task']:
    text+=f'| {r["task_id"]} {r["name"]} | {r["call_seconds"]:.2f} | {"是" if r["public_pass"] else "否"} | {"是" if r["hidden_pass"] else "否"} | {r["finished_at"]:.2f} |\n'
text+='\n## 相同时间预算\n\n| 预算秒数 | 纯 Grok 合格题数 | 跨题版合格题数 |\n|---|---:|---:|\n'
for t,n in s['qualified_by_seconds'].items():
    text+=f'| {t} | {n} | {cross["qualified_by_seconds"][t]} |\n'
text+='''
这是一轮小样本观察，两组在不同时间运行，Grok 的服务延迟和输出内容会变化，不能据此宣称稳定的一般性加速。

## 数据与复现

- [汇总 JSON](reports/grok_only/summary.json)
- [逐题 CSV](reports/grok_only/task_results.csv)
- [纯 Grok 运行脚本](examples_stage2/grok_only_benchmark.py)
- [原始配置](results_stage2/grok-only10-seed0.ap6u8ss0/config.json)
- [实际请求](results_stage2/grok-only10-seed0.ap6u8ss0/requests.jsonl)与[响应](results_stage2/grok-only10-seed0.ap6u8ss0/responses.jsonl)

```bash
python examples_stage2/grok_only_benchmark.py --out results_stage2/new-grok-only --count 10 --seed 0
```

详细模型响应、公开验证反馈和答案位于原始实验目录；该目录被 git 忽略，迁移复现时需要一起保存。
'''
(ROOT/'GROK_ONLY_REPORT.md').write_text(text)
print(json.dumps(dict(grok_only=s,comparison=comparison),ensure_ascii=False,indent=2))
