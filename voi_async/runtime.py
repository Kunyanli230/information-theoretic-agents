"""Actual nonblocking guide + executor loop, with a single mutation boundary."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
import hashlib
import random
import time

from .environment import CodeEnvironment
from .information import ArrivalEncoder
from .learning import ValueBundle
from .models import Agent, Guide
from .planning import WorkPlanner, fusion_decision
from .types import Action, Message, RunResult, Snapshot, TaskSpec, candidates, digest


def subseed(seed: int, *parts) -> int:
    text = "|".join(map(str, (seed, *parts)))
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)


@dataclass(frozen=True)
class Config:
    mode: str = "async"                  # async, sync, none
    message_mode: str = "info"           # info, fixed
    deadline: float = 30.0
    expected_delay: float = 1.0          # forecast, NOT future observed service time
    max_steps: int = 100
    max_requests: int = 1
    seed: int = 0
    force_request: bool = False          # explicitly a fixed-timing ablation
    deterministic_encoder: bool = False # explicit argmax ablation
    compatibility_planning: bool = True
    max_speculative_steps: int = 1      # bounded work per in-flight request

    def __post_init__(self):
        if self.mode not in {"async", "sync", "none"}:
            raise ValueError("invalid run mode")
        if self.message_mode not in {"info", "fixed"}:
            raise ValueError("invalid message mode")
        if (self.deadline <= 0 or self.expected_delay < 0
                or self.max_steps < 1 or self.max_requests < 0
                or self.max_speculative_steps < 0):
            raise ValueError("invalid deadline/limits")


class AsyncDelegate:
    def __init__(self, agent: Agent, guide: Guide, values: ValueBundle,
                 config: Config, planner: WorkPlanner | None = None):
        self.agent, self.guide, self.values = agent, guide, values
        self.config = config
        self.planner = planner or WorkPlanner()
        self.encoder = ArrivalEncoder(values.value, values.beta)
        self.events: list[dict] = []
        self.start = 0.0

    def log(self, event: str, **data):
        self.events.append(dict(time=time.monotonic() - self.start,
                                event=event, **data))

    def remaining(self) -> float:
        return max(0, self.config.deadline - (time.monotonic() - self.start))

    async def _guide_job(self, snapshot: Snapshot, request_no: int,
                         remaining: float, override: Message | None) -> Message:
        started = time.monotonic()
        z = await self.guide.diagnose(
            snapshot, subseed(self.config.seed, snapshot.task_id, "guide", request_no))
        delay = time.monotonic() - started
        ms = candidates(z, snapshot)
        if override is not None:
            selected = override
            self.log("encoded", kind="calibration_override", message=asdict(selected),
                     message_hash=selected.id)
        elif self.config.message_mode == "fixed":
            selected = next(m for m in ms
                            if set(m.fields) == {"location", "cause", "change"})
            self.log("encoded", kind="fixed", message=asdict(selected),
                     message_hash=selected.id)
        else:
            # Only request snapshot + observed own service time. No live env.
            result = self.encoder.encode(
                snapshot, ms, delay, max(0, remaining - delay),
                random.Random(subseed(self.config.seed, snapshot.task_id,
                                      "encoder", request_no)),
                deterministic=self.config.deterministic_encoder)
            selected = result.message
            self.log("encoded", kind="information", message=asdict(selected),
                     message_hash=selected.id, probabilities=result.probabilities,
                     distortions=result.distortions, objective=result.objective,
                     rate_upper_bound=result.expected_kl_to_reference,
                     reference_log_probabilities=result.reference_log_probabilities,
                     wire_bits=result.wire_bits)
        self.log("guide_returned", request_no=request_no, service_time=delay)
        return selected

    async def _fuse(self, env: CodeEnvironment, message: Message | None) -> Message | None:
        # No tool mutations run concurrently with this operation.
        for result in await env.reconcile():
            self.log("reconcile", **result)
        if message is None:
            return None
        if env.visible_pass:
            self.log("fusion", decision="already_solved", message_hash=message.id)
            return None
        decision = fusion_decision(message, env.snapshot())
        if decision == "verify":
            observation = await env.execute(Action("test"))
            self.log("fusion_verification", ok=observation.ok)
            self.log("fusion", decision="already_solved" if observation.ok else "discard",
                     message_hash=message.id)
            return None
        self.log("fusion", decision=decision, message_hash=message.id,
                 received_version=env.snapshot().version)
        # Rebase only the protocol anchor; the executor sees BOTH the original
        # advice and current files. No unverified patch is applied by the guide.
        return replace(message, request_version=env.snapshot().version)

    async def run(self, task: TaskSpec, initial: Snapshot | None = None,
                  message_override: Message | None = None) -> RunResult:
        env = CodeEnvironment(task, initial)
        self.start, self.events = time.monotonic(), []
        self.log("start", task_id=task.task_id, config=asdict(self.config),
                 predictor_provenance=self.values.provenance,
                 models={name: getattr(getattr(actor, "model", None), "metadata",
                                       {"adapter": type(actor).__name__}).copy()
                         for name, actor in (("executor", self.agent), ("guide", self.guide))},
                 work_model="calibrated" if self.planner.work_statistics else "dependency_heuristic",
                 initial_hash=env.snapshot().state_id)
        guide_task = proposal_task = tool_task = None
        pending_snapshot = None
        ready_message = None
        delivery_ready = False
        guide_failed = False
        active = None
        requests = 0
        checked_state = None
        proposal_state = None
        speculative_steps = 0
        current_action = None
        reason = "step_limit"
        submitted = False
        task_elapsed = 0.0
        try:
            async with asyncio.timeout(self.config.deadline):
                while True:
                    if guide_task is not None and guide_task.done():
                        guide_failed = False
                        try:
                            ready_message = guide_task.result()
                        except Exception as exc:
                            ready_message = None
                            guide_failed = True
                            self.log("guide_error", error=type(exc).__name__)
                        guide_task = None
                        delivery_ready = True
                        # Interrupt unfinished inference, but retain a completed
                        # candidate for public validation before fusing advice.
                        if (not guide_failed and proposal_task is not None
                                and not proposal_task.done()):
                            self.log("proposal_cancelled", reason="guide_arrived")
                            proposal_task.cancel()
                            await asyncio.gather(proposal_task, return_exceptions=True)
                            proposal_task = None

                    if tool_task is not None and tool_task.done():
                        observation = tool_task.result()
                        self.planner.belief.update(self.planner.family(current_action), observation)
                        self.log("tool_end", action=asdict(current_action),
                                 observation=asdict(observation),
                                 output_hash=digest(asdict(observation)),
                                 state_hash=env.snapshot().state_id,
                                 while_in_flight=pending_snapshot is not None)
                        tool_task = None

                    if env.visible_pass:
                        reason, submitted = "visible_verified", True
                        break

                    if proposal_task is not None and proposal_task.done():
                        try:
                            actions = proposal_task.result()
                            if not actions:
                                raise ValueError("empty executor action set")
                        except Exception as exc:
                            self.log("executor_error", error=type(exc).__name__,
                                     speculative=pending_snapshot is not None)
                            if pending_snapshot is None:
                                reason = "executor_error"
                                break
                            # A failed speculative decode must not lose the
                            # already-requested guidance or cause a retry loop.
                            actions = []
                            speculative_steps = self.config.max_speculative_steps
                        proposal_task = None
                        if proposal_state != env.snapshot().state_id:
                            self.log("proposal_discarded", reason="state_changed")
                            continue
                        if actions:
                            if pending_snapshot is not None and self.config.compatibility_planning:
                                ranked = self.planner.rank(
                                    actions + [Action("wait", seconds=0.01)],
                                    env.snapshot(), pending_snapshot)
                            else:
                                ranked = self.planner.rank(actions, env.snapshot(), None)
                            _, current_action, parts = ranked[0]
                            self.log("tool_start", action=asdict(current_action), scores=parts,
                                     while_in_flight=pending_snapshot is not None)
                            # Validate immediately in an isolated copy. Only a
                            # passing patch commits, at the single tool boundary;
                            # guide delivery never mutates the environment.
                            tool_task = asyncio.create_task(
                                env.execute(current_action), name="vda-tool")

                    if delivery_ready and tool_task is None and proposal_task is None:
                        active = await self._fuse(env, ready_message)
                        delivery_ready, ready_message, pending_snapshot = False, None, None
                        if env.visible_pass:
                            reason, submitted = "visible_verified", True
                            break
                        if guide_failed and requests >= self.config.max_requests:
                            # No new advice can arrive. Do not restart the same
                            # unguided inference after exhausting this request.
                            reason = "guide_error"
                            break

                    if env.step >= self.config.max_steps:
                        reason = "step_limit"
                        break

                    if (guide_task is None and not delivery_ready and tool_task is None
                            and proposal_task is None and requests < self.config.max_requests
                            and self.config.mode != "none"):
                        snapshot = env.snapshot()
                        if snapshot.state_id != checked_state:
                            checked_state = snapshot.state_id
                            gain = self.values.gain(
                                snapshot, self.config.expected_delay, self.remaining())
                            request = ((self.config.force_request or gain > self.values.threshold)
                                       and self.remaining() > self.config.expected_delay)
                            self.log("gate", state_hash=snapshot.state_id, step=snapshot.step,
                                     gain=gain, request=request, sees_diagnosis=False,
                                     remaining=self.remaining())
                            if request:
                                pending_snapshot = snapshot
                                speculative_steps = 0
                                self.log("request", request_no=requests, snapshot_hash=snapshot.state_id)
                                guide_task = asyncio.create_task(
                                    self._guide_job(snapshot, requests, self.remaining(), message_override),
                                    name="vda-guide")
                                requests += 1

                    blocked = pending_snapshot is not None and (
                        self.config.mode == "sync"
                        or speculative_steps >= self.config.max_speculative_steps)
                    if (proposal_task is None and tool_task is None and not delivery_ready
                            and not blocked):
                        snapshot = env.snapshot()
                        proposal_state = snapshot.state_id
                        if pending_snapshot is not None:
                            speculative_steps += 1
                        model_seed = subseed(self.config.seed, task.task_id, "executor", snapshot.step)
                        self.log("executor_start", state_hash=proposal_state,
                                 message_hash=active.id if active else None, seed=model_seed,
                                 input_hash=digest({"snapshot": snapshot.public(),
                                                    "message": asdict(active) if active else None}))
                        proposal_task = asyncio.create_task(
                            self.agent.propose(snapshot, active, model_seed),
                            name="vda-proposal")

                    waiting = [f for f in (guide_task, proposal_task, tool_task) if f is not None]
                    if not waiting:
                        reason = "no_work"
                        break
                    await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
        except TimeoutError:
            reason = "deadline"
        finally:
            task_elapsed = time.monotonic() - self.start
            tasks = [f for f in (guide_task, proposal_task, tool_task) if f is not None]
            for future in tasks:
                if not future.done():
                    future.cancel()
                    self.log("cancel_local_task", task=future.get_name(),
                             remote_cancellation_confirmed=False)
            await asyncio.gather(*tasks, return_exceptions=True)
            if env.staged:
                self.log("uncommitted_discarded", count=len(env.staged))
            self.log("task_end", reason=reason, submitted=submitted,
                     task_elapsed=task_elapsed, requests=requests)
        success = None
        if task.hidden_test:
            # Evaluation after submission: never returned to the runtime.
            success = (await env.check(hidden=True))[0] if submitted else False
            self.log("heldout_evaluation", success=success, feedback_to_agent=False)
        return RunResult(task.task_id, self.config.mode, task_elapsed, reason,
                         dict(env.files), submitted and env.visible_pass, success, self.events)
