"""Explicitly synthetic integration tasks; never a research benchmark."""
import json
import sys
from .models import FixtureGuide
from .types import Diagnosis, TaskSpec


def fixture_tasks(tool_delay: float = 0.025):
    tasks, diagnoses = [], {}
    definitions = [
        ("inclusive", "def total(n):\n    return sum(range(n))\n",
         "range(n)", "range(n + 1)",
         "from calc import total\nassert total(3) == 6\n",
         "from calc import total\nassert total(0) == 0\nassert total(5) == 15\n",
         "Return the sum of all integers from 0 through n, inclusive."),
        ("average", "def average(xs):\n    return sum(xs) // len(xs)\n",
         "// len(xs)", "/ len(xs)",
         "from calc import average\nassert average([1, 2]) == 1.5\n",
         "from calc import average\nassert average([2, 3]) == 2.5\n",
         "Return the arithmetic mean as a real number."),
    ]
    for tid, source, old, new, visible, hidden, description in definitions:
        tasks.append(TaskSpec(
            tid, description,
            {"calc.py": source, "requirements.txt": description, "tests.py": visible},
            [sys.executable, "tests.py"], [sys.executable, "heldout.py"],
            hidden_files={"heldout.py": hidden}, tool_delay=tool_delay))
        diagnoses[tid] = Diagnosis(
            location="calc.py", cause=description,
            change=json.dumps({"path": "calc.py", "old": old, "new": new}, sort_keys=True),
            verification="Run the visible tests and independently verify the contract.",
            anchors={"calc.py": old})
    return tasks, diagnoses


class FixtureGuideSet:
    def __init__(self, diagnoses, delay=0):
        self.diagnoses, self.delay = diagnoses, delay

    async def diagnose(self, snapshot, seed):
        return await FixtureGuide(self.diagnoses[snapshot.task_id], self.delay).diagnose(
            snapshot, seed)
