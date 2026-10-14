"""Bayesian information gain and compatibility-aware speculative work."""
from __future__ import annotations
import math
from collections import defaultdict
from dataclasses import dataclass, field
from .types import Action, Message, Observation, Snapshot


def entropy(p: dict[str, float]) -> float:
    return -sum(x * math.log(x) for x in p.values() if x > 0)


def outcome_symbol(obs: Observation) -> str:
    return f"{obs.kind}:{'ok' if obs.ok else 'fail'}"


@dataclass
class Belief:
    prior: dict[str, float]
    likelihood: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

    def __post_init__(self):
        total = sum(self.prior.values())
        if total <= 0 or any(p < 0 for p in self.prior.values()):
            raise ValueError("invalid diagnostic prior")
        self.prior = {k: v / total for k, v in self.prior.items()}

    @classmethod
    def fit(cls, records: list[dict], alpha: float = 1.0) -> "Belief":
        """Records: offline hypothesis label, action family, public outcome."""
        if not records or alpha <= 0:
            raise ValueError("need labeled observations and positive smoothing")
        hs = sorted({r["hypothesis"] for r in records})
        families = sorted({r["family"] for r in records})
        counts = defaultdict(int)
        for r in records:
            counts[(r["family"], r["hypothesis"], r["outcome"])] += 1
        likelihood = {}
        for family in families:
            symbols = sorted({r["outcome"] for r in records if r["family"] == family})
            likelihood[family] = {}
            for h in hs:
                den = sum(counts[(family, h, o)] + alpha for o in symbols)
                likelihood[family][h] = {
                    o: (counts[(family, h, o)] + alpha) / den for o in symbols}
        return cls({h: 1 / len(hs) for h in hs}, likelihood)

    def expected_information(self, family: str) -> float:
        table = self.likelihood.get(family)
        if not table:
            return 0.0  # Missing calibration, not fabricated information.
        symbols = set().union(*(row.keys() for row in table.values()))
        expected_entropy = 0.0
        for symbol in symbols:
            weights = {h: p * table.get(h, {}).get(symbol, 0)
                       for h, p in self.prior.items()}
            prob = sum(weights.values())
            if prob:
                expected_entropy += prob * entropy({h: w / prob for h, w in weights.items()})
        return max(0.0, entropy(self.prior) - expected_entropy)

    def update(self, family: str, obs: Observation) -> None:
        table = self.likelihood.get(family)
        if not table:
            return
        weights = {h: p * table.get(h, {}).get(outcome_symbol(obs), 0)
                   for h, p in self.prior.items()}
        den = sum(weights.values())
        if den:
            self.prior = {h: w / den for h, w in weights.items()}


@dataclass
class WorkPlanner:
    belief: Belief = field(default_factory=lambda: Belief({"unknown": 1.0}))
    info_weight: float = 0.15
    conflict_weight: float = 0.5
    work_statistics: dict[str, dict[str, float]] = field(default_factory=dict)

    @staticmethod
    def family(action: Action) -> str:
        return f"{action.kind}:{action.path}"

    def rank(self, actions: list[Action], snapshot: Snapshot,
             pending_snapshot: Snapshot | None) -> list[tuple[float, Action, dict]]:
        ranked = []
        for a in actions:
            family = self.family(a)
            seen = any(o.kind == a.kind and o.path == a.path for o in snapshot.observations)
            if a.kind == "read":
                keep, progress, conflict = 1.0, (0.01 if seen else 0.25), 0.0
            elif a.kind == "test":
                keep, progress, conflict = 1.0, (0.01 if seen else 0.2), 0.0
            elif a.kind in {"edit", "patch"}:
                paths = [e["path"] for e in a.edits] if a.kind == "patch" else [a.path]
                conflict = float(pending_snapshot is not None and any(
                    p in pending_snapshot.files for p in paths))
                keep, progress = 1 - 0.8 * conflict, 0.7
            elif a.kind == "submit":
                keep, progress, conflict = 1.0, -0.2, 0.0
            else:
                keep, progress, conflict = 1.0, 0.0, 0.0
            calibrated = self.work_statistics.get(family)
            if calibrated:
                keep, progress, conflict = (calibrated[k] for k in ("keep", "progress", "conflict"))
            ig = self.belief.expected_information(family)
            score = keep * progress + self.info_weight * ig - self.conflict_weight * conflict
            ranked.append((score, a, dict(
                keep=keep, progress=progress, conflict=conflict, information_gain=ig,
                source="calibrated" if calibrated else "dependency_heuristic")))
        return sorted(ranked, key=lambda x: x[0], reverse=True)

    @classmethod
    def from_records(cls, records: list[dict]) -> "WorkPlanner":
        belief = Belief.fit(records)
        buckets = defaultdict(list)
        for r in records:
            if any(not 0 <= r[k] <= 1 for k in ("keep", "progress", "conflict")):
                raise ValueError("work labels must be in [0,1]")
            buckets[r["family"]].append(r)
        stats = {family: {k: sum(r[k] for r in rows) / len(rows)
                          for k in ("keep", "progress", "conflict")}
                 for family, rows in buckets.items()}
        return cls(belief=belief, work_statistics=stats)


def fusion_decision(message: Message, snapshot: Snapshot) -> str:
    """Conservative exact-anchor fusion, not a semantic oracle."""
    if not message.anchors:
        return "verify"
    valid = all(path in snapshot.files and snapshot.files[path].count(anchor) == 1
                for path, anchor in message.anchors.items())
    if not valid:
        return "verify"
    return "apply" if message.request_version == snapshot.version else "rebase"
