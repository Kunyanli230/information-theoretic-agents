import math
import random
import unittest

from voi_async.information import (
    ArrivalEncoder, CompleteMessageCode, blahut_arimoto, channel_metrics)
from voi_async.learning import RidgePredictor, fit_values
from voi_async.planning import Belief
from voi_async.types import Message, Observation, Snapshot


class InformationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = Snapshot("not-a-feature", "task", {"a.py": "a"})
        self.a = Message(self.snapshot.version, {"change": "a"}, {"a.py": "a"})
        self.b = Message(self.snapshot.version, {"change": "b"}, {"a.py": "a"})

    def test_complete_payload_roundtrip_and_trailing_rejection(self):
        codec = CompleteMessageCode()
        m = Message("版本", {"cause": "含中文\nand unicode λ"}, {"code.py": "x"})
        data = codec.encode(m)
        self.assertEqual(codec.decode(data), m)
        self.assertLessEqual(codec.bits(m.wire()), len(data) * 8)
        self.assertLess(len(data) * 8 - codec.bits(m.wire()), 8)
        with self.assertRaises(ValueError):
            codec.decode(data + b"\0")

    def test_reference_counts_content_not_template_index(self):
        codec = CompleteMessageCode()
        long = Message(self.snapshot.version, {"change": "a" * 100}, {"a.py": "a"})
        self.assertLess(codec.log_probability(long), codec.log_probability(self.a))

    def test_conditional_encoder_changes_decision_with_state(self):
        def value(s, m, delay, remaining):
            return float(m.fields["change"] == s.files["a.py"])
        enc = ArrivalEncoder(value, beta=0.01)
        for choice in ("a", "b"):
            s = Snapshot("x", "task", {"a.py": choice})
            result = enc.encode(s, [self.a, self.b], 0, 1, random.Random(0), True)
            self.assertEqual(result.message.fields["change"], choice)
            self.assertAlmostEqual(sum(result.probabilities.values()), 1)

    def test_gibbs_matches_analytic_binary_solution(self):
        enc = ArrivalEncoder(lambda s, m, d, r: float(m == self.a), beta=0.5)
        result = enc.distribution(self.snapshot, [self.a, self.b], 0, 1)
        self.assertAlmostEqual(result.probabilities[self.a.id], 1 / (1 + math.exp(-2)))
        # Since reference assigns mass outside this candidate set, KL remains
        # unnormalized globally. Do not call a two-template entropy the rate.
        self.assertGreater(result.expected_kl_to_reference, math.log(2))

    def test_stability_at_low_temperature(self):
        enc = ArrivalEncoder(lambda s, m, d, r: float(m == self.a), beta=1e-12)
        r = enc.distribution(self.snapshot, [self.a, self.b], 0, 1)
        self.assertEqual(r.probabilities[self.a.id], 1)
        self.assertTrue(math.isfinite(r.objective))

    def test_sampling_not_silently_argmax(self):
        enc = ArrivalEncoder(lambda *args: 0.5, beta=1)
        rng = random.Random(1)
        observed = {enc.encode(self.snapshot, [self.a, self.b], 0, 1, rng).message.id
                    for _ in range(50)}
        self.assertEqual(observed, {self.a.id, self.b.id})

    def test_information_decomposition(self):
        r = channel_metrics([0.5, 0.5], [[0.9, 0.1], [0.2, 0.8]],
                            [math.log(0.3), math.log(0.7)])
        self.assertAlmostEqual(r["rate_upper_bound"],
                               r["mutual_information"] + r["marginal_kl"])
        self.assertGreaterEqual(r["marginal_kl"], 0)

    def test_ba_binary_rate_distortion(self):
        r = blahut_arimoto([0.5, 0.5], [[0, 1], [1, 0]], beta=0.5)
        self.assertAlmostEqual(r["channel"][0][1], 1 / (1 + math.exp(2)))
        self.assertTrue(all(b <= a + 1e-10 for a, b in zip(r["history"], r["history"][1:])))

    def test_ba_support_mask_and_bad_data(self):
        r = blahut_arimoto([0.5, 0.5], [[0, math.inf], [1, 0]], 0.2)
        self.assertEqual(r["channel"][0][1], 0)
        with self.assertRaises(ValueError):
            blahut_arimoto([1], [[math.inf]], 0.2)

    def test_bayesian_information_gain_and_update(self):
        b = Belief({"A": 0.5, "B": 0.5},
                   {"test:": {"A": {"test:ok": 1, "test:fail": 0},
                              "B": {"test:ok": 0, "test:fail": 1}}})
        self.assertAlmostEqual(b.expected_information("test:"), math.log(2))
        b.update("test:", Observation("test", "", "passed", True))
        self.assertEqual(b.prior["A"], 1)
        self.assertEqual(b.expected_information("unknown:"), 0)

    def test_ridge_fits_and_validates(self):
        p = RidgePredictor.fit([[1, 0], [1, 1], [1, 2]], [0, 0.5, 1], penalty=0.0001)
        self.assertAlmostEqual(p.predict([1, 1]), 0.5, places=3)
        with self.assertRaises(ValueError):
            p.predict([1])
        with self.assertRaises(ValueError):
            fit_values([], beta=0.1)
