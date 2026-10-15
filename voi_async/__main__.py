from __future__ import annotations
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .calibration import collect_forks
from .batch import BatchConfig, BatchDelegate
from .complete_code import CompleteCodeAgent
from .evaluation import factorial
from .fixtures import fixture_tasks, FixtureGuideSet
from .hf_backend import HFProcessModel
from .learning import ValueBundle, fit_values
from .models import CommandAgent, CommandGuide, CursorModel, FixtureAgent, JSONCommandModel
from .planning import WorkPlanner
from .runtime import AsyncDelegate, Config
from .types import TaskSpec


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def task_specs(path):
    data = json.loads(Path(path).read_text())
    return [TaskSpec(**t) for t in data["tasks"]]


def real_models(path):
    data = json.loads(Path(path).read_text())
    def adapter(config):
        config = dict(config)
        kind = config.pop("kind", "command")
        if kind == "command":
            return JSONCommandModel(**config)
        if kind == "cursor":
            return CursorModel(**config)
        if kind == "hf":
            return HFProcessModel(**config)
        if kind != "openai":
            raise ValueError("model kind must be cursor, hf, command or openai")
        timeout = config.pop("timeout", 120)
        # Isolated import path prevents package types.py shadowing stdlib types.
        argv = [sys.executable, "-I", str(Path(__file__).with_name("http_worker.py")),
                "--timeout", str(timeout)]
        for key in ("base_url", "model", "key_env", "temperature", "max_tokens"):
            if key in config:
                argv.extend(["--" + key.replace("_", "-"), str(config.pop(key))])
        if config.pop("json_mode", False):
            argv.append("--json-mode")
        if config:
            raise ValueError(f"unknown model settings: {list(config)}")
        return JSONCommandModel(argv, timeout=timeout)
    executor = dict(data["executor"])
    protocol = executor.pop("protocol", "actions")
    if protocol not in {"actions", "complete_code"}:
        raise ValueError("executor protocol must be actions or complete_code")
    agent = CompleteCodeAgent if protocol == "complete_code" else CommandAgent
    return agent(adapter(executor)), CommandGuide(adapter(data["guide"]))


async def demo(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tasks, diagnoses = fixture_tasks()
    # These are actual local code/test executions with synthetic model fixtures.
    rows = await collect_forks(
        tasks, FixtureAgent(), FixtureGuideSet(diagnoses),
        delays=[0.06], seeds=[0, 1], deadline=0.7, max_steps=12)
    write_json(out / "calibration.json", rows)
    values = fit_values(rows, penalty=0.1)
    values.provenance += "; SYNTHETIC FIXTURE DATA, not model performance evidence"
    values.save(out / "values.json")
    summary = []
    for mode in ("sync", "async"):
        for message_mode in ("fixed", "info"):
            result = await AsyncDelegate(
                FixtureAgent(), FixtureGuideSet(diagnoses, delay=0.18), values,
                Config(mode=mode, message_mode=message_mode, deadline=1.2,
                       expected_delay=0.18, max_steps=40, seed=7,
                       force_request=True, deterministic_encoder=True)).run(tasks[0])
            name = f"{mode}-{message_mode}"
            write_json(out / f"{name}.json", asdict(result))
            starts = [e["time"] for e in result.events if e["event"] == "tool_start"]
            returns = [e["time"] for e in result.events if e["event"] == "guide_returned"]
            summary.append(dict(
                arm=name, elapsed=round(result.elapsed, 4), success=result.success,
                tools_before_guide=sum(t < returns[0] for t in starts) if returns else 0))
    write_json(out / "summary.json",
               {"label": "synthetic integration demonstration, not a research result",
                "arms": summary})
    print(json.dumps({"out": str(out.resolve()), "label": "synthetic fixture",
                      "arms": summary}, indent=2))


async def collect(args):
    tasks = task_specs(args.tasks)
    agent, guide = args.live_models
    out = Path(args.out)
    if out.exists():
        raise ValueError("refusing to overwrite calibration log; choose a new path")
    out.parent.mkdir(parents=True, exist_ok=True)
    def append(row):
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    rows = await collect_forks(tasks, agent, guide, args.delays, args.seeds,
                               args.deadline, args.max_steps, append,
                               prefix_steps=args.prefix_steps)
    print(json.dumps({"trials": len(rows), "out": str(out.resolve())}))


def fit(args):
    text = Path(args.data).read_text()
    rows = json.loads(text) if text.lstrip().startswith("[") else [
        json.loads(line) for line in text.splitlines() if line.strip()]
    values = fit_values(rows, args.beta, args.penalty, args.threshold)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    values.save(args.out)
    print(json.dumps({"training_tasks": values.training_tasks, "out": args.out}))


async def run(args):
    tasks = task_specs(args.tasks)
    agent, guide = args.live_models
    values = ValueBundle.load(args.values)
    overlap = set(values.training_tasks) & {t.task_id for t in tasks}
    if overlap and not args.allow_training_tasks:
        raise ValueError(f"evaluation overlaps calibration tasks: {sorted(overlap)}")
    for task in tasks:
        planner = WorkPlanner()
        if args.work_records:
            planner = WorkPlanner.from_records(json.loads(Path(args.work_records).read_text()))
        result = await AsyncDelegate(
            agent, guide, values,
            Config(mode=args.mode, message_mode=args.message_mode, deadline=args.deadline,
                   expected_delay=args.expected_delay, max_steps=args.max_steps,
                   max_speculative_steps=args.max_speculative_steps,
                   seed=args.seed, force_request=args.force_request,
                   deterministic_encoder=args.argmax),
            planner=planner).run(task)
        # Task IDs are not accepted as paths.
        name = str(len(list(Path(args.out).glob("episode-*.json")))) if Path(args.out).exists() else "0"
        write_json(Path(args.out) / f"episode-{name}.json", asdict(result))
        print(json.dumps(dict(task=task.task_id, success=result.success,
                              elapsed=result.elapsed, reason=result.reason)))


async def evaluate(args):
    agent, guide = args.live_models
    report = await factorial(task_specs(args.tasks), agent, guide,
                             ValueBundle.load(args.values), args.out,
                             args.deadlines, args.seeds, args.expected_delay,
                             args.max_steps)
    print(json.dumps(report, indent=2))


async def batch(args):
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("choose an empty batch output directory")
    agent, guide = args.live_models
    result = await BatchDelegate(agent, guide, BatchConfig(
        mode=args.mode, deadline=args.deadline, seed=args.seed,
        max_unassisted_steps=args.max_unassisted_steps,
        max_guided_steps=args.max_guided_steps,
        prefetch_guides=not args.no_guide_prefetch)).run(task_specs(args.tasks))
    write_json(out / "batch.json", asdict(result))
    print(json.dumps(dict(elapsed=result.elapsed, reason=result.reason,
                         qualified=result.qualified_by(args.deadline),
                         tasks=len(result.results))))


async def dispatch(args):
    models = ()
    try:
        if args.command in {"collect", "run", "evaluate", "batch"}:
            args.live_models = real_models(args.models)
            models = tuple(actor.model for actor in args.live_models)
            for model in models:
                prepare = getattr(model, "prepare", None)
                if prepare:
                    await prepare()
        await {"demo": demo, "collect": collect, "run": run,
               "evaluate": evaluate, "batch": batch}[args.command](args)
    finally:
        for model in models:
            close = getattr(model, "aclose", None)
            if close:
                await close()


def main():
    p = argparse.ArgumentParser(description="Stage-2 executable asynchronous delegation")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("demo", help="local synthetic integration run; no network/model download")
    d.add_argument("--out", default="results_stage2/demo")
    c = sub.add_parser("collect", help="execute calibration forks with configured model processes")
    c.add_argument("--tasks", required=True)
    c.add_argument("--models", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--delays", type=float, nargs="+", default=[0.5, 2.0])
    c.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3])
    c.add_argument("--deadline", type=float, default=60)
    c.add_argument("--max-steps", type=int, default=30)
    c.add_argument("--prefix-steps", type=int, nargs="+", default=[0, 2, 4])
    f = sub.add_parser("fit", help="task-cross-fitted arrival and pre-call value models")
    f.add_argument("--data", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--beta", type=float, default=0.0001)
    f.add_argument("--penalty", type=float, default=1.0)
    f.add_argument("--threshold", type=float, default=0.01)
    r = sub.add_parser("run", help="full tasks with real async model processes")
    for arg in ("tasks", "models", "values", "out"):
        r.add_argument("--" + arg, required=True)
    r.add_argument("--mode", choices=["async", "sync", "none"], default="async")
    r.add_argument("--message-mode", choices=["info", "fixed"], default="info")
    r.add_argument("--deadline", type=float, default=60)
    r.add_argument("--expected-delay", type=float, default=2)
    r.add_argument("--max-steps", type=int, default=100)
    r.add_argument("--max-speculative-steps", type=int, default=1,
                   help="maximum executor proposals per in-flight guide request (0 disables speculation)")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--force-request", action="store_true")
    r.add_argument("--argmax", action="store_true")
    r.add_argument("--allow-training-tasks", action="store_true")
    r.add_argument("--work-records")
    b = sub.add_parser("batch", help="one executor switches tasks while one guide request runs")
    for arg in ("tasks", "models", "out"):
        b.add_argument("--" + arg, required=True)
    b.add_argument("--mode", choices=["cross_task", "sequential"], default="cross_task")
    b.add_argument("--deadline", type=float, default=300)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--max-unassisted-steps", type=int, default=1)
    b.add_argument("--max-guided-steps", type=int, default=1)
    b.add_argument("--no-guide-prefetch", action="store_true",
                   help="only request guidance after an independent attempt fails (except bootstrap A)")
    e = sub.add_parser("evaluate", help="paired 2x2 message/schedule factorial with task-bootstrap CI")
    for arg in ("tasks", "models", "values", "out"):
        e.add_argument("--" + arg, required=True)
    e.add_argument("--deadlines", type=float, nargs="+", default=[30, 60, 120])
    e.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    e.add_argument("--expected-delay", type=float, default=2)
    e.add_argument("--max-steps", type=int, default=100)
    args = p.parse_args()
    if args.command == "fit":
        fit(args)
    else:
        asyncio.run(dispatch(args))


if __name__ == "__main__":
    main()
