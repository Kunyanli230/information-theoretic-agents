"""Executable counterfactual forks; task-separated fitting lives in learning."""
from __future__ import annotations

from dataclasses import asdict
import time

from .environment import CodeEnvironment
from .learning import DIM, RidgePredictor, ValueBundle
from .models import Agent, Guide, FixtureGuide
from .planning import WorkPlanner
from .runtime import AsyncDelegate, Config
from .types import Action, TaskSpec, candidates


async def public_prefixes(tasks: list[TaskSpec], agent: Agent,
                          prefix_steps: list[int], max_steps: int):
    """Sample later decision boundaries using only unassisted PUBLIC feedback.

    Each fork gets a fresh residual wall-clock budget. Prefix generation is
    outside that conditional continuation experiment and never uses heldout labels.
    """
    if not prefix_steps or any(n < 0 or n + 1 >= max_steps for n in prefix_steps):
        raise ValueError("prefix steps must leave at least one continuation step")
    wanted = set(prefix_steps)
    for task in tasks:
        if not task.hidden_test:
            raise ValueError("calibration requires a private terminal evaluator")
        env = CodeEnvironment(task)
        feedback = await env.execute(Action("test"))
        if feedback.ok:
            continue
        planner = WorkPlanner()
        for n in range(max(wanted) + 1):
            if n in wanted:
                yield task, env.snapshot()
            if n == max(wanted):
                break
            snapshot = env.snapshot()
            actions = await agent.propose(snapshot, None, n)
            if not actions:
                break
            action = planner.rank(actions, snapshot, None)[0][1]
            observation = await env.execute(action)
            planner.belief.update(planner.family(action), observation)
            if env.visible_pass:
                break


def collection_bundle() -> ValueBundle:
    # Collection forces a fixed request and exact message. These coefficients
    # are NEVER represented as a trained predictor or used for policy claims.
    return ValueBundle(RidgePredictor([0.0] * DIM),
                       RidgePredictor([0.0] * DIM, -1, 1),
                       0.0001, 0.01, [], "collection-only; fixed interventions")


async def collect_forks(tasks: list[TaskSpec], agent: Agent, guide: Guide,
                        delays: list[float], seeds: list[int], deadline: float,
                        max_steps: int = 30, on_row=None,
                        prefix_steps: list[int] | None = None) -> list[dict]:
    """One fresh diagnosis per public prefix, then delayed cached forks.

    The teacher computation time is logged; each intervention reuses the same
    payload with controlled delay. This is calibration simulation, not a claim
    that a live teacher finished earlier. Rows are resumable JSONL via on_row.
    """
    rows = []
    async for task, snapshot in public_prefixes(tasks, agent, prefix_steps or [0], max_steps):
        started = time.monotonic()
        diagnosis = await guide.diagnose(snapshot, 0)
        service_time = time.monotonic() - started
        messages = candidates(diagnosis, snapshot)
        for delay in delays:
            if not 0 <= delay < deadline:
                raise ValueError("calibration delay must be below deadline")
            for seed in seeds:
                common = dict(deadline=deadline, expected_delay=delay,
                              seed=seed, max_steps=max_steps, force_request=True)
                control = await AsyncDelegate(
                    agent, FixtureGuide(diagnosis, delay), collection_bundle(),
                    Config(mode="none", **common)).run(task, initial=snapshot)
                branches = []
                for message in messages:
                    result = await AsyncDelegate(
                        agent, FixtureGuide(diagnosis, delay), collection_bundle(),
                        Config(mode="async", **common)).run(
                            task, initial=snapshot, message_override=message)
                    branches.append(dict(message=asdict(message), success=result.success,
                                         elapsed=result.elapsed, reason=result.reason,
                                         events=result.events))
                row = dict(schema="voi-async-forks-v1",
                           snapshot=snapshot.public(), diagnosis=asdict(diagnosis),
                           teacher_service_time=service_time,
                           delay=delay, remaining=deadline - delay,
                           request_remaining=deadline, seed=seed,
                           control=control.success, control_events=control.events,
                           messages=branches, max_requests=1,
                           protocol="controlled delayed cached diagnosis; live executor")
                rows.append(row)
                if on_row:
                    on_row(row)
    return rows
