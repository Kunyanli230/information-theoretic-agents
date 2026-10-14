"""Resident local Transformers process; generation never blocks the event loop."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import signal
import sys

from .environment import stop_process
from .models import parse_json

MODEL_ID = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
MODEL_REVISION = "ea3f2471cf1b1f0db85067f1ef93848e38e88c25"


class HFProcessModel:
    def __init__(self, model: str = MODEL_ID, revision: str = MODEL_REVISION,
                 device: str = "cpu", threads: int = 6, temperature: float = 0.7,
                 top_p: float = 0.95, max_new_tokens: int = 256,
                 timeout: float = 120, load_timeout: float = 300,
                 cancel_grace: float = 2, local_files_only: bool = False):
        if (threads < 1 or max_new_tokens < 1 or temperature < 0
                or not 0 < top_p <= 1 or min(timeout, load_timeout, cancel_grace) <= 0):
            raise ValueError("invalid HF generation or timeout settings")
        self.settings = dict(model=model, revision=revision, device=device,
                             threads=threads, temperature=temperature, top_p=top_p,
                             max_new_tokens=max_new_tokens, local_files_only=local_files_only)
        self.timeout, self.load_timeout, self.cancel_grace = timeout, load_timeout, cancel_grace
        self.metadata = dict(backend="transformers-resident-process", **self.settings,
                             dtype="float32", prepared=False)
        self._process = None
        self._lock = asyncio.Lock()

    def worker_command(self):
        # -I avoids local types.py shadowing the standard library in a worker.
        return [sys.executable, "-I", str(Path(__file__).with_name("hf_worker.py")),
                "--config", json.dumps(self.settings)]

    async def _stop(self):
        process, self._process = self._process, None
        self.metadata["prepared"] = False
        if process is not None:
            await stop_process(process)

    async def _start(self):
        if self._process is not None and self._process.returncode is None:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self.worker_command(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, limit=2_000_000)
        try:
            line = await asyncio.wait_for(self._process.stdout.readline(), self.load_timeout)
            status = json.loads(line)
            if not status.get("ready"):
                raise RuntimeError("HF worker initialization failed: " + str(status.get("error", "unknown")))
            self.metadata.update(status.get("metadata", {}), prepared=True)
        except BaseException:
            await self._stop()
            raise

    async def prepare(self):
        """Load once before episode clocks start; CLI logs ready metadata."""
        async with self._lock:
            await self._start()

    async def _interrupt(self):
        """Stop at a token boundary and drain one response to retain warm weights."""
        process = self._process
        if process is None or process.returncode is not None:
            await self._stop()
            return
        try:
            process.send_signal(signal.SIGUSR1)
            line = await asyncio.wait_for(process.stdout.readline(), self.cancel_grace)
            if not line:
                await self._stop()
            else:
                json.loads(line)  # Preserve only a synchronized JSONL worker.
        except (TimeoutError, ProcessLookupError, ValueError):
            await self._stop()

    async def complete(self, payload: dict) -> dict:
        async with self._lock:
            await self._start()
            process = self._process
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
                await process.stdin.drain()
                line = await asyncio.wait_for(process.stdout.readline(), self.timeout)
            except (asyncio.CancelledError, TimeoutError):
                await self._interrupt()
                raise
            except BaseException:
                await self._stop()
                raise
            if not line:
                await self._stop()
                raise RuntimeError("HF worker exited during generation")
            response = json.loads(line)
            if "error" in response:
                raise RuntimeError("HF generation failed: " + response["error"])
            return parse_json(response["text"])

    async def aclose(self):
        async with self._lock:
            await self._stop()
