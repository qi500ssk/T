from core.capabilities.skill_registry import SkillRegistry
from core.capabilities.skills import SkillRecord


def _record(skill_id: str, description: str) -> SkillRecord:
    return SkillRecord(
        id=skill_id,
        name=skill_id,
        description=description,
        required_tools=(),
        instructions="Do the task.",
        source="local",
        default_enabled=True,
        available=True,
    )


class FakeProvider:
    def __init__(self, name, priority, records):
        self.name = name
        self.priority = priority
        self.records = records
        self.fail = False

    def list(self):
        if self.fail:
            raise RuntimeError("temporary failure")
        return self.records


def test_provider_priority_and_disposer():
    registry = SkillRegistry()
    low = FakeProvider("low", 100, [_record("shared", "winner")])
    high = FakeProvider("high", 200, [_record("shared", "loser"), _record("extra", "extra")])
    dispose = registry.register(high)
    registry.register(low)
    snapshot = registry.snapshot()
    by_id = {item.id: item for item in snapshot.records}
    assert by_id["shared"].description == "winner"
    assert snapshot.complete is True
    assert len(snapshot.version) == 64
    dispose()
    assert [item.id for item in registry.snapshot().records] == ["shared"]


def test_provider_failure_keeps_last_good_catalog():
    registry = SkillRegistry()
    provider = FakeProvider("remote", 100, [_record("stable", "v1")])
    registry.register(provider)
    first = registry.snapshot()
    provider.fail = True
    fallback = registry.snapshot()
    assert fallback.complete is False
    assert fallback.records == first.records
    assert fallback.version == first.version
