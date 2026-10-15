"""Complete-code executor protocol for small models; no model-output repairs."""
from dataclasses import asdict

from .types import Action


class CompleteCodeAgent:
    def __init__(self, model, visible_tests=None):
        self.model = model
        self.visible_tests = visible_tests or {}

    async def propose(self, snapshot, message, seed):
        source = snapshot.files["calc.py"]
        visible = self.visible_tests.get(snapshot.task_id, snapshot.files.get("tests.py", ""))
        feedback = next((o.text for o in reversed(snapshot.observations) if o.kind == "test"), "")
        user = (f"Code:\n```python\n{source}```\nThis test fails:\n```python\n"
                f"{visible}\n```\nError:\n{feedback}\n")
        if message is not None:
            fields = [k for k in ("location", "cause", "change", "verification", "applicable_if")
                      if k in message.fields]
            guidance = "\n".join(f"{k}: {message.fields[k]}" for k in fields)
            user += f"\nA senior engineer sent this advice:\n{guidance}\n\n"
        user += "Fix the code."
        result = await self.model.complete({
            "role": "executor", "snapshot": snapshot.public(), "seed": seed,
            "response_format": "python_code",
            "messages": [{"role": "system", "content": "You fix bugs in Python code. Reply with the complete corrected code in one ```python block and nothing else."},
                         {"role": "user", "content": user}],
            "guidance": asdict(message) if message else None})
        if not isinstance(result.get("code"), str) or not result["code"].strip():
            raise ValueError("executor needs nonempty complete code")
        return [Action("patch", edits=({"path": "calc.py", "old": source, "new": result["code"]},))]
