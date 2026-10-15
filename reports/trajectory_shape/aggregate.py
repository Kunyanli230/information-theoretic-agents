"""Project preserved logs only; no model calls or simulated task execution."""
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from voi_async.trajectory_shape import PROFILES, compare_runs

OUT = Path(__file__).resolve().parent
BATCH_LEFT = ROOT / 'results_stage2/cross-task10-sequential-seed0.4d8_btoi/batch.json'
BATCH_RIGHT = ROOT / 'results_stage2/cross-task10-prefetch-seed0.6hyhjicw/batch.json'
PAIRED = ROOT / 'results_stage2/async-engineering-paired-seed0.3ysyu8_5'


def summarize(result):
    return {k: result[k] for k in ('pair_count', 'changed_pair_count',
                                  'changed_pair_rate', 'empty_prefix_pairs')}


def main():
    groups, rows = {}, []
    for group in ('live_cross_task', 'frozen_guide_same_task'):
        groups[group] = {}
        for profile in PROFILES:
            if group == 'live_cross_task':
                result = compare_runs(BATCH_LEFT, BATCH_RIGHT, profile)
            else:
                comparisons = [compare_runs(PAIRED / f'T{i:02}-sync/episode.json',
                                            PAIRED / f'T{i:02}-async/episode.json', profile)
                               for i in range(1, 11)]
                pairs = [d['pairs'][0] for d in comparisons]
                result = dict(profile=profile, pair_count=len(pairs),
                              changed_pair_count=sum(p['shape_changed'] for p in pairs),
                              changed_pair_rate=sum(p['shape_changed'] for p in pairs) / len(pairs),
                              empty_prefix_pairs=[p['task_id'] for p in pairs if p['empty_common_prefix']],
                              individual_pair_metadata=[{k: v for k, v in d.items() if k != 'pairs'}
                                                        for d in comparisons], pairs=pairs)
            (OUT / f'{group}-{profile}.json').write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            groups[group][profile] = summarize(result)
            for p in result['pairs']:
                rows.append(dict(group=group, profile=profile, **{k: p[k] for k in (
                    'task_id', 'D_shape', 'shape_changed', 'k_left', 'k_right', 'common_rounds',
                    'empty_common_prefix', 'D_iter_observed', 'auxiliary_D_struct_observed')},
                    left_success=p['quality_left']['success'],
                    right_success=p['quality_right']['success']))
    summary = dict(groups=groups, notes=[
        'Each task is one pair; left=sync/sequential, right=async/cross_task.',
        'live_cross_task: fresh historical Grok calls; not frozen guidance or latency.',
        'frozen_guide_same_task: historical real Grok guidance/delay replay; actual historical Qwen generations.',
        'This analysis only reads saved traces; it does not rerun tasks or invoke models.',
        'Decisions are observed-event projections; common-prefix differences are not correctness scores.',
        'Empty-prefix pairs remain in the all-pair denominator and are explicitly flagged.',
    ])
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    with (OUT / 'task_results.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
