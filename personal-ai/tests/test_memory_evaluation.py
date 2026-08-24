from evaluation.memory import evaluate


def test_fixed_memory_evaluation_meets_baseline():
    metrics = evaluate()
    assert metrics["false_memory_rate"] == 0
    assert metrics["duplicate_rate"] == 0
    assert metrics["recall_at_3"] == 1
    assert metrics["scope_misrecall_rate"] == 0
    assert metrics["conflict_resolution_rate"] == 1
    assert metrics["context_actual_use_rate"] == 1
