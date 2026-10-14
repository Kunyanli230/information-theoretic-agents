"""Real JSON model-process adapters and explicitly synthetic smoke fixtures."""
from __future__ import annotations
import asyncio
from dataclasses import asdict
import json
import os
import re
import tempfile
from typing import Protocol
from .environment import stop_process
from .types import Action, Diagnosis, Message, Snapshot


class Guide(Protocol):
    async def diagnose(self, snapshot: Snapshot, seed: int) -> Diagnosis: ...


class Agent(Protocol):
    async def propose(self, snapshot: Snapshot, message: Message | None,
                      seed: int) -> list[Action]: ...


def parse_json(text: str) -> dict:
    text = text.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = re.sub("^" + fence + r"(?:json)?\s*", "", text)
        text = re.sub(r"\s*" + fence + "$", "", text)
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("model output must be one JSON object")
    return obj


class JSONCommandModel:
    """Actual model CLI, without a shell. stdin JSON or final prompt argument.

    Cancellation/timeout terminates and reaps the process group. Remote service
    cancellation is not guaranteed by killing its local client.
    """
    def __init__(self, argv: list[str], mode: str = "stdin", timeout: float = 120):
        if not argv or mode not in {"stdin", "argument"} or timeout <= 0:
            raise ValueError("invalid model command")
        self.argv, self.mode, self.timeout = argv, mode, timeout

    def command(self, data: str, directory: str) -> list[str]:
        return self.argv + ([data] if self.mode == "argument" else [])

    async def complete(self, payload: dict) -> dict:
        data = json.dumps(payload, ensure_ascii=False)
        with tempfile.TemporaryDirectory(prefix="vda-model-") as directory:
            proc = await asyncio.create_subprocess_exec(
                *self.command(data, directory), cwd=directory, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True)
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(data.encode() if self.mode == "stdin" else b""),
                    self.timeout)
            except BaseException:
                await stop_process(proc)
                raise
            if proc.returncode:
                raise RuntimeError(f"model process exited {proc.returncode}")
            if len(out) > 2_000_000:
                raise ValueError("model response too large")
            return parse_json(out.decode())


class CursorModel(JSONCommandModel):
    """Pinned headless ask-mode invocation in an explicit empty workspace."""
    def __init__(self, binary: str | None = None, model: str = "grok-4.6",
                 timeout: float = 300):
        binary = binary or os.environ.get("VOI_GUIDE_BIN", "agent")
        super().__init__([binary], mode="argument", timeout=timeout)
        self.model = model
        self.metadata = dict(backend="cursor-cli", model=model, binary=binary,
                             flags=["-p", "--mode=ask", "--output-format", "text", "--trust"],
                             workspace="empty temporary directory",
                             sampling="Cursor defaults; seed in prompt, no deterministic guarantee")

    def command(self, data: str, directory: str) -> list[str]:
        return self.argv + ["-p", "--mode=ask", "--model", self.model,
                            "--output-format", "text", "--workspace", directory,
                            "--trust", data]


class CommandGuide:
    def __init__(self, model: JSONCommandModel):
        self.model = model

    async def diagnose(self, snapshot: Snapshot, seed: int) -> Diagnosis:
        obj = await self.model.complete({
            "role": "guide", "seed": seed, "snapshot": snapshot.public(),
            "instruction": (
                "Diagnose the code task using ONLY this snapshot. Do not execute tools "
                "or edit files. Return JSON with nonempty strings location, cause, "
                "change, verification and anchors={relative_file: exact_nonempty_substring}. "
                "Give actionable advice, not a complete replacement implementation.")
        })
        diagnosis = Diagnosis.from_dict(obj)
        if any(path not in snapshot.files or snapshot.files[path].count(anchor) != 1
               for path, anchor in diagnosis.anchors.items()):
            raise ValueError("guide anchors must be unique in the request snapshot")
        return diagnosis


class CommandAgent:
    def __init__(self, model: JSONCommandModel):
        self.model = model

    async def propose(self, snapshot: Snapshot, message: Message | None,
                      seed: int) -> list[Action]:
        obj = await self.model.complete({
            "role": "executor", "seed": seed, "snapshot": snapshot.public(),
            "guidance": asdict(message) if message else None,
            "instruction": (
                "Return JSON {actions:[...]}, 1 to 6 candidate next actions. "
                "Allowed: {kind:read,path:relative_file}, {kind:test}, "
                "{kind:edit,path:relative_file,old:unique_exact_substring,new:replacement}, "
                "{kind:patch,edits:[{path:relative_file,old:unique_exact_substring,new:replacement},...]}, "
                "{kind:wait,seconds:0.01}, {kind:submit}. "
                "Use an atomic patch for coordinated changes in multiple files. "
                "Interpret guidance against CURRENT files and observations. "
                "Do not execute tools yourself. Edit public existing files only.")
        })
        raw = obj.get("actions")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
            raise ValueError("executor needs 1..6 actions")
        return [Action.from_dict(a) for a in raw]


class FixtureGuide:
    """Synthetic test double, not a pretrained model or an empirical result."""
    def __init__(self, diagnosis: Diagnosis, delay: float):
        self.diagnosis, self.delay = diagnosis, delay

    async def diagnose(self, snapshot: Snapshot, seed: int) -> Diagnosis:
        await asyncio.sleep(self.delay)
        return self.diagnosis


class FixtureAgent:
    """Deterministic integration fixture: gather evidence, follow a repair."""
    async def propose(self, snapshot: Snapshot, message: Message | None,
                      seed: int) -> list[Action]:
        await asyncio.sleep(0)
        read = {o.path for o in snapshot.observations if o.kind == "read"}
        if len(read) < len(snapshot.files):
            return [Action("read", path=p) for p in snapshot.files if p not in read][:6]
        if message and "change" in message.fields:
            change = json.loads(message.fields["change"])
            return [Action("edit", **change)]
        return [Action("wait", seconds=0.01)]
