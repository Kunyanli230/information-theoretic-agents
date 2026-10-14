import asyncio
from dataclasses import replace
import json
import sys
import unittest

from voi_async.environment import CodeEnvironment, safe_relative
from voi_async.fixtures import fixture_tasks, FixtureGuideSet
from voi_async.learning import DIM, RidgePredictor, ValueBundle
from voi_async.models import FixtureAgent, FixtureGuide, JSONCommandModel
from voi_async.planning import fusion_decision
from voi_async.runtime import AsyncDelegate, Config
from voi_async.types import Action, Message, Snapshot


def test_values():
    # Explicit test fixture: transmitted "change" has positive value.
    arrival = [0.0] * DIM
    arrival[8] = 1.0
    gate = [0.0] * DIM
    gate[0] = 0.9
    return ValueBundle(RidgePredictor(arrival), RidgePredictor(gate, -1, 1),
                       0.00001, 0.01, [], "unit-test coefficients")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tasks, self.diags = fixture_tasks(tool_delay=0.01)
        self.task = self.tasks[0]

    async def run_fixture(self, mode, deadline=1.0, delay=0.08):
        return await AsyncDelegate(
            FixtureAgent(), FixtureGuideSet(self.diags, delay), test_values(),
            Config(mode=mode, deadline=deadline, expected_delay=0.001,
                   max_steps=100, deterministic_encoder=True)).run(self.task)

    async def test_real_overlap_and_sync_wait(self):
        for mode in ("async", "sync"):
            r = await self.run_fixture(mode)
            self.assertTrue(r.success)
            arrival = next(e["time"] for e in r.events if e["event"] == "guide_returned")
            early_tools = [e for e in r.events if e["event"] == "tool_start"
                           and e["time"] < arrival]
            self.assertEqual(bool(early_tools), mode == "async")
            fusion = next(e["time"] for e in r.events if e["event"] == "fusion")
            advised = [e for e in r.events if e["event"] == "executor_start"
                       and e["message_hash"]]
            self.assertTrue(all(e["time"] >= fusion for e in advised))
            gate = next(e for e in r.events if e["event"] == "gate")
            self.assertFalse(gate["sees_diagnosis"])

    async def test_deadline_cancels_pending_and_no_orphan_tasks(self):
        r = await self.run_fixture("async", deadline=0.03, delay=2)
        self.assertEqual(r.reason, "deadline")
        self.assertFalse(r.success)
        self.assertTrue(any(e["event"] == "cancel_local_task" for e in r.events))
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_name().startswith("vda-")])

    async def test_a_a_normalized_feedback(self):
        a, b = CodeEnvironment(self.task), CodeEnvironment(self.task)
        oa = await a.execute(Action("test"))
        ob = await b.execute(Action("test"))
        self.assertEqual(oa, ob)
        self.assertNotIn("/tmp/vda-", oa.text)
        self.assertEqual(a.snapshot().state_id, b.snapshot().state_id)

    async def test_staged_edit_does_not_mutate_before_validation(self):
        env = CodeEnvironment(self.task)
        action = Action("edit", "calc.py", "range(n)", "range(n + 1)")
        old = env.snapshot().version
        await env.execute(action, speculative=True)
        self.assertEqual(env.snapshot().version, old)
        result = await env.reconcile()
        self.assertEqual(result[0]["status"], "committed")
        self.assertNotEqual(env.snapshot().version, old)

    async def test_conflicting_staged_patch_cannot_overwrite(self):
        env = CodeEnvironment(self.task)
        action = Action("edit", "calc.py", "range(n)", "range(n + 1)")
        await env.execute(action, speculative=True)
        env.files["calc.py"] = "def total(n):\n    return 99\n"
        results = await env.reconcile()
        self.assertEqual(results[0]["status"], "conflict")
        self.assertIn("99", env.files["calc.py"])

    async def test_bad_patch_is_rolled_back(self):
        env = CodeEnvironment(self.task)
        old = dict(env.files)
        obs = await env.execute(Action("edit", "calc.py", "range(n)", "range(n - 1)"))
        self.assertFalse(obs.ok)
        self.assertEqual(env.files, old)

    async def test_private_tests_never_in_snapshot(self):
        env = CodeEnvironment(self.task)
        self.assertNotIn("heldout.py", env.snapshot().files)
        await env.check(hidden=True)
        self.assertNotIn("heldout.py", env.snapshot().files)
        self.assertFalse(env.observations)

    async def test_fusion_rebases_unrelated_changes_checks_missing_anchor(self):
        sn = CodeEnvironment(self.task).snapshot()
        m = Message(sn.version, {"change": "repair"}, {"calc.py": "range(n)"})
        self.assertEqual(fusion_decision(m, sn), "apply")
        changed = Snapshot(sn.task_id, sn.description, {**sn.files, "other.txt": "new"})
        self.assertEqual(fusion_decision(m, changed), "rebase")
        changed.files["calc.py"] = "different"
        self.assertEqual(fusion_decision(m, changed), "verify")

    async def test_invalid_message_discarded_after_check(self):
        bad = replace(self.diags[self.task.task_id], anchors={"calc.py": "missing"})
        r = await AsyncDelegate(
            FixtureAgent(), FixtureGuide(bad, 0.01), test_values(),
            Config(deadline=0.2, expected_delay=0.001,
                   deterministic_encoder=True)).run(self.task)
        self.assertTrue(any(e["event"] == "fusion" and e["decision"] == "discard"
                            for e in r.events))
        self.assertFalse(r.success)

    async def test_arrival_interrupts_slow_executor_proposal(self):
        class SlowProposal(FixtureAgent):
            async def propose(self, snapshot, message, seed):
                if message is None:
                    await asyncio.sleep(2)
                return [Action("edit", **json.loads(message.fields["change"]))]
        r = await AsyncDelegate(
            SlowProposal(), FixtureGuideSet(self.diags, 0.03), test_values(),
            Config(deadline=0.5, expected_delay=0.001,
                   deterministic_encoder=True)).run(self.task)
        self.assertTrue(r.success)
        self.assertLess(r.elapsed, 0.5)

    async def test_gate_rechecked_after_waiting_at_first_boundary(self):
        class LaterValues:
            beta, threshold, provenance = 0.00001, 0.01, "test later trigger"
            value = test_values().value
            def gain(self, snapshot, delay, remaining):
                return 0.9 if snapshot.step >= 1 else -0.1
        r = await AsyncDelegate(
            FixtureAgent(), FixtureGuideSet(self.diags, 0.02), LaterValues(),
            Config(deadline=0.7, expected_delay=0.001,
                   deterministic_encoder=True)).run(self.task)
        gates = [e for e in r.events if e["event"] == "gate"]
        self.assertFalse(gates[0]["request"])
        self.assertTrue(any(e["request"] and e["step"] >= 1 for e in gates))
        self.assertTrue(r.success)

    async def test_actual_json_process_adapter(self):
        script = "import sys,json; x=json.load(sys.stdin); print(json.dumps({'echo':x['seed']}))"
        model = JSONCommandModel([sys.executable, "-c", script])
        self.assertEqual(await model.complete({"seed": 7}), {"echo": 7})

    async def test_model_process_timeout(self):
        model = JSONCommandModel(
            [sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.03)
        with self.assertRaises(TimeoutError):
            await model.complete({})

    async def test_paths_cannot_escape_task(self):
        for path in ("../x", "/tmp/x", "a/../../x", "a\\b"):
            with self.assertRaises(ValueError):
                safe_relative(path)


if __name__ == "__main__":
    unittest.main()
