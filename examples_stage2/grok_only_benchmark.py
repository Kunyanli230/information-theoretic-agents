"""Grok directly solves T01-T10, one fresh CLI call per task, sequentially.

Public verification is inside the batch clock. Hidden evaluation occurs after
all model calls and never supplies feedback. No Qwen, replay, cached answers,
API retries, or hidden-outcome-driven reruns are used.
"""
import argparse
import asyncio
import csv
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voi.tasks import T
from voi_async.environment import CodeEnvironment
from voi_async.models import CursorModel
from voi_async.types import Action, TaskSpec


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


class DirectGrok(CursorModel):
    def __init__(self, out, timeout):
        super().__init__(model='grok-4.6', timeout=timeout)
        self.out = out

    def command(self, data, directory):
        return super().command(json.loads(data)['prompt'], directory)

    async def complete(self, payload):
        row = dict(task_id=payload['snapshot']['task_id'], started_wall=time.time(), payload=payload)
        with (self.out/'requests.jsonl').open('a') as f:
            f.write(json.dumps(row,ensure_ascii=False)+'\n')
        try:
            result = await super().complete(payload)
            row.update(status='completed',response=result)
            return result
        except asyncio.CancelledError:
            row['status']='cancelled'
            raise
        except Exception as exc:
            row.update(status='error',error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            row['ended_wall']=time.time()
            with (self.out/'responses.jsonl').open('a') as f:
                f.write(json.dumps(row,ensure_ascii=False)+'\n')


def prompt_for(task, feedback, seed):
    return (
        'You fix bugs in Python code. Do not run tools or edit files. '
        'Return ONLY a JSON object with one field "code", containing the complete '
        'corrected Python source. Preserve the public interface and intended general behavior.\n'
        f'Code:\n```python\n{task["buggy"]}```\n'
        f'This test fails:\n```python\n{task["visible"]}\n```\n'
        f'Error:\n{feedback}\n\nFix the code.\nExperiment seed: {seed}.')


async def main(args):
    out=Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError('choose an empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    model=DirectGrok(out,args.timeout)
    cases=T[:args.count]
    tasks=[TaskSpec(t['id'],'Fix '+t['name'],
        {'calc.py':t['buggy'],'tests.py':'from calc import *\n'+t['visible']+'\n'},
        [sys.executable,'tests.py'],[sys.executable,'heldout.py'],
        hidden_files={'heldout.py':'from calc import *\n'+'\n'.join(t['hidden'])+'\n'}) for t in cases]
    save(out/'config.json',dict(model=model.metadata,task_ids=[t['id'] for t in cases],seed=args.seed,
        solver='Grok directly returns complete source; one actual CLI call per task; no Qwen',
        concurrency=1,attempts_per_task=1,per_call_timeout=args.timeout,
        total_deadline=None,
        timing='Initial public checks, actual CLI response wait and public patch verification included; hidden evaluation excluded',
        sampling='seed in prompt only; remote Grok sampling is provider-controlled',
        replay=False,retries=False,
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()))
    (out/'run.py').write_bytes(Path(__file__).read_bytes())
    rows=[]
    envs=[CodeEnvironment(t) for t in tasks]
    start=time.monotonic()
    # Same initial public feedback preparation as the cross-task batch.
    for env in envs:
        await env.execute(Action('test'))
    for original,env in zip(cases,envs):
        tid=original['id']
        directory=out/tid
        directory.mkdir()
        began=time.monotonic()
        feedback=next(o.text for o in reversed(env.observations) if o.kind=='test')
        prompt=prompt_for(original,feedback,args.seed)
        (directory/'prompt.txt').write_text(prompt)
        print('START '+tid+' '+original['name'],flush=True)
        row=dict(task_id=tid,name=original['name'],public_pass=False,hidden_pass=None,
                 reason='model_error',call_seconds=None,error=None)
        try:
            called=time.monotonic()
            result=await model.complete(dict(role='solver',seed=args.seed,
                snapshot=env.snapshot().public(),prompt=prompt))
            row['call_seconds']=time.monotonic()-called
            save(directory/'grok.json',result)
            code=result.get('code')
            if not isinstance(code,str) or not code.strip():
                raise ValueError('Grok must return nonempty complete code')
            (directory/'candidate.py').write_text(code)
            obs=await env.execute(Action('patch',edits=({'path':'calc.py','old':env.files['calc.py'],'new':code},)))
            row.update(public_pass=obs.ok,reason='visible_verified' if obs.ok else 'public_failed')
            save(directory/'public_observation.json',asdict(obs))
        except Exception as exc:
            if row['call_seconds'] is None:
                row['call_seconds']=time.monotonic()-called
            row['error']=f'{type(exc).__name__}: {exc}'
        row.update(task_seconds=time.monotonic()-began,finished_at=time.monotonic()-start)
        (directory/'answer.py').write_text(env.files['calc.py'])
        rows.append(row)
        save(directory/'result.json',row)
        save(out/'progress.json',dict(completed=len(rows),public_pass=sum(r['public_pass'] for r in rows),
                                     elapsed=time.monotonic()-start,rows=rows))
        print(json.dumps(row,ensure_ascii=False),flush=True)
    batch_seconds=time.monotonic()-start
    evaluation_start=time.monotonic()
    for row,env in zip(rows,envs):
        row['hidden_pass']=(await env.check(hidden=True))[0] if row['public_pass'] else False
        save(out/row['task_id']/'result.json',row)
    evaluation_seconds=time.monotonic()-evaluation_start
    summary=dict(solver='grok_only',tasks=len(rows),seed=args.seed,
        batch_seconds=batch_seconds,evaluation_seconds=evaluation_seconds,
        model_wait_seconds=sum(r['call_seconds'] for r in rows),
        qualified=sum(r['public_pass'] and r['hidden_pass'] for r in rows),
        public_pass=sum(r['public_pass'] for r in rows),
        model_errors=sum(r['error'] is not None for r in rows),
        qualified_by_seconds={str(t):sum(r['public_pass'] and r['hidden_pass']
            and r['finished_at']<=t for r in rows) for t in [30,60,90,120,180,240]},per_task=rows)
    save(out/'summary.json',summary)
    with (out/'task_results.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print('COMPLETE '+json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True)
    p.add_argument('--count',type=int,choices=range(1,len(T)+1),default=10)
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--timeout',type=float,default=120)
    asyncio.run(main(p.parse_args()))
