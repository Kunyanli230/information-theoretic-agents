"""Offline topology distances for a declared projection of stage2 event logs.

Each selected semantic decision is one round, in recorded order. This is not a
reconstruction of every Python loop iteration or every implicit environment node.
Payload text, hashes, observations and wall-clock timestamps are excluded.

Usage: python -m voi_async.trajectory_shape LEFT.json RIGHT.json --out report.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

PROFILES = ("observed_control_v1", "observed_tools_v1")


def _decision(action: str, parameters: dict, node: str, index: int) -> dict:
    return dict(a=action, Q=parameters, node=node, source_event_index=index)


def project(events: list[dict], profile: str = "observed_control_v1") -> list[dict]:
    """Allowlist structural fields; never compare the full serialized Action."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    rounds = []
    for index, event in enumerate(events):
        name = event["event"]
        decision = None
        if name == "tool_start":
            action = event["action"]
            kind = action["kind"]
            if kind not in {"read", "edit", "patch", "test", "submit", "wait"}:
                raise ValueError(f"unknown tool kind: {kind}")
            params: dict[str, Any] = {}
            if kind == "patch":
                # Ordering and multiplicity are part of the patch call interface.
                params["paths"] = [edit["path"] for edit in action["edits"]]
            elif kind in {"read", "edit"}:
                params["path"] = action["path"]
            elif kind == "wait":
                params["seconds"] = action["seconds"]  # requested, not observed
            decision = _decision("TOOL_" + kind.upper(), params, "tool:" + kind, index)
        elif profile == "observed_control_v1":
            if name in {"request", "guide_start"}:
                decision = _decision("REQUEST_GUIDANCE", {}, "guide", index)
            elif name == "executor_start":
                if "message_hash" not in event:
                    raise ValueError("executor_start lacks guidance-presence marker")
                decision = _decision("GENERATE", {
                    "guided": event["message_hash"] is not None,
                }, "executor", index)
            elif name in {"fusion", "guidance_ready"}:
                decision = _decision("FUSE_GUIDANCE", {
                    "decision": event["decision"],
                }, "fusion", index)
            elif name == "task_parked":
                decision = _decision("PARK", {"reason": event["reason"]}, "park", index)
            elif name in {"proposal_cancelled", "proposal_discarded"}:
                decision = _decision("CANCEL_GENERATION" if name == "proposal_cancelled"
                                     else "DISCARD_GENERATION", {
                    "reason": event["reason"],
                }, "proposal_control", index)
            elif name in {"task_end", "task_finished"}:
                decision = _decision("STOP", {"reason": event["reason"]}, "stop", index)
        if decision is not None:
            rounds.append(decision)
    return rounds


def distance(left: list[dict], right: list[dict]) -> dict:
    """Prefix mismatch count, not edit distance; trailing rounds are excluded."""
    common = min(len(left), len(right))
    mismatch = [dict(t=i + 1, left=left[i], right=right[i])
                for i in range(common)
                if (left[i]["a"], left[i]["Q"]) != (right[i]["a"], right[i]["Q"])]
    counts_l = Counter(x["node"] for x in left)
    counts_r = Counter(x["node"] for x in right)
    nodes = sorted(counts_l.keys() | counts_r.keys())
    delta = {node: abs(counts_l[node] - counts_r[node]) for node in nodes}
    return dict(D_shape=len(mismatch), shape_changed=bool(mismatch),
                k_left=len(left), k_right=len(right), common_rounds=common,
                empty_common_prefix=common == 0,
                mismatch_fraction=len(mismatch) / common if common else None,
                unmatched_tail_rounds=abs(len(left) - len(right)),
                D_iter_observed=sum(delta.values()),
                node_counts_left=dict(counts_l), node_counts_right=dict(counts_r),
                node_count_differences=delta,
                auxiliary_D_struct_observed=set(counts_l) != set(counts_r),
                mismatches=mismatch)


def read_run(path: str | Path) -> tuple[dict[str, dict], dict]:
    """Read a batch.json or a single RunResult episode; fail on missing traces."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("expected batch.json or episode.json object")
    rows = data.get("results") if "results" in data else [data]
    if not isinstance(rows, list) or not rows:
        raise ValueError("run contains no task episodes")
    tasks = {}
    for row in rows:
        task = row["task_id"]
        if task in tasks:
            raise ValueError(f"duplicate task ID: {task}")
        if not isinstance(row.get("events"), list) or not row["events"]:
            raise ValueError(f"missing recorded events for {task}")
        tasks[task] = row
    start = next((e for e in data.get("events", [])
                  if e["event"] in {"start", "batch_start"}), {})
    return tasks, start.get("config", {})


def compare_runs(left_path: str | Path, right_path: str | Path,
                 profile: str = "observed_control_v1") -> dict:
    left, config_l = read_run(left_path)
    right, config_r = read_run(right_path)
    if left.keys() != right.keys():
        raise ValueError("task sets differ; explicitly select matching episodes")
    pairs = []
    for task in sorted(left):
        l, r = left[task], right[task]
        rounds_l, rounds_r = project(l["events"], profile), project(r["events"], profile)
        pairs.append(dict(task_id=task, **distance(rounds_l, rounds_r),
                          rounds_left=rounds_l, rounds_right=rounds_r,
                          quality_left={k: l.get(k) for k in ("visible_pass", "success", "reason")},
                          quality_right={k: r.get(k) for k in ("visible_pass", "success", "reason")}))
    return dict(schema="stage2_shape_comparison_v1", profile=profile,
                round_definition="one selected semantic decision event; per task, recorded order",
                left=str(left_path), right=str(right_path),
                config_left=config_l, config_right=config_r,
                config_differences={k: [config_l.get(k), config_r.get(k)]
                                    for k in sorted(config_l.keys() | config_r.keys())
                                    if config_l.get(k) != config_r.get(k)},
                pair_count=len(pairs), changed_pair_count=sum(p["shape_changed"] for p in pairs),
                changed_pair_rate=sum(p["shape_changed"] for p in pairs) / len(pairs),
                empty_prefix_pairs=[p["task_id"] for p in pairs if p["empty_common_prefix"]],
                caveats=["A declared observed-event projection, not the paper's original controller graph.",
                         "Implicit public-test and unlogged gate/commit nodes are not reconstructed.",
                         "D_iter and D_struct cover observed node IDs only; D_struct is auxiliary.",
                         "Same task IDs alone do not establish a controlled causal comparison.",
                         "Zero shape distance does not imply equal outputs or quality; empty prefixes are vacuous."],
                pairs=pairs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("--profile", choices=PROFILES, default=PROFILES[0])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    target = Path(args.out)
    if target.exists():
        parser.error("output already exists; choose a new path")
    result = compare_runs(args.left, args.right, args.profile)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in
                      ("profile", "pair_count", "changed_pair_count", "changed_pair_rate", "empty_prefix_pairs")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
