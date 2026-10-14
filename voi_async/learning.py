"""Small executable predictors. No provider probabilities or task IDs as labels."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .types import Message, Observation, Snapshot

DIM = 48


def features(snapshot: Snapshot, message: Message | None, delay: float,
             remaining: float) -> list[float]:
    """Request-visible state only; task_id intentionally excluded."""
    text = snapshot.description + "\n" + "\n".join(snapshot.files.values())
    text += "\n" + "\n".join(o.text for o in snapshot.observations[-4:])
    if message:
        text += "\n" + message.wire().decode()
    # Exclude random version hashes from lexical features.
    text = re.sub(r"\b[0-9a-f]{64}\b", "<version>", text)
    x = [1.0, min(snapshot.step / 10, 3), min(delay, 60) / 10,
         min(max(remaining, 0), 120) / 30, len(snapshot.files) / 10,
         float(message is not None)]
    x += [float(message is not None and k in message.fields)
          for k in ("location", "cause", "change", "verification")]
    x += [min(len(message.wire()), 8000) / 1000 if message else 0,
          sum(not o.ok for o in snapshot.observations[-4:]) / 4]
    lexical = [0.0] * (DIM - len(x))
    for token in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text.lower()):
        h = hashlib.sha256(token.encode()).digest()
        j = int.from_bytes(h[:4], "big") % len(lexical)
        lexical[j] += 1 if h[4] % 2 else -1
    norm = max(1, math.sqrt(sum(v * v for v in lexical)))
    return x + [v / norm for v in lexical]


def solve(matrix: list[list[float]], target: list[float]) -> list[float]:
    a = [row[:] + [b] for row, b in zip(matrix, target)]
    for j in range(len(a)):
        k = max(range(j, len(a)), key=lambda i: abs(a[i][j]))
        a[j], a[k] = a[k], a[j]
        pivot = a[j][j]
        if abs(pivot) < 1e-12:
            raise ValueError("singular calibration design")
        a[j] = [v / pivot for v in a[j]]
        for i in range(len(a)):
            if i != j:
                scale = a[i][j]
                a[i] = [u - scale * v for u, v in zip(a[i], a[j])]
    return [row[-1] for row in a]


@dataclass
class RidgePredictor:
    weights: list[float]
    lower: float = 0.0
    upper: float = 1.0

    @classmethod
    def fit(cls, xs: list[list[float]], ys: list[float], penalty: float = 1.0,
            lower: float = 0.0, upper: float = 1.0) -> "RidgePredictor":
        if not xs or len(xs) != len(ys) or penalty <= 0:
            raise ValueError("nonempty paired data and positive ridge penalty required")
        n = len(xs[0])
        if any(len(x) != n for x in xs):
            raise ValueError("feature dimension mismatch")
        if any(not math.isfinite(v) for x in xs for v in x) or any(
                not math.isfinite(y) for y in ys):
            raise ValueError("nonfinite training data")
        a = [[sum(x[i] * x[j] for x in xs) + (penalty if i == j else 0)
              for j in range(n)] for i in range(n)]
        b = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(n)]
        return cls(solve(a, b), lower, upper)

    def predict(self, x: list[float]) -> float:
        if len(x) != len(self.weights):
            raise ValueError("model/feature schema mismatch")
        return max(self.lower, min(self.upper, sum(a * b for a, b in zip(x, self.weights))))


@dataclass
class ValueBundle:
    arrival: RidgePredictor
    gate: RidgePredictor
    beta: float
    threshold: float
    training_tasks: list[str]
    provenance: str
    schema: str = "voi-async-values-v1"

    def value(self, snapshot: Snapshot, message: Message, delay: float,
              remaining: float) -> float:
        return self.arrival.predict(features(snapshot, message, delay, remaining))

    def gain(self, snapshot: Snapshot, delay: float, remaining: float) -> float:
        return self.gate.predict(features(snapshot, None, delay, remaining))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ValueBundle":
        data = json.loads(Path(path).read_text())
        if data.get("schema") != "voi-async-values-v1":
            raise ValueError("unsupported predictor artifact")
        data["arrival"] = RidgePredictor(**data["arrival"])
        data["gate"] = RidgePredictor(**data["gate"])
        return cls(**data)


def snapshot_from_dict(obj: dict) -> Snapshot:
    return Snapshot(obj["task_id"], obj["description"], dict(obj["files"]),
                    tuple(Observation(**o) for o in obj.get("observations", [])),
                    obj.get("step", 0))


def fit_values(rows: list[dict], beta: float = 0.0001,
               penalty: float = 1.0, threshold: float = 0.01) -> ValueBundle:
    """Task-cross-fitted gate targets for the SAME stochastic encoder.

    A row is one snapshot/delay/continuation-seed trial, with control outcome
    and all complete-message fork outcomes. Gate target = E_e[Y_m] - Y_0.
    Held-out task outcomes score the distribution but NEVER select its message.
    Only the final arrival predictor uses all calibration tasks.
    """
    from .information import ArrivalEncoder
    tasks = sorted({row["snapshot"]["task_id"] for row in rows})
    if len(tasks) < 2:
        raise ValueError("at least two independent tasks for cross-fitting")

    def training_xy(selected):
        xs, ys = [], []
        for row in selected:
            sn = snapshot_from_dict(row["snapshot"])
            for branch in row["messages"]:
                m = Message(**branch["message"])
                xs.append(features(sn, m, row["delay"], row["remaining"]))
                ys.append(float(branch["success"]))
        return xs, ys

    gate_x, gate_y = [], []
    for held_task in tasks:
        train = [r for r in rows if r["snapshot"]["task_id"] != held_task]
        xs, ys = training_xy(train)
        pred = RidgePredictor.fit(xs, ys, penalty)
        encoder = ArrivalEncoder(
            lambda s, m, d, r: pred.predict(features(s, m, d, r)), beta)
        for row in rows:
            if row["snapshot"]["task_id"] != held_task:
                continue
            sn = snapshot_from_dict(row["snapshot"])
            ms = [Message(**b["message"]) for b in row["messages"]]
            result = encoder.distribution(sn, ms, row["delay"], row["remaining"])
            target = sum(result.probabilities[m.id] * float(b["success"])
                         for m, b in zip(ms, row["messages"])) - float(row["control"])
            gate_x.append(features(sn, None, row["delay"],
                                   row.get("request_remaining", row["remaining"] + row["delay"])))
            gate_y.append(target)
    xs, ys = training_xy(rows)
    return ValueBundle(RidgePredictor.fit(xs, ys, penalty),
                       RidgePredictor.fit(gate_x, gate_y, penalty, -1, 1),
                       beta, threshold, tasks,
                       "execution forks; leave-one-task-out stochastic encoder targets; "
                       "single-request continuation; no claim of Q*")
