# 纯 Grok 解题基线：同一批 10 题

使用 Grok-4.6 CLI 直接生成修复后的完整 Python 代码，每题一次真实请求、10 题串行执行。没有 Qwen、指导／时延回放、答案缓存、API 重试或根据隐藏结果重跑单题。提示中固定 seed=0；该提示不能控制远端模型的采样随机性。

公开输入与跨题实验相同：错误源代码、可见测试及初始失败反馈。Grok 输出完整代码，由同一隔离测试环境验证和提交。CLI 为 ask 模式，要求模型不运行工具或修改文件。

整批计时包含初始公开测试、CLI 启动和真实响应等待、代码解析与公开验证。隐藏评测在全部提交后执行，单独计时，不向模型返回反馈。每次调用最多等待 120 秒；为测完整 10 题耗时，不设置整批硬截止，另统计相同时间预算内的合格完成数。

## 结果

| 策略 | 整批秒数 | 合格题数 |
|---|---:|---:|
| 纯 Grok 直接解题 | 154.37 | 10/10 |
| Qwen 0.5B + Grok 跨题版 | 112.87 | 10/10 |

纯 Grok 的 CLI 响应等待合计 153.54 秒；隐藏评测另用 0.334 秒。模型错误 0 次，公开测试通过 10/10，全部隐藏测试通过 10/10。

在跨题版结束的同一时间截点（112.87 秒），纯 Grok 已合格完成 7 题，跨题版完成 10 题。

## 逐题记录

| 题目 | CLI 响应秒数 | 公开通过 | 隐藏通过 | 累计完成秒数 |
|---|---:|---|---|---:|
| T01 sum_to_n | 21.51 | 是 | 是 | 21.93 |
| T02 max_of | 14.98 | 是 | 是 | 37.03 |
| T03 is_even | 13.45 | 是 | 是 | 50.51 |
| T04 average | 15.00 | 是 | 是 | 65.55 |
| T05 count_vowels | 14.33 | 是 | 是 | 79.90 |
| T06 reverse_words | 14.88 | 是 | 是 | 94.82 |
| T07 factorial | 11.17 | 是 | 是 | 106.06 |
| T08 clamp | 15.72 | 是 | 是 | 121.80 |
| T09 last_n | 16.94 | 是 | 是 | 138.79 |
| T10 fib | 15.55 | 是 | 是 | 154.37 |

## 相同时间预算

| 预算秒数 | 纯 Grok 合格题数 | 跨题版合格题数 |
|---|---:|---:|
| 30 | 1 | 2 |
| 60 | 3 | 5 |
| 90 | 5 | 7 |
| 120 | 7 | 10 |
| 180 | 10 | 10 |
| 240 | 10 | 10 |

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
