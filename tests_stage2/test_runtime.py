import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from voi_async.environment import CodeEnvironment, safe_relative, stop_process
from voi_async.fixtures import fixture_tasks, FixtureGuideSet
from voi_async.learning import DIM, RidgePredictor, ValueBundle
from voi_async.models import FixtureAgent, FixtureGuide, JSONCommandModel
from voi_async.planning import WorkPlanner, fusion_decision
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

    async def test_patch_on_guide_snapshot_beats_wait(self):
        snapshot = CodeEnvironment(self.task).snapshot()
        action = Action("edit", "calc.py", "range(n)", "range(n + 1)")
        ranked = WorkPlanner().rank([Action("wait"), action], snapshot, snapshot)
        self.assertEqual(ranked[0][1], action)

    async def test_speculative_repair_finishes_without_guide(self):
        cancelled = asyncio.Event()
        class SlowGuide:
            async def diagnose(self, snapshot, seed):
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()
        class Repair:
            async def propose(self, snapshot, message, seed):
                return [Action("edit", "calc.py", "range(n)", "range(n + 1)")]
        r = await AsyncDelegate(Repair(), SlowGuide(), test_values(),
            Config(force_request=True, expected_delay=0, deadline=0.5)).run(self.task)
        self.assertTrue(r.success)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(any(e["event"] == "guide_returned" for e in r.events))
        self.assertEqual(sum(e["event"] == "executor_start" for e in r.events), 1)

    async def test_failed_speculation_rolls_back_and_waits_for_advice(self):
        attempts = []
        class Repair:
            async def propose(self, snapshot, message, seed):
                attempts.append(message is not None)
                self_source = snapshot.files["calc.py"]
                assert "range(n)" in self_source  # failed candidate never commits
                return [Action("edit", "calc.py", "range(n)",
                               "range(n + 1)" if message else "range(n - 1)")]
        r = await AsyncDelegate(Repair(), FixtureGuideSet(self.diags, 0.1), test_values(),
            Config(force_request=True, expected_delay=0, deadline=0.8)).run(self.task)
        self.assertTrue(r.success)
        self.assertEqual(attempts, [False, True])
        rejected = next(e for e in r.events if e["event"] == "tool_end")
        self.assertFalse(rejected["observation"]["ok"])
        self.assertTrue(rejected["while_in_flight"])

    async def test_completed_proposal_survives_simultaneous_guide_return(self):
        diagnosis = self.diags[self.task.task_id]
        class ImmediateGuide:
            async def diagnose(self, snapshot, seed):
                return diagnosis
        class ImmediateRepair:
            async def propose(self, snapshot, message, seed):
                assert message is None  # must not need a second generation
                return [Action("edit", "calc.py", "range(n)", "range(n + 1)")]
        r = await AsyncDelegate(ImmediateRepair(), ImmediateGuide(), test_values(),
            Config(force_request=True, expected_delay=0, deadline=0.5)).run(self.task)
        self.assertTrue(r.success)
        self.assertEqual(sum(e["event"] == "executor_start" for e in r.events), 1)

    async def test_guide_arrival_during_validation_keeps_single_writer(self):
        checking = asyncio.Event()
        diagnosis = self.diags[self.task.task_id]
        original_check = CodeEnvironment.check
        async def slow_check(env, files=None, hidden=False):
            if files is not None:
                checking.set()
                await asyncio.sleep(0.03)
            return await original_check(env, files, hidden)
        class GuideDuringCheck:
            async def diagnose(self, snapshot, seed):
                await checking.wait()
                return diagnosis
        class Repair:
            async def propose(self, snapshot, message, seed):
                return [Action("edit", "calc.py", "range(n)", "range(n + 1)")]
        with patch.object(CodeEnvironment, "check", slow_check):
            r = await AsyncDelegate(Repair(), GuideDuringCheck(), test_values(),
                Config(force_request=True, expected_delay=0, deadline=0.5)).run(self.task)
        self.assertTrue(r.success)
        events = [e["event"] for e in r.events]
        self.assertLess(events.index("guide_returned"), events.index("tool_end"))
        self.assertNotIn("fusion", events)  # solved before stale advice is used

    async def test_speculative_decode_error_does_not_drop_guide(self):
        calls = []
        class Repair:
            async def propose(self, snapshot, message, seed):
                calls.append(message is not None)
                if message is None:
                    raise ValueError("invalid model JSON")
                return [Action("edit", "calc.py", "range(n)", "range(n + 1)")]
        r = await AsyncDelegate(Repair(), FixtureGuideSet(self.diags, 0.04), test_values(),
            Config(force_request=True, expected_delay=0, deadline=0.5)).run(self.task)
        self.assertTrue(r.success)
        self.assertEqual(calls, [False, True])

    async def test_zero_speculation_budget_waits_for_guide(self):
        r = await AsyncDelegate(FixtureAgent(), FixtureGuideSet(self.diags, 0.03),
            test_values(), Config(force_request=True, expected_delay=0, deadline=0.5,
                                  max_speculative_steps=0)).run(self.task)
        self.assertTrue(r.success)
        self.assertFalse(any(e["event"] == "tool_start" and e["while_in_flight"]
                             for e in r.events))

    async def test_deadline_during_speculative_validation_cannot_commit(self):
        cancelled = asyncio.Event()
        original = dict(self.task.files)
        async def unfinished_check(env, files=None, hidden=False):
            self.assertIsNotNone(files)
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
        class Repair:
            async def propose(self, snapshot, message, seed):
                return [Action("edit", "calc.py", "range(n)", "range(n + 1)")]
        with patch.object(CodeEnvironment, "check", unfinished_check):
            r = await AsyncDelegate(Repair(), FixtureGuideSet(self.diags, 2), test_values(),
                Config(force_request=True, expected_delay=0, deadline=0.08)).run(self.task)
        self.assertEqual(r.reason, "deadline")
        self.assertFalse(r.success)
        self.assertEqual(r.files, original)
        self.assertTrue(cancelled.is_set())
        self.assertFalse([t for t in asyncio.all_tasks() if t.get_name().startswith("vda-")])

    async def test_failed_guide_keeps_inflight_candidate_without_retry_loop(self):
        for valid in (False, True):
            calls = []
            class FailedGuide:
                async def diagnose(self, snapshot, seed):
                    raise RuntimeError("provider unavailable")
            class Repair:
                async def propose(self, snapshot, message, seed):
                    calls.append(message)
                    await asyncio.sleep(0.02)
                    return [Action("edit", "calc.py", "range(n)",
                                   "range(n + 1)" if valid else "range(n - 1)")]
            r = await AsyncDelegate(Repair(), FailedGuide(), test_values(),
                Config(force_request=True, expected_delay=0, deadline=0.5)).run(self.task)
            self.assertEqual(r.success, valid)
            self.assertEqual(r.reason, "visible_verified" if valid else "guide_error")
            self.assertEqual(calls, [None])

    @unittest.skipUnless(os.path.isdir("/proc"), "Linux process-state regression")
    async def test_cancel_reaps_group_when_descendant_ignores_term(self):
        script = (
            "import os,signal,time\n"
            "child=os.fork()\n"
            "if child == 0:\n"
            " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            " print(os.getpid(),flush=True)\n"
            " time.sleep(30)\n"
            "else:\n"
            " time.sleep(30)\n")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script, stdout=asyncio.subprocess.PIPE,
            start_new_session=True)
        try:
            child = int(await asyncio.wait_for(proc.stdout.readline(), 1))
            await stop_process(proc)
            # An adopted zombie can await init's reap, but must not run work.
            for _ in range(100):
                status = Path(f"/proc/{child}/stat")
                if not status.exists() or status.read_text().split()[2] == "Z":
                    break
                await asyncio.sleep(0.01)
            else:
                self.fail("cancelled CLI left a running descendant")
            self.assertIsNotNone(proc.returncode)
        finally:
            await stop_process(proc)

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
