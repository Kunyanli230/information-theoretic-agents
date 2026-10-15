import asyncio
from dataclasses import replace
import json
import unittest

from voi_async.batch import BatchConfig, BatchDelegate
from voi_async.complete_code import CompleteCodeAgent
from voi_async.environment import CodeEnvironment
from voi_async.fixtures import fixture_tasks
from voi_async.types import Action


class BatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tasks, self.diags = fixture_tasks(tool_delay=0)

    def repair(self, task_id):
        return Action("edit", **json.loads(self.diags[task_id].change))

    async def test_b_runs_during_a_guide_then_a_resumes_at_boundary(self):
        b_started = asyncio.Event()
        calls = []
        active = 0
        outer = self
        c = replace(self.tasks[1], task_id="third")
        self.diags[c.task_id] = self.diags[self.tasks[1].task_id]
        class Guide:
            async def diagnose(self, snapshot, seed):
                await b_started.wait()
                return outer.diags[snapshot.task_id]
        class Agent:
            async def propose(self, snapshot, message, seed):
                nonlocal active
                active += 1
                outer.assertEqual(active, 1)
                outer.assertNotIn("heldout.py", snapshot.files)
                outer.assertEqual(seed, 0)
                calls.append((snapshot.task_id, message is not None))
                if snapshot.task_id == "average":
                    b_started.set()
                    await asyncio.sleep(0.02)
                active -= 1
                return [outer.repair(snapshot.task_id)]
        r = await BatchDelegate(Agent(), Guide(), BatchConfig(deadline=1)).run(self.tasks+[c])
        self.assertEqual(calls, [("average", False), ("inclusive", True), ("third", True)])
        self.assertEqual(r.qualified_by(1), 3)
        returned = next(e for e in r.events if e['event']=='guide_returned')
        b_done = next(e for e in r.events if e['event']=='task_finished' and e['task_id']=='average')
        a_start = next(e for e in r.events if e['event']=='executor_start' and e['task_id']=='inclusive')
        self.assertLess(returned['time'], b_done['time'])
        prefetched = next(e for e in r.events if e['event']=='guide_start' and e['task_id']=='third')
        self.assertLess(prefetched['time'], b_done['time'])
        self.assertGreater(a_start['time'], b_done['time'])
        self.assertFalse(any(e['event']=='cancel_local_task' for e in r.events))

    async def test_sequential_control_does_not_work_on_b_while_a_waits(self):
        calls = []
        outer = self
        class Guide:
            async def diagnose(self, snapshot, seed):
                await asyncio.sleep(0.03)
                return outer.diags[snapshot.task_id]
        class Agent:
            async def propose(self, snapshot, message, seed):
                calls.append(snapshot.task_id)
                return [outer.repair(snapshot.task_id)]
        r = await BatchDelegate(Agent(), Guide(), BatchConfig(mode="sequential", deadline=1)).run(self.tasks)
        self.assertEqual(calls, ['inclusive', 'average'])
        self.assertEqual(r.qualified_by(1), 2)

    async def test_failed_b_is_parked_and_receives_only_its_own_guidance(self):
        outer = self
        calls, guides = [], []
        guide_active = 0
        class Guide:
            async def diagnose(self, snapshot, seed):
                nonlocal guide_active
                guide_active += 1
                outer.assertEqual(guide_active, 1)
                guides.append(snapshot.task_id)
                await asyncio.sleep(0.04)
                guide_active -= 1
                return outer.diags[snapshot.task_id]
        class Agent:
            async def propose(self, snapshot, message, seed):
                calls.append((snapshot.task_id, bool(message)))
                if message:
                    outer.assertEqual(message.anchors, outer.diags[snapshot.task_id].anchors)
                    outer.assertEqual(message.request_version, snapshot.version)
                    return [outer.repair(snapshot.task_id)]
                return [Action('edit', 'calc.py', '// len(xs)', '* len(xs)')]
        r = await BatchDelegate(Agent(), Guide(), BatchConfig(deadline=1)).run(self.tasks)
        self.assertEqual(calls, [('average',False),('inclusive',True),('average',True)])
        self.assertEqual(guides, ['inclusive','average'])
        self.assertTrue(all(x.success for x in r.results))
        self.assertTrue(any(e['event']=='task_parked' and e['task_id']=='average' for e in r.events))

    async def test_guide_failure_is_isolated_from_other_tasks(self):
        outer = self
        class Guide:
            async def diagnose(self, snapshot, seed):
                raise RuntimeError('provider unavailable')
        class Agent:
            async def propose(self, snapshot, message, seed):
                return [outer.repair(snapshot.task_id)]
        r = await BatchDelegate(Agent(), Guide(), BatchConfig(deadline=1)).run(self.tasks)
        self.assertEqual(r.results[0].reason, 'guide_error')
        self.assertTrue(r.results[1].success)
        self.assertEqual(r.qualified_by(1), 1)

    async def test_global_deadline_cancels_guide_and_executor_without_leaks(self):
        cancelled = set()
        class Guide:
            async def diagnose(self, snapshot, seed):
                try:
                    await asyncio.Future()
                finally:
                    cancelled.add('guide')
        class Agent:
            async def propose(self, snapshot, message, seed):
                try:
                    await asyncio.Future()
                finally:
                    cancelled.add('executor')
        r = await BatchDelegate(Agent(), Guide(), BatchConfig(deadline=0.12)).run(self.tasks)
        self.assertEqual(r.reason, 'deadline')
        self.assertEqual(cancelled, {'guide','executor'})
        self.assertEqual(r.qualified_by(1), 0)
        self.assertTrue(all(x.files == t.files for x,t in zip(r.results,self.tasks)))
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_name().startswith('vda-batch')])

    async def test_hidden_quality_does_not_change_online_completion(self):
        outer = self
        class Guide:
            async def diagnose(self, snapshot, seed):
                await asyncio.sleep(0.03)
                return outer.diags[snapshot.task_id]
        class Agent:
            async def propose(self, snapshot, message, seed):
                if snapshot.task_id == 'average':
                    source = snapshot.files['calc.py']
                    return [Action('edit', 'calc.py', source, 'def average(xs):\n    return 1.5\n')]
                return [outer.repair(snapshot.task_id)]
        r = await BatchDelegate(Agent(), Guide(), BatchConfig(deadline=1)).run(self.tasks)
        self.assertTrue(all(x.visible_pass for x in r.results))
        self.assertFalse(r.results[1].success)
        self.assertEqual(r.qualified_by(1), 1)
        self.assertFalse(any('hidden' in e['event'] for e in r.events))

    async def test_rejects_duplicate_ids_and_mismatched_snapshots(self):
        runtime = BatchDelegate(None, None, BatchConfig())
        with self.assertRaises(ValueError):
            await runtime.run([self.tasks[0], self.tasks[0]])
        with self.assertRaises(ValueError):
            await runtime.run(self.tasks, {'inclusive':CodeEnvironment(self.tasks[1]).snapshot()})

    async def test_full_code_adapter_uses_atomic_patch_without_rewriting_output(self):
        outer = self
        task = self.tasks[1]
        class Model:
            async def complete(self, payload):
                outer.assertEqual(payload['response_format'],'python_code')
                outer.assertEqual(payload['seed'],0)
                outer.assertNotIn('heldout.py',payload['snapshot']['files'])
                return {'code':'def average(xs):\n    return 1.5\n'}
        actions = await CompleteCodeAgent(Model()).propose(CodeEnvironment(task).snapshot(),None,0)
        self.assertEqual(actions[0].kind,'patch')
        self.assertEqual(actions[0].edits[0]['new'],'def average(xs):\n    return 1.5\n')
