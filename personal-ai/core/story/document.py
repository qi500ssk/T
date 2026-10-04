"""Story document contracts and deterministic character-scoped import."""
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Person(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    personality: str = Field(default="", max_length=2000)
    motivation: str = Field(default="", max_length=2000)
    speech: str = Field(default="", max_length=2000)
    relationships: str = Field(default="", max_length=3000)
    boundaries: str = Field(default="", max_length=2000)
    example_dialogue: str = Field(default="", max_length=3000)


class Viewpoint(Strict):
    character_id: str
    knowledge: Literal["direct", "witnessed", "heard", "unknown"]
    memory: str = Field(default="", max_length=1000)
    quote: str = Field(default="", max_length=500)
    known_people: list[str] = Field(default_factory=list, max_length=30)
    importance: int = Field(default=3, ge=1, le=5)
    significance: list[Literal["identity", "relationship", "goal", "belief", "emotion", "milestone", "decision"]] = Field(default_factory=list, max_length=7)
    importance_reason: str = Field(default="", max_length=200)
    emotion: str = Field(default="", max_length=120)
    relationship_change: str = Field(default="", max_length=240)
    confidence: float = Field(default=0.5, ge=0, le=1)


class Event(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    stage: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)
    time: str = Field(default="", max_length=200)
    time_type: Literal["exact", "fuzzy", "relative", "sequence", "unknown"] = "unknown"
    timeline_order: int | None = Field(default=None, ge=0)
    parent_event_id: str | None = None
    participants: list[str] = Field(default_factory=list, max_length=30)
    viewpoints: list[Viewpoint] = Field(default_factory=list, max_length=30)


class Lore(Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,55}$")
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["place", "organization", "rule", "history", "culture", "item"]
    content: str = Field(min_length=1, max_length=3000)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    known_by: list[str] = Field(default_factory=list, max_length=30)


class Story(Strict):
    format: Literal["personal-ai-story-v1"]
    title: str = Field(min_length=1, max_length=100)
    basis: Literal["original", "source_based", "adaptation"]
    source_note: str = Field(min_length=1, max_length=2000)
    characters: list[Person] = Field(min_length=1, max_length=30)
    events: list[Event] = Field(min_length=1, max_length=500)
    world_entries: list[Lore] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def references(self):
        people = {p.id for p in self.characters}
        if len({l.id for l in self.world_entries}) != len(self.world_entries) or any(not set(l.known_by) <= people for l in self.world_entries):
            raise ValueError("世界条目身份必须唯一，知情人物必须存在")
        if {"lore_"+l.id for l in self.world_entries} & {e.id for e in self.events}:
            raise ValueError("事件不能占用世界条目的保留身份")
        if len(people) != len(self.characters) or len({e.id for e in self.events}) != len(self.events):
            raise ValueError("人物与事件 ID 必须唯一")
        for event in self.events:
            if event.parent_event_id and (event.parent_event_id == event.id or event.parent_event_id not in {e.id for e in self.events}):
                raise ValueError("父事件必须引用另一个已有事件")
            if not set(event.participants) <= people:
                raise ValueError(f"事件 {event.id} 引用了不存在的人物：{sorted(set(event.participants) - people)}；可用人物 ID：{sorted(people)}")
            if len({v.character_id for v in event.viewpoints}) != len(event.viewpoints):
                raise ValueError("同一事件不能重复声明同一人物视角")
            for view in event.viewpoints:
                if view.character_id not in people or not set(view.known_people) <= people:
                    raise ValueError(f"事件 {event.id} 的视角 {view.character_id} 引用了不存在的人物；可用人物 ID：{sorted(people)}")
                if view.knowledge != "unknown" and (not view.memory or not view.quote or view.quote not in event.text):
                    raise ValueError(f"事件 {event.id} 的视角 {view.character_id}：知情记忆必须有正文中的连续原文依据；quote 须逐字摘录该事件 text，memory 不可为空")
                if view.knowledge == "direct" and view.character_id not in event.participants:
                    raise ValueError("亲历角色必须在事件参与者中")
        parents = {e.id: e.parent_event_id for e in self.events}
        for identity in parents:
            seen = set()
            while identity:
                if identity in seen: raise ValueError("事件归组不能形成循环")
                seen.add(identity); identity = parents.get(identity)
        return self


def parse_story(text):
    match = re.search(r"```(?:json|story)\s*\n(.*?)\n```", text, re.S)
    return Story.model_validate_json(match.group(1) if match else text.strip())


def markdown(story):
    parts = [f"# {story.title}", f"资料类型：{story.basis}\n\n来源说明：{story.source_note}", "## 人物档案"]
    parts += [f"### {p.name} [{p.id}]\n\n" + "\n\n".join(f"{label}：{getattr(p, field)}" for field, label in [("description","人物档案"),("personality","性格"),("motivation","目标与动机"),("speech","说话方式"),("relationships","关系认知"),("boundaries","知识与行为边界"),("example_dialogue","对话示例")] if getattr(p, field)) for p in story.characters]
    if story.world_entries:
        parts.append("## 世界设定条目")
        parts += [f"### {l.title} [{l.kind}]\n\n{l.content}" for l in story.world_entries]
    for event in story.events:
        parts.append(f"## {event.stage}\n\n### {event.title} [{event.id}]\n\n{event.text}")
    parts.append("## 结构化故事记录\n\n```json\n" + story.model_dump_json(indent=2) + "\n```")
    return "\n\n".join(parts)


def index_events(story):
    """World entries are indexed separately and only projected to declared knowers."""
    return [*story.events, *[Event(id="lore_"+l.id, stage="世界设定 · "+l.kind, title=l.title, text=l.content,
        viewpoints=[Viewpoint(character_id=p, knowledge="heard", memory=l.content[:1000], quote=l.content[:500], importance=4,
            significance=["identity"], importance_reason="书籍明确声明该人物掌握的背景知识", confidence=1) for p in l.known_by]) for l in story.world_entries]]


def stable_id(*parts):
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:32]
