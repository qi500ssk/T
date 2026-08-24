"""固定意图路由评测：规则用例不得增加模型往返。"""

from __future__ import annotations

import json
from pathlib import Path

from core.chat.intent import rule_intent


CASE_FILE = Path(__file__).resolve().parents[1] / "tests" / "eval" / "intent_cases.json"


def main() -> None:
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    correct = 0
    rule_short_circuits = 0
    failures: list[str] = []
    for case in cases:
        result = rule_intent(case["message"])
        actual = result.intent if result else "unclassified"
        if actual == case["intent"]:
            correct += 1
        else:
            failures.append(f"- {case['message']}：期望 {case['intent']}，实际 {actual}")
        if result is not None and result.source == "rule":
            rule_short_circuits += 1
    total = len(cases)
    print(f"Cases: {total}")
    print(f"Intent accuracy: {correct / total:.3f}")
    print(f"Rule short-circuit rate: {rule_short_circuits / total:.3f}")
    print("Rule-case model round trips: 0")
    if failures:
        print("Failures:")
        print("\n".join(failures))


if __name__ == "__main__":
    main()
