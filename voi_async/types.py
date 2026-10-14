from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Observation:
    kind: str
    path: str
    text: str
    ok: bool


@dataclass(frozen=True)
class Snapshot:
    task_id: str
    description: str
    files: dict[str, str]
    observations: tuple[Observation, ...] = ()
    step: int = 0

    @property
    def version(self) -> str:
        return digest(self.files)

    @property
    def state_id(self) -> str:
        return digest(asdict(self))

    def public(self) -> dict:
        # A fresh tree, so background adapters cannot mutate live state.
        return json.loads(canonical(asdict(self)))


@dataclass(frozen=True)
class Diagnosis:
    location: str
    cause: str
    change: str
    verification: str
    anchors: dict[str, str]

    @classmethod
    def from_dict(cls, obj: dict) -> "Diagnosis":
        for key in ("location", "cause", "change", "verification"):
            if not isinstance(obj.get(key), str) or not obj[key].strip():
                raise ValueError(f"diagnosis needs nonempty {key}")
        anchors = obj.get("anchors")
        if (not isinstance(anchors, dict) or not anchors
                or any(not isinstance(k, str) or not isinstance(v, str) or not v
                       for k, v in anchors.items())):
            raise ValueError("anchors must map file paths to nonempty exact text")
        return cls(**{k: obj[k] for k in
                      ("location", "cause", "change", "verification")}, anchors=anchors)


@dataclass(frozen=True)
class Message:
    request_version: str
    fields: dict[str, str]
    anchors: dict[str, str]

    def wire(self) -> bytes:
        return canonical(asdict(self))

    @property
    def id(self) -> str:
        return hashlib.sha256(self.wire()).hexdigest()

    @classmethod
    def from_wire(cls, data: bytes) -> "Message":
        obj = json.loads(data)
        return cls(**obj)


def candidates(z: Diagnosis, snapshot: Snapshot) -> list[Message]:
    """Complete payloads, not template IDs. Both content and scope can vary."""
    sets = (
        ("location", "cause"),
        ("location", "change"),
        ("location", "cause", "change"),
        ("location", "cause", "change", "verification"),
        ("cause", "verification"),
    )
    out = [Message(snapshot.version, {k: getattr(z, k) for k in keys},
                   dict(z.anchors)) for keys in sets]
    return list({m.id: m for m in out}.values())


@dataclass(frozen=True)
class Action:
    kind: str
    path: str = ""
    old: str = ""
    new: str = ""
    seconds: float = 0.01
    edits: tuple[dict[str, str], ...] = ()

    @classmethod
    def from_dict(cls, obj: dict) -> "Action":
        obj = dict(obj)
        if "edits" in obj:
            obj["edits"] = tuple(obj["edits"])
        action = cls(**obj)
        if action.kind not in {"read", "test", "edit", "patch", "wait", "submit"}:
            raise ValueError(f"unsupported action: {action.kind}")
        if action.kind == "edit" and not action.old:
            raise ValueError("edits must have a nonempty exact old substring")
        if action.kind == "patch":
            if not action.edits or any(
                    set(e) != {"path", "old", "new"}
                    or not all(isinstance(v, str) for v in e.values())
                    or not e["old"] for e in action.edits):
                raise ValueError("patch needs nonempty exact {path,old,new} edits")
        if not 0 <= action.seconds <= 1:
            raise ValueError("wait seconds must be in [0, 1]")
        return action

    @property
    def id(self) -> str:
        return digest(asdict(self))


@dataclass
class TaskSpec:
    task_id: str
    description: str
    files: dict[str, str]
    visible_test: list[str]
    hidden_test: list[str] | None = None
    hidden_files: dict[str, str] = field(default_factory=dict)
    test_timeout: float = 5.0
    tool_delay: float = 0.0


@dataclass
class RunResult:
    task_id: str
    mode: str
    elapsed: float
    reason: str
    files: dict[str, str]
    visible_pass: bool
    success: bool | None
    events: list[dict] = field(default_factory=list)
