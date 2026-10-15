"""Copy-on-test workspace with staged compare-and-swap edits.

Local task commands run in separate directories, NOT a security sandbox.
Held-out test files are only materialized during post-run evaluation.
"""
from __future__ import annotations
import asyncio
import os
from pathlib import Path, PurePosixPath
import signal
import tempfile
from .types import Action, Observation, Snapshot, TaskSpec


def safe_relative(path: str) -> str:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in path:
        raise ValueError(f"not a relative task path: {path!r}")
    return str(p)


async def stop_process(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(proc.wait(), 0.3)
    except asyncio.TimeoutError:
        pass
    # A CLI launcher may exit on TERM while a descendant ignores it. Reaping
    # the leader alone does not clean up the process group we created.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await proc.wait()


async def run_command(argv: list[str], files: dict[str, str],
                      timeout: float) -> tuple[bool, str]:
    if not argv:
        raise ValueError("empty test command")
    with tempfile.TemporaryDirectory(prefix="vda-") as directory:
        for path, content in files.items():
            target = Path(directory, safe_relative(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=directory, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
            env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"})
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            await stop_process(proc)
            return False, "TIMEOUT"
        except BaseException:
            await stop_process(proc)
            raise
        text = (stdout + stderr).decode("utf-8", errors="replace")
        return proc.returncode == 0, text.replace(directory, "<workspace>")[-12000:]


class CodeEnvironment:
    def __init__(self, task: TaskSpec, initial: Snapshot | None = None):
        if set(task.files) & set(task.hidden_files):
            raise ValueError("held-out test files may not overlap public files")
        for path in list(task.files) + list(task.hidden_files):
            safe_relative(path)
        self.task = task
        self.files = dict(initial.files if initial else task.files)
        self.observations = list(initial.observations) if initial else []
        self.step = initial.step if initial else 0
        self.staged: list[Action] = []
        self.visible_pass = False

    def snapshot(self) -> Snapshot:
        return Snapshot(self.task.task_id, self.task.description, dict(self.files),
                        tuple(self.observations), self.step)

    async def check(self, files: dict[str, str] | None = None,
                    hidden: bool = False) -> tuple[bool, str]:
        contents = dict(self.files if files is None else files)
        if hidden:
            if not self.task.hidden_test:
                raise ValueError("no held-out evaluator configured")
            contents.update(self.task.hidden_files)
            cmd = self.task.hidden_test
        else:
            cmd = self.task.visible_test
        return await run_command(cmd, contents, self.task.test_timeout)

    def patched(self, action: Action) -> dict[str, str]:
        new = dict(self.files)
        edits = action.edits if action.kind == "patch" else (
            {"path": action.path, "old": action.old, "new": action.new},)
        if not edits:
            raise ValueError("empty patch")
        for edit in edits:
            path = safe_relative(edit["path"])
            if not edit["old"] or path not in new or new[path].count(edit["old"]) != 1:
                raise ValueError("edit conflict: old text absent or ambiguous")
            new[path] = new[path].replace(edit["old"], edit["new"], 1)
        return new

    async def execute(self, action: Action, speculative: bool = False) -> Observation:
        if self.task.tool_delay:
            await asyncio.sleep(self.task.tool_delay)
        ok, text = True, ""
        try:
            if action.kind == "wait":
                await asyncio.sleep(action.seconds)
                text = "waited"
            elif action.kind == "read":
                text = self.files[safe_relative(action.path)]
            elif action.kind in {"edit", "patch"}:
                new = self.patched(action)
                if speculative:
                    if action not in self.staged:
                        self.staged.append(action)
                    text = "staged in isolated branch; not committed"
                else:
                    ok, text = await self.check(new)
                    if ok:
                        self.files = new
                        self.visible_pass = True
                        text = "committed after visible verification\n" + text
                    else:
                        text = "edit rejected; main state unchanged\n" + text
            elif action.kind in {"test", "submit"}:
                ok, text = await self.check()
                self.visible_pass = ok
            else:
                raise ValueError("unknown action")
        except (ValueError, KeyError) as exc:
            ok, text = False, str(exc)
        observation = Observation(action.kind, action.path, text, ok)
        self.observations.append(observation)
        self.step += 1
        return observation

    async def reconcile(self) -> list[dict]:
        staged, self.staged = self.staged, []
        results = []
        for action in staged:
            try:
                new = self.patched(action)
                ok, feedback = await self.check(new)
            except ValueError as exc:
                results.append(dict(action=action.id, status="conflict", feedback=str(exc)))
                continue
            if ok:
                self.files = new
                self.visible_pass = True
            results.append(dict(action=action.id, status="committed" if ok else "rolled_back",
                                feedback=feedback))
        return results
