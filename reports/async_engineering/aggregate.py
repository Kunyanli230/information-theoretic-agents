"""Aggregate preserved experiments; reads logs only and never invokes models."""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results_stage2'
BASE = RESULTS / 'grok-qwen20-seed0.PbMOG5'
PAIRED = RESULTS / 'async-engineering-paired-seed0.3ysyu8_5'
RUNS = [
    ('historical_async', RESULTS / 'async10-vs-sync-seed0.445suS/fullcode'),
    ('initial_fix_live', RESULTS / 'async-engineering-seed0.quo9sirx'),
    ('final_fix_live', RESULTS / 'async-engineering-final-seed0.j_62ubmc'),
]

def read(path):
    return json.loads(path.read_text())

def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]

def usage_by_task(path):
    calls = jsonl(path / 'responses.jsonl')
    qwen = [c for c in calls if c['role'] == 'executor']
    generations = [json.loads(r['text']) for r in jsonl(path / 'worker-raw.jsonl') if 'text' in r]
    assert len(qwen) == len(generations), path
    usage = defaultdict(lambda: dict(qwen_calls=0, qwen_cancelled=0, qwen_tokens=0,
                                    qwen_generation_seconds=0.0, guide_calls=0, guide_errors=0,
                                    guide_cancelled=0))
    # One resident executor serializes calls, so raw worker responses and logged
    # completions have the same order, including drained cancelled generations.
    for c, g in zip(qwen, generations):
        assert c['actual_seed'] == 0
        u = usage[c['task_id']]
        u['qwen_calls'] += 1
        u['qwen_cancelled'] += c['status'] == 'cancelled'
        u['qwen_tokens'] += g['generated_tokens']
        u['qwen_generation_seconds'] += g['generation_seconds']
    for c in calls:
        if c['role'] == 'guide':
            u = usage[c['task_id']]
            u['guide_calls'] += 1
            u['guide_errors'] += c['status'] == 'error'
            u['guide_cancelled'] += c['status'] == 'cancelled'
    return usage

rows = []
for i in range(1, 11):
    r = read(BASE / f'T{i:02}' / 'result.json')
    rows.append(dict(run_id='historical_sync', guide_mode='live', task_id=r['task_id'],
                     name=r['name'], seed=0, e2e_seconds=r['elapsed_seconds'],
                     visible_pass=r['visible_pass'], hidden_pass=r['hidden_pass'],
                     qwen_calls=1, qwen_cancelled=0, qwen_tokens=r['generated_tokens'],
                     qwen_generation_seconds=r['qwen_seconds'], guide_calls=1,
                     guide_errors=0, guide_cancelled=0, reason='completed',
                     source=str((BASE/r['task_id']/'result.json').relative_to(ROOT))))
for name, path in RUNS:
    usage = usage_by_task(path)
    for r in read(path / 'summary.json')['per_task']:
        rows.append(dict(run_id=name, guide_mode='live', task_id=r['task_id'], name=r['name'],
                         seed=0, e2e_seconds=r['e2e_seconds'], visible_pass=r['visible_pass'],
                         hidden_pass=r['hidden_pass'], **usage[r['task_id']], reason=r['reason'],
                         source=str((path/r['task_id']/'result.json').relative_to(ROOT))))
paired = read(PAIRED / 'comparison.json')['paired_actual_qwen_frozen_guide']
for r in paired['rows']:
    episode = read(PAIRED / f"{r['task_id']}-{r['mode']}" / 'episode.json')
    rows.append(dict(run_id='paired_'+r['mode'], guide_mode='replayed', task_id=r['task_id'],
                     name=next(x['name'] for x in rows if x['task_id']==r['task_id']), seed=0,
                     e2e_seconds=r['e2e_seconds'], visible_pass=episode['visible_pass'],
                     hidden_pass=r['success'], qwen_calls=r['executor_calls'],
                     qwen_cancelled=r['cancelled_executor_calls'], qwen_tokens=r['qwen_tokens'],
                     qwen_generation_seconds=r['generation_seconds'], guide_calls=0,
                     guide_errors=0, guide_cancelled=0, reason=r['reason'],
                     source=str((PAIRED/f"{r['task_id']}-{r['mode']}"/'result.json').relative_to(ROOT))))
assert len(rows) == 60
summary = []
for run_id in dict.fromkeys(r['run_id'] for r in rows):
    group = [r for r in rows if r['run_id'] == run_id]
    summary.append(dict(run_id=run_id, guide_mode=group[0]['guide_mode'], tasks=len(group),
        visible_pass=sum(r['visible_pass'] for r in group), hidden_pass=sum(r['hidden_pass'] for r in group),
        **{key:sum(r[key] for r in group) for key in (
            'e2e_seconds','qwen_calls','qwen_cancelled','qwen_tokens','qwen_generation_seconds',
            'guide_calls','guide_errors','guide_cancelled')}))
for filename, records in [('task_results.csv', rows), ('run_summary.csv', summary)]:
    with (OUT / filename).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
(OUT / 'summary.json').write_text(json.dumps(dict(runs=summary,
    paired_speedup=paired['speedup'], paired_time_reduction=paired['time_reduction'],
    live_time_change_vs_historical_sync=summary[3]['e2e_seconds']/summary[0]['e2e_seconds']-1,
    token_definition='Qwen generated tokens, including cancelled generations; excludes Grok tokens',
    guide_calls_definition='Actual remote invocations; replayed guidance is counted as 0 remote calls',
    timing_definition='Sum of task e2e wall seconds; includes evaluation/cleanup; excludes model loading',
    limitations=['Historical and final live runs were not simultaneous controlled pairs.',
                 'Paired arms replay identical historical guidance and delays; Qwen inference is real.',
                 'Qwen seed is always 0. Grok remote sampling is not controlled by that seed.',
                 'The native JSON-protocol diagnostic trial is excluded from the common-interface comparison.']),
    ensure_ascii=False, indent=2)+'\n')
print(json.dumps(summary, ensure_ascii=False, indent=2))
