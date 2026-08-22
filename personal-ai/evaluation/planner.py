"""P6 Planner 确定性 schema / 权限回归评测。"""

import json
from pathlib import Path

from core.automation.planner import PlanValidationError, parse_plan


CASES = Path(__file__).resolve().parents[1] / "tests" / "eval" / "planner_cases.json"


def evaluate() -> dict:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    correct = 0
    valid_count = 0
    unsafe_hints = 0
    compliant_steps = 0
    allowed_hints = 0
    total_hints = 0
    details = []
    for case in cases:
        try:
            draft = parse_plan(
                json.dumps(case["output"], ensure_ascii=False),
                set(case["allowed_tools"]),
                int(case["max_steps"]),
            )
            valid = True
            valid_count += 1
            compliant_steps += int(2 <= len(draft.steps) <= int(case["max_steps"]))
            for step in draft.steps:
                total_hints += len(step.tool_hints)
                allowed_hints += len(set(step.tool_hints) & set(case["allowed_tools"]))
                unsafe_hints += len(set(step.tool_hints) - set(case["allowed_tools"]))
        except PlanValidationError:
            valid = False
        passed = valid is bool(case["expected_valid"])
        correct += int(passed)
        details.append({"name": case["name"], "passed": passed, "valid": valid})
    return {
        "cases": len(cases),
        "classification_accuracy": correct / len(cases),
        "schema_valid_rate": valid_count / len(cases),
        "step_count_compliance_rate": compliant_steps / valid_count if valid_count else 0.0,
        "allowed_tool_hint_rate": allowed_hints / total_hints if total_hints else 1.0,
        "unsafe_tool_hint_count": unsafe_hints,
        "details": details,
    }


if __name__ == "__main__":
    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["classification_accuracy"] != 1.0 or result["unsafe_tool_hint_count"] != 0:
        raise SystemExit(1)
