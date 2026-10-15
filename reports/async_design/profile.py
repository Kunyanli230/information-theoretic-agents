"""Read-only phase accounting for the preserved 112.87 s live batch.

Generation intervals include adapter/IPC work; they are not kernel CPU time.
Bounds hold only for the same work and resources, not a new model experiment.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'results_stage2/cross-task10-prefetch-seed0.6hyhjicw/batch.json'
OUT = Path(__file__).with_name('profile.json')


def main():
    batch = json.loads(SOURCE.read_text())
    events = batch['events']
    actions, guides = [], []
    for i, event in enumerate(events):
        task = event['task_id']
        later = events[i + 1:]
        if event['event'] == 'executor_start':
            tool = next(e for e in later if e['task_id'] == task and e['event'] == 'tool_start')
            end = next(e for e in later if e['task_id'] == task and e['event'] == 'tool_end')
            actions.append(dict(task_id=task, guided=event['message_hash'] is not None,
                                start=event['time'], end=end['time'],
                                generation_stage_seconds=tool['time'] - event['time'],
                                validation_stage_seconds=end['time'] - tool['time'],
                                public_pass=end['observation']['ok']))
        elif event['event'] == 'guide_start':
            end = next(e for e in later if e['task_id'] == task and e['event'] == 'guide_returned')
            use = next(e for e in later if e['task_id'] == task and e['event'] == 'executor_start')
            guides.append(dict(task_id=task, start=event['time'], end=end['time'],
                               service_seconds=end['time'] - event['time'],
                               wait_for_executor_seconds=use['time'] - end['time']))
    for before, after in zip(actions, actions[1:]):
        assert before['end'] <= after['start'], 'executor intervals overlap'
    generation = sum(a['generation_stage_seconds'] for a in actions)
    validation = sum(a['validation_stage_seconds'] for a in actions)
    guide = sum(g['service_seconds'] for g in guides)
    elapsed = batch['elapsed']
    failed = sum(a['generation_stage_seconds'] for a in actions
                 if not a['guided'] and not a['public_pass'])
    result = dict(source=str(SOURCE.relative_to(ROOT)), source_kind='preserved live calls; no replay',
                  elapsed_seconds=elapsed, executor_calls=len(actions), guide_calls=len(guides),
                  generation_stage_seconds=generation, validation_stage_seconds=validation,
                  outside_executor_action_seconds=elapsed-generation-validation,
                  executor_action_occupancy=(generation+validation)/elapsed,
                  generation_stage_fraction=generation/elapsed,
                  guide_service_seconds=guide, failed_unguided_generation_seconds=failed,
                  guidance_ready_wait_mean=sum(g['wait_for_executor_seconds'] for g in guides)/len(guides),
                  guidance_ready_wait_max=max(g['wait_for_executor_seconds'] for g in guides),
                  same_work_generation_resource_lower_bound_seconds=generation,
                  same_work_max_speedup_if_all_non_generation_time_removed=elapsed/generation,
                  same_work_phase_demand_sensitivity=[dict(
                      generation_service_reduction=rate,
                      generation_demand=generation*(1-rate),
                      resource_only_lower_bound=max(generation*(1-rate), guide, validation))
                      for rate in (0.0, 0.1, 0.2)],
                  caveats=['No historical CPU, scheduler lag, lock-wait or context-switch counters.',
                           'Resource lower bounds omit precedence, startup and final drain.',
                           'Failing attempts cannot be declared avoidable using hindsight.',
                           'Guidance waits overlap existing work and cannot be summed as savings.'],
                  actions=actions, guides=guides)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'actions','guides'}},indent=2))


if __name__ == '__main__':
    main()
