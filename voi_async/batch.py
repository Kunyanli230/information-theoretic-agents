"""Cross-task scheduling with one executor and one in-flight guide request.

A waiting task is parked, not speculatively regenerated. Guide-ready tasks take
priority at executor action boundaries; another task's generation is never
cancelled to switch tasks. Held-out evaluation happens after scheduling ends.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import time

from .environment import CodeEnvironment
from .models import Agent, Guide
from .planning import WorkPlanner, fusion_decision
from .types import Action, Message, RunResult, Snapshot, TaskSpec


@dataclass(frozen=True)
class BatchConfig:
    mode: str = "cross_task"  # sequential is the same routing without switching
    deadline: float = 300.0   # one wall-clock budget for the entire batch
    seed: int = 0            # passed unchanged to every model call
    max_unassisted_steps: int = 1
    max_guided_steps: int = 1
    prefetch_guides: bool = True

    def __post_init__(self):
        if self.mode not in {"cross_task", "sequential"}:
            raise ValueError("invalid batch mode")
        if (self.deadline <= 0 or self.max_unassisted_steps < 0
                or self.max_guided_steps < 1):
            raise ValueError("invalid batch limits")


@dataclass
class BatchResult:
    elapsed: float
    reason: str
    results: list[RunResult]
    completion_times: dict[str, float]
    events: list[dict]
    evaluation_seconds: float

    def qualified_by(self, seconds: float) -> int:
        """Post-run quality audit, never available to the scheduling policy."""
        return sum(r.success is True and r.visible_pass
                   and self.completion_times[r.task_id] <= seconds
                   for r in self.results)


@dataclass
class _State:
    env: CodeEnvironment
    status: str = "ready_unassisted"
    message: Message | None = None
    unassisted_steps: int = 0
    guided_steps: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    reason: str = ""
    submitted: bool = False

    @property
    def task_id(self):
        return self.env.task.task_id


class BatchDelegate:
    def __init__(self, agent: Agent, guide: Guide, config: BatchConfig):
        self.agent, self.guide, self.config = agent, guide, config
        self.events: list[dict] = []
        self.start = 0.0
        self.planner = WorkPlanner()

    def log(self, event, task_id=None, **data):
        self.events.append(dict(time=time.monotonic() - self.start,
                                event=event, task_id=task_id, **data))

    def _finish(self, state, reason, submitted=False):
        state.status, state.reason, state.submitted = "done", reason, submitted
        state.finished_at = time.monotonic() - self.start
        self.log("task_finished", state.task_id, reason=reason, submitted=submitted)

    async def _diagnose(self, state):
        snapshot = state.env.snapshot()
        self.log("guide_start", state.task_id, snapshot_hash=snapshot.state_id,
                 request_version=snapshot.version, seed=self.config.seed)
        z = await self.guide.diagnose(snapshot, self.config.seed)
        fields = {k: getattr(z, k) for k in ("location", "cause", "change", "verification")}
        if len(z.anchors) == 1:
            fields["applicable_if"] = next(iter(z.anchors.values()))
        message = Message(snapshot.version, fields, dict(z.anchors))
        self.log("guide_returned", state.task_id, message=asdict(message),
                 message_hash=message.id)
        return message

    async def _step(self, state, waiting_for):
        snapshot = state.env.snapshot()
        self.log("executor_start", state.task_id, snapshot_hash=snapshot.state_id,
                 message_hash=state.message.id if state.message else None,
                 waiting_for=waiting_for, seed=self.config.seed)
        actions = await self.agent.propose(snapshot, state.message, self.config.seed)
        if not actions:
            raise ValueError("empty executor action set")
        _, action, scores = self.planner.rank(actions, snapshot, None)[0]
        self.log("tool_start", state.task_id, action=asdict(action), scores=scores)
        observation = await state.env.execute(action)
        self.log("tool_end", state.task_id, action=asdict(action),
                 observation=asdict(observation), state_hash=state.env.snapshot().state_id)
        return observation

    async def run(self, tasks: list[TaskSpec],
                  initial: dict[str, Snapshot] | None = None) -> BatchResult:
        ids = [t.task_id for t in tasks]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("batch needs nonempty tasks with unique task IDs")
        initial = initial or {}
        if set(initial) - set(ids) or any(k != s.task_id for k, s in initial.items()):
            raise ValueError("initial snapshot/task mismatch")
        states = [_State(CodeEnvironment(t, initial.get(t.task_id))) for t in tasks]
        self.events, self.start = [], time.monotonic()
        self.log("batch_start", config=asdict(self.config), task_ids=ids,
                 executor_concurrency=1, guide_concurrency=1)
        guide_task = executor_task = None
        guiding = executing = None
        last_executor = None
        reason = "completed"
        try:
            async with asyncio.timeout(self.config.deadline):
                # Public initial failure feedback is included in the batch clock
                # unless callers explicitly supply their pre-existing snapshots.
                for state in states:
                    if state.task_id not in initial:
                        await state.env.execute(Action("test"))
                        if state.env.visible_pass:
                            self._finish(state, "initial_visible_verified", True)
                    if self.config.max_unassisted_steps == 0 and state.status != "done":
                        state.status = "needs_guide"
                first = next((s for s in states if s.status != "done"), None)
                if first:
                    # Bootstrap A's guide request while B is available to work.
                    first.status = "needs_guide"

                while any(s.status != "done" for s in states):
                    if guide_task is not None and guide_task.done():
                        try:
                            message = guide_task.result()
                            decision = fusion_decision(message, guiding.env.snapshot())
                            if decision == "verify":
                                observation = await guiding.env.execute(Action("test"))
                                self.log("fusion", guiding.task_id, decision="discard")
                                self._finish(guiding, "visible_verified" if observation.ok
                                             else "invalid_guidance", observation.ok)
                            else:
                                guiding.message, guiding.status = message, "ready_guided"
                                self.log("guidance_ready", guiding.task_id, decision=decision,
                                         executor_busy=executing.task_id if executing else None)
                        except Exception as exc:
                            self.log("guide_error", guiding.task_id, error=type(exc).__name__)
                            self._finish(guiding, "guide_error")
                        guide_task, guiding = None, None

                    if executor_task is not None and executor_task.done():
                        failed = False
                        try:
                            executor_task.result()
                        except Exception as exc:
                            failed = True
                            self.log("executor_error", executing.task_id, error=type(exc).__name__)
                        if executing.env.visible_pass:
                            self._finish(executing, "visible_verified", True)
                        elif executing.message is not None:
                            executing.guided_steps += 1
                            if failed or executing.guided_steps >= self.config.max_guided_steps:
                                self._finish(executing, "executor_error" if failed else "guided_limit")
                            else:
                                executing.status = "ready_guided"
                        else:
                            executing.unassisted_steps += 1
                            if failed or executing.unassisted_steps >= self.config.max_unassisted_steps:
                                executing.status = "needs_guide"
                                self.log("task_parked", executing.task_id, reason="needs_guidance")
                            else:
                                executing.status = "ready_unassisted"
                        executor_task, executing = None, None

                    pending = [s for s in states if s.status != "done"]
                    eligible = pending[:1] if self.config.mode == "sequential" else pending
                    if guide_task is None:
                        waiting = next((s for s in eligible if s.status == "needs_guide"), None)
                        if waiting is None and self.config.prefetch_guides:
                            # Keep the teacher pipeline busy on another untouched
                            # task. Never request advice for the currently running
                            # executor: its candidate must first be validated.
                            waiting = next((s for s in eligible
                                            if s.status == "ready_unassisted"), None)
                        if waiting:
                            guiding, waiting.status = waiting, "waiting_guide"
                            if waiting.started_at is None:
                                waiting.started_at = time.monotonic() - self.start
                            guide_task = asyncio.create_task(self._diagnose(waiting), name="vda-batch-guide")

                    if executor_task is None:
                        ready = next((s for s in eligible if s.status == "ready_guided"), None)
                        if ready is None:
                            ready = next((s for s in eligible if s.status == "ready_unassisted"), None)
                        if ready:
                            if ready.started_at is None:
                                ready.started_at = time.monotonic() - self.start
                            self.log("dispatch", ready.task_id, previous_task=last_executor,
                                     reason="guidance_ready" if ready.message else "other_task_work",
                                     while_guiding=guiding.task_id if guiding else None)
                            last_executor = ready.task_id
                            executing, ready.status = ready, "running"
                            executor_task = asyncio.create_task(
                                self._step(ready, guiding.task_id if guiding else None),
                                name="vda-batch-executor")

                    active = [t for t in (guide_task, executor_task) if t is not None]
                    if not active:
                        if pending:
                            raise RuntimeError("batch scheduler stalled")
                        break
                    await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
        except TimeoutError:
            reason = "deadline"
        finally:
            active = [t for t in (guide_task, executor_task) if t is not None]
            for task in active:
                if not task.done():
                    self.log("cancel_local_task", task=task.get_name(),
                             remote_cancellation_confirmed=False)
                    task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            for state in states:
                if state.status != "done":
                    self._finish(state, "deadline" if reason == "deadline" else "cancelled")
            elapsed = time.monotonic() - self.start
            self.log("batch_end", reason=reason, elapsed=elapsed)

        # Held-out outcomes cannot alter priority, retries, or stopping times.
        evaluation_start = time.monotonic()
        results = []
        for state in states:
            success = None
            if state.env.task.hidden_test:
                success = (await state.env.check(hidden=True))[0] if state.submitted else False
            events = [e for e in self.events if e["task_id"] == state.task_id]
            results.append(RunResult(
                state.task_id, self.config.mode,
                state.finished_at - (state.started_at or 0), state.reason,
                dict(state.env.files), state.submitted and state.env.visible_pass, success, events))
        return BatchResult(elapsed, reason, results,
                           {s.task_id: s.finished_at for s in states}, self.events,
                           time.monotonic() - evaluation_start)
