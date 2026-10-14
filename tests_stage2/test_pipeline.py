import asyncio
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

from voi_async.__main__ import real_models
from voi_async.calibration import public_prefixes
from voi_async.environment import CodeEnvironment
from voi_async.evaluation import ARMS, factorial, summarize
from voi_async.fixtures import fixture_tasks, FixtureGuideSet
from voi_async.learning import DIM, RidgePredictor, ValueBundle, fit_values
from voi_async.models import FixtureAgent
from voi_async.types import Action, TaskSpec, candidates


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_multifile_patch_is_atomic(self):
        task = TaskSpec("multi", "both constants must equal 1",
                        {"a.py": "A = 0\n", "b.py": "B = 0\n"},
                        [sys.executable, "-c", "from a import A; from b import B; assert A == B == 1"])
        env = CodeEnvironment(task)
        one = await env.execute(Action("edit", "a.py", "A = 0", "A = 1"))
        self.assertFalse(one.ok)
        patch = Action.from_dict({"kind": "patch", "edits": [
            {"path": "a.py", "old": "A = 0", "new": "A = 1"},
            {"path": "b.py", "old": "B = 0", "new": "B = 1"}]})
        result = await env.execute(patch)
        self.assertTrue(result.ok)
        self.assertEqual(env.files, {"a.py": "A = 1\n", "b.py": "B = 1\n"})

    async def test_multifile_conflict_cannot_partially_commit(self):
        tasks, _ = fixture_tasks()
        env = CodeEnvironment(tasks[0])
        before = dict(env.files)
        action = Action.from_dict({"kind": "patch", "edits": [
            {"path": "calc.py", "old": "range(n)", "new": "range(n + 1)"},
            {"path": "missing.py", "old": "a", "new": "b"}]})
        self.assertFalse((await env.execute(action)).ok)
        self.assertEqual(env.files, before)

    async def test_collects_later_public_prefixes(self):
        tasks, _ = fixture_tasks(tool_delay=0)
        snapshots = [snapshot async for task, snapshot in
                     public_prefixes(tasks[:1], FixtureAgent(), [0, 2], 10)]
        self.assertEqual([s.step for s in snapshots], [1, 3])
        self.assertTrue(any(o.kind == "read" for o in snapshots[1].observations))
        self.assertNotIn("heldout.py", snapshots[1].files)

    async def test_real_http_bridge_and_protocol(self):
        tasks, diagnoses = fixture_tasks()
        received = []
        async def respond(reader, writer):
            header = await reader.readuntil(b"\r\n\r\n")
            n = next(int(line.split(b":", 1)[1]) for line in header.split(b"\r\n")
                     if line.lower().startswith(b"content-length:"))
            body = json.loads(await reader.readexactly(n))
            payload = json.loads(body["messages"][1]["content"])
            received.append((header, body, payload))
            obj = asdict(diagnoses[tasks[0].task_id]) if payload["role"] == "guide" else {
                "actions": [{"kind": "test"}]}
            data = json.dumps({"choices": [{"message": {"content": json.dumps(obj)}}]}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(data)).encode() + b"\r\nConnection: close\r\n\r\n" + data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            settings = dict(kind="openai", base_url=f"http://127.0.0.1:{port}/v1",
                            model="local-protocol-test", key_env="VDA_TEST_UNUSED_KEY",
                            json_mode=True, timeout=2)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, "models.json")
                path.write_text(json.dumps({"executor": settings, "guide": settings}))
                agent, guide = real_models(path)
                snapshot = CodeEnvironment(tasks[0]).snapshot()
                diagnosis, actions = await asyncio.gather(
                    guide.diagnose(snapshot, 19), agent.propose(snapshot, None, 19))
        self.assertEqual(diagnosis, diagnoses[tasks[0].task_id])
        self.assertEqual(actions, [Action("test")])
        self.assertEqual(len(received), 2)
        for header, body, payload in received:
            self.assertTrue(header.startswith(b"POST /v1/chat/completions "))
            self.assertEqual(body["seed"], 19)
            self.assertNotIn("heldout.py", payload["snapshot"]["files"])

    def test_factorial_interaction_and_failure_time(self):
        records = []
        for task in ("a", "b"):
            for mode, message in ARMS:
                success = mode == "async" and message == "info"
                records.append(dict(task_id=task, deadline=10,
                                    arm=f"{mode}-{message}", success=success,
                                    elapsed=1, overlap_tools=0))
        report = summarize(records, bootstrap=30)["by_deadline"]["10"]
        self.assertEqual(report["information_async_interaction"], 1)
        self.assertEqual(report["interaction_task_bootstrap_95ci"], [1, 1])
        self.assertEqual(report["arms"]["sync-fixed"]["restricted_time_to_success"], 10)

    async def test_factorial_runner_executes_all_arms(self):
        tasks, diagnoses = fixture_tasks(tool_delay=0.002)
        weights = [0.0] * DIM
        weights[8] = 1.0
        values = ValueBundle(RidgePredictor(weights), RidgePredictor([0.0] * DIM),
                             0.00001, 0, [], "factorial unit-test coefficients")
        with tempfile.TemporaryDirectory() as tmp:
            report = await factorial(tasks[:1], FixtureAgent(),
                                     FixtureGuideSet(diagnoses, 0.03), values,
                                     tmp, [0.8], [0], 0.03, max_steps=60)
            self.assertEqual(len(list(Path(tmp).glob("episode-*.json"))), 4)
            for arm in report["by_deadline"]["0.8"]["arms"].values():
                self.assertEqual(arm["success"], 1)
            self.assertIsNone(report["by_deadline"]["0.8"]["interaction_task_bootstrap_95ci"])
            with self.assertRaises(ValueError):
                await factorial(tasks[:1], FixtureAgent(),
                                FixtureGuideSet(diagnoses, 0.03), values,
                                tmp, [0.8], [0], 0.03)

    def test_fit_serialization_and_task_split(self):
        tasks, diagnoses = fixture_tasks()
        rows = []
        for task in tasks:
            sn = CodeEnvironment(task).snapshot()
            rows.append(dict(snapshot=sn.public(), delay=0.1, remaining=1,
                             request_remaining=1.1, control=False,
                             messages=[dict(message=asdict(m), success="change" in m.fields)
                                       for m in candidates(diagnoses[task.task_id], sn)]))
        values = fit_values(rows)
        self.assertEqual(set(values.training_tasks), {t.task_id for t in tasks})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "values.json")
            values.save(path)
            self.assertEqual(values, ValueBundle.load(path))
        with self.assertRaises(ValueError):
            fit_values(rows[:1])


if __name__ == "__main__":
    unittest.main()
