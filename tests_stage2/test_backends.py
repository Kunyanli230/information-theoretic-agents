import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from voi_async.hf_backend import HFProcessModel
from voi_async.models import CursorModel


COOPERATIVE_WORKER = """
import json,os,signal,sys,time
cancelled=False
def stop(signum,frame):
    global cancelled
    cancelled=True
signal.signal(signal.SIGUSR1,stop)
print(json.dumps({'ready':True,'metadata':{'worker_pid':os.getpid()}}),flush=True)
for line in sys.stdin:
    cancelled=False
    payload=json.loads(line)
    end=time.monotonic()+payload.get('pause',0)
    while time.monotonic()<end and not cancelled:
        time.sleep(.002)
    text=json.dumps({'seed':payload['seed'],'worker_pid':os.getpid()})
    print(json.dumps({'text':text,'cancelled':cancelled}),flush=True)
"""


class ProcessFixture(HFProcessModel):
    """Real process transport fixture, no pretrained-model performance claim."""
    def worker_command(self):
        return [sys.executable, "-c", COOPERATIVE_WORKER]


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_cursor_ask_mode_explicit_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp, "agent")
            binary.write_text(
                "#!" + sys.executable + "\n"
                "import json,os,sys\n"
                "print(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd(),'files':os.listdir()}))\n")
            binary.chmod(0o755)
            model = CursorModel(binary=str(binary))
            response = await model.complete({"seed": 7, "instruction": "JSON only"})
        argv = response["argv"]
        self.assertIn("--mode=ask", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "grok-4.6")
        self.assertEqual(argv[argv.index("--output-format") + 1], "text")
        self.assertEqual(argv[argv.index("--workspace") + 1], response["cwd"])
        self.assertEqual(response["files"], [])
        self.assertEqual(json.loads(argv[-1])["seed"], 7)
        self.assertFalse(Path(response["cwd"]).exists())

    async def test_resident_worker_nonblocking_and_reuses_loaded_process(self):
        model = ProcessFixture()
        try:
            await model.prepare()
            pid = model.metadata["worker_pid"]
            inference = asyncio.create_task(model.complete({"seed": 17, "pause": .08}))
            ticks = 0
            while not inference.done():
                await asyncio.sleep(.01)
                ticks += 1
            self.assertGreaterEqual(ticks, 3)
            self.assertEqual((await inference)["worker_pid"], pid)
            self.assertEqual((await model.complete({"seed": 18}))["worker_pid"], pid)
        finally:
            await model.aclose()
        self.assertIsNone(model._process)

    async def test_cancel_generation_keeps_weights_and_drains_old_response(self):
        model = ProcessFixture()
        try:
            await model.prepare()
            pid = model.metadata["worker_pid"]
            inference = asyncio.create_task(model.complete({"seed": 99, "pause": 2}))
            await asyncio.sleep(.03)
            inference.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await inference
            new = await model.complete({"seed": 7})
            self.assertEqual(new["seed"], 7)
            self.assertEqual(new["worker_pid"], pid)
        finally:
            await model.aclose()

    async def test_timeout_stops_generation_and_worker_remains_usable(self):
        model = ProcessFixture(timeout=.03)
        try:
            await model.prepare()
            with self.assertRaises(TimeoutError):
                await model.complete({"seed": 99, "pause": 2})
            self.assertEqual((await model.complete({"seed": 7}))["seed"], 7)
        finally:
            await model.aclose()

    async def test_unresponsive_worker_is_reaped_and_restarted(self):
        class Unresponsive(ProcessFixture):
            def worker_command(self):
                code = COOPERATIVE_WORKER.replace("cancelled=True", "pass")
                return [sys.executable, "-c", code]
        model = Unresponsive(timeout=.03, cancel_grace=.03)
        try:
            await model.prepare()
            old = model._process
            with self.assertRaises(TimeoutError):
                await model.complete({"seed": 99, "pause": 2})
            self.assertIsNotNone(old.returncode)
            self.assertIsNone(model._process)
            self.assertNotEqual((await model.complete({"seed": 7}))["worker_pid"], old.pid)
        finally:
            await model.aclose()


if __name__ == "__main__":
    unittest.main()
