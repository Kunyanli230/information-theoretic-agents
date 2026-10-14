"""Paired factorial evaluation; no claims of improvement baked into metrics."""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import random
from statistics import mean

from .runtime import AsyncDelegate, Config

ARMS = (("sync", "fixed"), ("sync", "info"),
        ("async", "fixed"), ("async", "info"))


def summarize(records: list[dict], bootstrap: int = 2000, seed: int = 0) -> dict:
    """Task-cluster bootstrap: repeated seeds are not independent tasks."""
    if not records:
        raise ValueError("empty experiment")
    summary = {}
    for deadline in sorted({r["deadline"] for r in records}):
        group = [r for r in records if r["deadline"] == deadline]
        tasks = sorted({r["task_id"] for r in group})
        arms = {}
        task_values = {}
        for mode, msg in ARMS:
            arm = f"{mode}-{msg}"
            rows = [r for r in group if r["arm"] == arm]
            if not rows or any(r["success"] is None for r in rows):
                raise ValueError("complete factorial heldout evaluation required")
            by_task = {t: [r for r in rows if r["task_id"] == t] for t in tasks}
            if any(not v for v in by_task.values()):
                raise ValueError("missing task/arm pair")
            task_values[arm] = {t: mean(float(r["success"]) for r in rr)
                               for t, rr in by_task.items()}
            arms[arm] = dict(
                success=mean(task_values[arm].values()),
                restricted_time_to_success=mean(
                    mean(min(r["elapsed"], deadline) if r["success"] else deadline for r in rr)
                    for rr in by_task.values()),
                completed_nonwait_tools_during_guide=mean(
                    mean(r["overlap_tools"] for r in rr) for rr in by_task.values()))
        contrast = {t: task_values["async-info"][t] - task_values["async-fixed"][t]
                    - task_values["sync-info"][t] + task_values["sync-fixed"][t]
                    for t in tasks}
        ci = None
        if len(tasks) >= 2 and bootstrap > 0:
            rng = random.Random(seed)
            boot = sorted(mean(contrast[rng.choice(tasks)] for _ in tasks)
                          for _ in range(bootstrap))
            ci = [boot[int(0.025 * (bootstrap - 1))], boot[int(0.975 * (bootstrap - 1))]]
        summary[str(deadline)] = dict(
            independent_tasks=len(tasks), arms=arms,
            information_async_interaction=mean(contrast.values()),
            interaction_task_bootstrap_95ci=ci)
    return {"estimand": "fixed-trigger factorial; stochastic information encoder; heldout success",
            "by_deadline": summary}


async def factorial(tasks, agent, guide, values, out, deadlines, seeds,
                    expected_delay, max_steps=100, allow_training_tasks=False):
    """Equal trigger and teacher budget isolate message x schedule interaction.

    Gate evaluation is separate (CLI run without --force-request). Models must
    be stateless across complete() calls, as the supplied adapters are.
    """
    overlap = set(values.training_tasks) & {t.task_id for t in tasks}
    if overlap and not allow_training_tasks:
        raise ValueError("factorial evaluation overlaps calibration tasks")
    if not tasks or any(not t.hidden_test for t in tasks):
        raise ValueError("factorial needs tasks with heldout evaluators")
    if not deadlines or min(deadlines) <= expected_delay:
        raise ValueError("deadlines must exceed the guide-delay forecast")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("need distinct continuation seeds")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("choose an empty experiment output directory")
    out.mkdir(parents=True, exist_ok=True)
    records = []
    order_rng = random.Random(0)
    for task in tasks:
        for deadline in deadlines:
            for seed in seeds:
                arms = list(ARMS)
                order_rng.shuffle(arms)
                for mode, msg in arms:
                    result = await AsyncDelegate(
                        agent, guide, values,
                        Config(mode=mode, message_mode=msg, deadline=deadline,
                               expected_delay=expected_delay, max_steps=max_steps,
                               seed=seed, force_request=True)).run(task)
                    arrivals = [e["time"] for e in result.events if e["event"] == "guide_returned"]
                    end = arrivals[0] if arrivals else result.elapsed
                    overlap_tools = sum(e["event"] == "tool_end" and e["time"] < end
                                        and e["action"]["kind"] != "wait"
                                        for e in result.events)
                    artifact = f"episode-{len(records):05d}.json"
                    (out / artifact).write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2))
                    row = dict(task_id=task.task_id, seed=seed, deadline=deadline,
                               arm=f"{mode}-{msg}", success=result.success,
                               elapsed=result.elapsed, overlap_tools=overlap_tools,
                               artifact=artifact)
                    records.append(row)
                    with (out / "trials.jsonl").open("a") as f:
                        f.write(json.dumps(row) + "\n")
    report = summarize(records)
    (out / "summary.json").write_text(json.dumps(report, indent=2))
    return report
