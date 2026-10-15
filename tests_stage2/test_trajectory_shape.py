import json
from pathlib import Path
import tempfile
import unittest

from voi_async.trajectory_shape import compare_runs, distance, project


class ShapeTests(unittest.TestCase):
    def tool(self, new="x", path="calc.py"):
        return dict(event="tool_start", action=dict(
            kind="patch", edits=[dict(path=path, old="old", new=new)]))

    def test_output_text_hashes_observations_and_timestamps_do_not_change_shape(self):
        l = [dict(event="executor_start", message_hash="abc", time=1), self.tool("a"),
             dict(event="tool_end", observation={"ok": True, "text": "a"})]
        r = [dict(event="executor_start", message_hash="def", time=9), self.tool("b"),
             dict(event="tool_end", observation={"ok": False, "text": "b"})]
        self.assertEqual(distance(project(l), project(r))["D_shape"], 0)

    def test_structural_parameters_and_order_change_shape(self):
        self.assertEqual(distance(project([self.tool()]),
                                  project([self.tool(path="other.py")]))["D_shape"], 1)
        l = project([dict(event="request"), dict(event="executor_start", message_hash=None)])
        r = list(reversed(l))
        d = distance(l, r)
        self.assertEqual(d["D_shape"], 2)
        self.assertEqual(d["D_iter_observed"], 0)
        self.assertFalse(d["auxiliary_D_struct_observed"])

    def test_guidance_presence_and_fusion_branch_are_structural(self):
        l = project([dict(event="executor_start", message_hash=None),
                     dict(event="fusion", decision="apply")])
        r = project([dict(event="executor_start", message_hash="id"),
                     dict(event="fusion", decision="discard")])
        self.assertEqual(distance(l, r)["D_shape"], 2)

    def test_tail_not_penalized_and_node_counts_are_separate(self):
        l = project([self.tool()])
        d = distance(l, l + l)
        self.assertEqual(d["D_shape"], 0)
        self.assertEqual(d["D_iter_observed"], 1)
        self.assertEqual(d["unmatched_tail_rounds"], 1)
        self.assertFalse(d["auxiliary_D_struct_observed"])

    def test_empty_prefix_is_explicit_and_has_no_normalized_ratio(self):
        d = distance([], project([self.tool()]))
        self.assertEqual(d["D_shape"], 0)
        self.assertTrue(d["empty_common_prefix"])
        self.assertIsNone(d["mismatch_fraction"])
        self.assertTrue(d["auxiliary_D_struct_observed"])

    def test_dispatch_order_does_not_enter_local_projection(self):
        events = [dict(event="dispatch", task_id="other", reason="anything"), self.tool()]
        self.assertEqual(distance(project(events), project([self.tool()]))["D_shape"], 0)
        self.assertEqual(len(project([dict(event="request"), self.tool()], "observed_tools_v1")), 1)

    def test_wait_requested_parameter_counts_but_unrelated_defaults_do_not(self):
        l = [dict(event="tool_start", action=dict(kind="wait", seconds=0.01))]
        r = [dict(event="tool_start", action=dict(kind="wait", seconds=0.02))]
        self.assertEqual(distance(project(l), project(r))["D_shape"], 1)
        l = [dict(event="tool_start", action=dict(kind="test", seconds=0.01, path="ignored"))]
        r = [dict(event="tool_start", action=dict(kind="test", seconds=0.99))]
        self.assertEqual(distance(project(l), project(r))["D_shape"], 0)

    def test_paired_rate_includes_empty_prefix_and_rejects_missing_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "left.json", Path(directory) / "right.json"
            def row(task, events):
                return dict(task_id=task, events=events)
            l = [row("A", [self.tool()]), row("B", [dict(event="task_finished", reason="guide_error")])]
            r = [row("B", [self.tool()]), row("A", [self.tool(path="other.py")])]
            left.write_text(json.dumps(dict(results=l)))
            right.write_text(json.dumps(dict(results=r)))
            d = compare_runs(left, right, "observed_tools_v1")
            self.assertEqual(d["changed_pair_rate"], 0.5)
            self.assertEqual(d["empty_prefix_pairs"], ["B"])
            right.write_text(json.dumps(dict(results=r[:1])))
            with self.assertRaises(ValueError):
                compare_runs(left, right)

    def test_rejects_unknown_profile_and_unknown_tools(self):
        with self.assertRaises(ValueError):
            project([], "unregistered")
        with self.assertRaises(ValueError):
            project([dict(event="tool_start", action=dict(kind="unknown"))])
