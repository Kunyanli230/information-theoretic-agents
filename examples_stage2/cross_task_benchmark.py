"""Real Qwen 0.5B + Grok CLI, fixed seed, one batch wall-clock budget.

Run from the repository: python examples_stage2/cross_task_benchmark.py --out ...
This script never replays guidance, retries model calls, or uses hidden outcomes
for scheduling. Models are prepared once before the batch clock starts.
"""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voi import guide as legacy_guide
from voi.tasks import T
from voi_async.batch import BatchConfig, BatchDelegate
from voi_async.complete_code import CompleteCodeAgent
from voi_async.hf_backend import HFProcessModel
from voi_async.models import CursorModel
from voi_async.types import Diagnosis, TaskSpec


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class LogCalls:
    async def complete(self, payload):
        record = dict(role=self.role, task_id=payload['snapshot']['task_id'],
                      started_wall=time.time(), payload=payload)
        with (self.out / 'requests.jsonl').open('a') as f:
            f.write(json.dumps(record, ensure_ascii=False)+'\n')
        try:
            result = await super().complete(payload)
            record.update(status='completed', response=result)
            return result
        except asyncio.CancelledError:
            record['status'] = 'cancelled'
            raise
        except Exception as exc:
            record.update(status='error', error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            record['ended_wall'] = time.time()
            with (self.out / 'responses.jsonl').open('a') as f:
                f.write(json.dumps(record, ensure_ascii=False)+'\n')


class LocalModel(LogCalls, HFProcessModel):
    def __init__(self, out):
        super().__init__(threads=4, temperature=.7, top_p=.95, max_new_tokens=256,
                         local_files_only=True, timeout=120)
        self.out, self.role = out, 'executor'


class RemoteModel(LogCalls, CursorModel):
    def __init__(self, out):
        super().__init__(model='grok-4.6', timeout=120)
        self.out, self.role = out, 'guide'

    def command(self, data, directory):
        return super().command(json.loads(data)['prompt'], directory)


class FullGuide:
    def __init__(self, model, cases):
        self.model, self.cases = model, cases

    async def diagnose(self, snapshot, seed):
        feedback = next((o.text for o in reversed(snapshot.observations) if o.kind == 'test'), '')
        prompt = legacy_guide.build_prompt('diagnosis', snapshot.files['calc.py'],
                                           self.cases[snapshot.task_id]['visible'], feedback)
        prompt += f'\nExperiment seed: {seed}. Do not return the complete corrected source.'
        obj = await self.model.complete(dict(role='guide', snapshot=snapshot.public(),
                                             seed=seed, prompt=prompt))
        if any(not isinstance(obj.get(k), str) or not obj[k].strip()
               for k in ['location','cause','change','verification','applicable_if']):
            raise ValueError('missing diagnosis fields')
        if obj['applicable_if'] not in snapshot.files['calc.py']:
            raise ValueError('guide anchor absent from source')
        return Diagnosis(obj['location'], obj['cause'], obj['change'], obj['verification'],
                         {'calc.py':obj['applicable_if']})


class LoggedBatch(BatchDelegate):
    def __init__(self, agent, guide, config, out):
        super().__init__(agent, guide, config)
        self.out = out

    def log(self, event, task_id=None, **data):
        super().log(event, task_id, **data)
        with (self.out / 'events.jsonl').open('a') as f:
            f.write(json.dumps(self.events[-1], ensure_ascii=False)+'\n')
        if event in {'guide_start','guide_returned','guide_error','dispatch','task_finished','batch_end'}:
            print(json.dumps(self.events[-1], ensure_ascii=False), flush=True)


async def main(args):
    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('choose an empty output directory')
    out.mkdir(parents=True, exist_ok=True)
    cases = {t['id']:t for t in T[:args.count]}
    tasks = [TaskSpec(t['id'], 'Fix '+t['name'],
        {'calc.py':t['buggy'], 'tests.py':'from calc import *\n'+t['visible']+'\n'},
        [sys.executable,'tests.py'], [sys.executable,'heldout.py'],
        hidden_files={'heldout.py':'from calc import *\n'+'\n'.join(t['hidden'])+'\n'})
        for t in cases.values()]
    config = BatchConfig(mode=args.mode, deadline=args.deadline, seed=args.seed,
                         max_unassisted_steps=1, max_guided_steps=1,
                         prefetch_guides=not args.no_guide_prefetch)
    hf, cursor = LocalModel(out), RemoteModel(out)
    agent = CompleteCodeAgent(hf, {t['id']:t['visible'] for t in cases.values()})
    save(out/'config.json', dict(runtime=asdict(config), task_ids=list(cases),
        qwen=hf.metadata, guide=cursor.metadata,
        teacher='Fresh actual Grok CLI calls; no guidance or latency replay',
        resource_limits=dict(executor_concurrency=1, guide_concurrency=1),
        policy='Bootstrap A, execute B; guide-ready priority after action validation; failed tasks first, then prefetch untouched tasks; one guide at a time',
        evaluation='Hidden evaluation after batch; quality = all held-out assertions pass',
        timing='One batch deadline; initial public checks included, model load and hidden evaluation excluded',
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()))
    (out/'source.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=ROOT))
    # Include newly added modules, which git diff does not contain yet.
    source = out/'source'
    source.mkdir()
    for filename in ['batch.py','complete_code.py','hf_worker.py']:
        (source/filename).write_bytes((ROOT/'voi_async'/filename).read_bytes())
    try:
        await hf.prepare()
        print('READY: resident Qwen; actual Grok; fixed seed; batch='+str(args.deadline), flush=True)
        result = await LoggedBatch(agent, FullGuide(cursor, cases), config, out).run(tasks)
        save(out/'batch.json', asdict(result))
        for row in result.results:
            directory = out/row.task_id
            directory.mkdir()
            save(directory/'episode.json', asdict(row))
            (directory/'answer.py').write_text(row.files['calc.py'])
        guide_returns = [e for e in result.events if e['event']=='guide_returned']
        resumed = [e for e in result.events if e['event']=='dispatch' and e['reason']=='guidance_ready']
        cross_work = [e for e in result.events if e['event']=='dispatch'
                      and e['while_guiding'] and e['while_guiding']!=e['task_id']]
        cutoffs = sorted(set([30,60,90,120,180,240,args.deadline]))
        report = dict(mode=args.mode, seed=args.seed, tasks=len(tasks),
            wall_budget_seconds=args.deadline, batch_seconds=result.elapsed,
            evaluation_seconds=result.evaluation_seconds, reason=result.reason,
            qualified=sum(r.success is True for r in result.results),
            public_pass=sum(r.visible_pass for r in result.results),
            qualified_by_seconds={str(t):result.qualified_by(t) for t in cutoffs if t<=args.deadline},
            cross_task_dispatches=len(cross_work), guided_resumptions=len(resumed),
            guide_errors=sum(e['event']=='guide_error' for e in result.events),
            per_task=[dict(task_id=r.task_id, name=cases[r.task_id]['name'],
                public_pass=r.visible_pass, hidden_pass=r.success, reason=r.reason,
                finished_at=result.completion_times[r.task_id], task_latency=r.elapsed)
                for r in result.results],
            resume_wait_seconds=[dict(task_id=e['task_id'],
                seconds=e['time']-next(g['time'] for g in guide_returns if g['task_id']==e['task_id']))
                for e in resumed],
            limitations=['Single small task set and a single fixed seed.',
                         'Remote Grok sampling is provider-controlled.',
                         'Historical sequential runs are not controlled comparisons of this batch.'])
        save(out/'summary.json',report)
        print('COMPLETE '+json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        await hf.aclose()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True)
    p.add_argument('--mode',choices=['cross_task','sequential'],default='cross_task')
    p.add_argument('--deadline',type=float,default=240)
    p.add_argument('--count',type=int,choices=range(1,len(T)+1),default=10)
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--no-guide-prefetch',action='store_true')
    asyncio.run(main(p.parse_args()))
