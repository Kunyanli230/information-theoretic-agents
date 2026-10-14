"""Complete-message reference coding, variational RD and finite-channel BA.

All logarithms are natural. No probability is attached merely to a template ID.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable

from .types import Message, Snapshot, digest


def logsumexp(xs: list[float]) -> float:
    m = max(xs)
    if m == -math.inf:
        return m
    return m + math.log(sum(math.exp(x - m) for x in xs))


class CompleteMessageCode:
    """A prefix code on ALL finite byte strings.

    gamma(len(payload)+1) followed by payload bytes. Its Kraft sum is one:
    sum_n 2^-gamma_length(n+1) * 256^n * 2^(-8n) = 1.
    Unseen messages have positive reference probability. Headers count too.
    The returned padding is transport padding; decode rejects trailing bytes.
    """

    @staticmethod
    def bits(data: bytes) -> int:
        return 2 * (len(data) + 1).bit_length() - 1 + 8 * len(data)

    def log_probability(self, message: Message) -> float:
        return -self.bits(message.wire()) * math.log(2)

    def encode(self, message: Message) -> bytes:
        data = message.wire()
        length = bin(len(data) + 1)[2:]
        bits = "0" * (len(length) - 1) + length
        bits += "".join(f"{b:08b}" for b in data)
        bits += "0" * (-len(bits) % 8)
        return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))

    def decode(self, data: bytes) -> Message:
        bits = "".join(f"{b:08b}" for b in data)
        k = bits.find("1")
        if k < 0 or len(bits) < 2 * k + 1:
            raise ValueError("invalid length prefix")
        n = int(bits[k:2 * k + 1], 2) - 1
        end = 2 * k + 1 + 8 * n
        if end > len(bits) or len(bits) - end >= 8 or "1" in bits[end:]:
            raise ValueError("truncated or noncanonical code")
        payload = bytes(int(bits[i:i + 8], 2)
                        for i in range(2 * k + 1, end, 8))
        return Message.from_wire(payload)


@dataclass(frozen=True)
class Encoding:
    message: Message
    probabilities: dict[str, float]
    distortions: dict[str, float]
    objective: float
    expected_kl_to_reference: float
    wire_bits: int
    reference_log_probabilities: dict[str, float]


class ArrivalEncoder:
    """Fixed-reference Gibbs optimizer; value() must match the rollout protocol.

    Arrival value is estimated from request-side information and delay. The
    encoder never receives the live environment or receiver's future history.
    """

    def __init__(self, value: Callable, beta: float = 0.0001):
        if beta <= 0 or not math.isfinite(beta):
            raise ValueError("beta must be positive and finite")
        self.value = value
        self.beta = beta
        self.code = CompleteMessageCode()

    def distribution(self, snapshot: Snapshot, messages: list[Message],
                     delay: float, remaining: float) -> Encoding:
        if not messages or len({m.id for m in messages}) != len(messages):
            raise ValueError("need nonempty, unique complete messages")
        values = [float(self.value(snapshot, m, delay, remaining)) for m in messages]
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError("arrival success estimates must be in [0,1]")
        # A COMMON reference. Never use a different, late-arrival oracle per m.
        best = max(values)
        ds = [best - v for v in values]
        logq = [self.code.log_probability(m) for m in messages]
        scores = [q - d / self.beta for q, d in zip(logq, ds)]
        logz = logsumexp(scores)
        ps = [math.exp(s - logz) for s in scores]
        kl = sum(p * (math.log(p) - q)
                 for p, q in zip(ps, logq) if p)
        return Encoding(
            messages[max(range(len(ps)), key=ps.__getitem__)],
            dict(zip((m.id for m in messages), ps)),
            dict(zip((m.id for m in messages), ds)),
            sum(p * d for p, d in zip(ps, ds)) + self.beta * kl,
            kl, 0, dict(zip((m.id for m in messages), logq)))

    def encode(self, snapshot: Snapshot, messages: list[Message],
               delay: float, remaining: float, rng: random.Random,
               deterministic: bool = False) -> Encoding:
        result = self.distribution(snapshot, messages, delay, remaining)
        chosen = result.message if deterministic else rng.choices(
            messages, [result.probabilities[m.id] for m in messages], k=1)[0]
        # Exercise the real complete-payload code, not just its bit estimate.
        chosen = self.code.decode(self.code.encode(chosen))
        return Encoding(chosen, result.probabilities, result.distortions,
                        result.objective, result.expected_kl_to_reference,
                        self.code.bits(chosen.wire()), result.reference_log_probabilities)


def channel_metrics(pz: list[float], channel: list[list[float]],
                    log_reference: list[float]) -> dict[str, float]:
    """I(Z;M), E KL(e||q) and marginal KL; q may include other messages."""
    if not pz or len(channel) != len(pz) or abs(sum(pz) - 1) > 1e-8:
        raise ValueError("invalid source")
    n = len(log_reference)
    if any(len(row) != n or any(p < 0 for p in row)
           or abs(sum(row) - 1) > 1e-8 for row in channel):
        raise ValueError("invalid channel")
    if any(p < 0 for p in pz):
        raise ValueError("negative source mass")
    marginal = [sum(p * row[j] for p, row in zip(pz, channel)) for j in range(n)]
    mi = sum(p * e * math.log(e / marginal[j])
             for p, row in zip(pz, channel) for j, e in enumerate(row) if p and e)
    marginal_kl = sum(p * (math.log(p) - q)
                      for p, q in zip(marginal, log_reference) if p)
    rate = sum(p * e * (math.log(e) - log_reference[j])
               for p, row in zip(pz, channel) for j, e in enumerate(row) if p and e)
    return dict(mutual_information=mi, rate_upper_bound=rate,
                marginal_kl=marginal_kl)


def blahut_arimoto(pz: list[float], distortion: list[list[float]], beta: float,
                  iterations: int = 2000, tolerance: float = 1e-10) -> dict:
    """Finite complete-message alphabet; +inf marks unavailable messages.

    This solves Ed + beta*I with an optimized marginal, unlike the deployed
    fixed-reference variant. Return the full conditional channel, not its mode.
    """
    if beta <= 0 or not pz or abs(sum(pz) - 1) > 1e-8 or any(p <= 0 for p in pz):
        raise ValueError("positive beta/source probabilities required")
    if len(distortion) != len(pz):
        raise ValueError("source/table shape mismatch")
    n = len(distortion[0])
    if not n or any(len(row) != n or not any(math.isfinite(d) for d in row)
                    or any(math.isnan(d) or d < 0 for d in row) for row in distortion):
        raise ValueError("invalid distortion/support")
    logq = [-math.log(n)] * n
    history = []
    for _ in range(iterations):
        loge = []
        for row in distortion:
            scores = [q - d / beta for q, d in zip(logq, row)]
            normalizer = logsumexp(scores)
            loge.append([s - normalizer for s in scores])
        logq_new = [logsumexp([math.log(p) + row[j] for p, row in zip(pz, loge)])
                    for j in range(n)]
        objective = 0.0
        for p, row, ds in zip(pz, loge, distortion):
            for j, le in enumerate(row):
                if math.isfinite(le):
                    e = math.exp(le)
                    objective += p * e * (ds[j] + beta * (le - logq_new[j]))
        history.append(objective)
        logq = logq_new
        if len(history) > 1 and abs(history[-1] - history[-2]) < tolerance:
            break
    return dict(channel=[[math.exp(le) for le in row] for row in loge],
                marginal=[math.exp(q) for q in logq], objective=history[-1],
                history=history)
