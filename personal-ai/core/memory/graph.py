"""有来源的图结构；从世界事实或角色记忆投影，不产生额外事实。"""
from datetime import date
import hashlib
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=80)
    predicate: str = Field(min_length=1, max_length=80)
    object: str = Field(min_length=1, max_length=80)
    quote: str = Field(default="", max_length=500)


class MemoryGraphData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(default="", max_length=240)
    event: str = Field(default="", max_length=100)
    stage: str = Field(default="", max_length=100)
    people: list[str] = Field(default_factory=list, max_length=12)
    relationships: list[Relationship] = Field(default_factory=list, max_length=12)
    event_links: list["EventLink"] = Field(default_factory=list, max_length=8)
    start: date | None = None
    end: date | None = None
    time_quote: str = Field(default="", max_length=500)
    # 原文的相对时间保留在 time_label，未确定的先后关系不强行建立边。
    importance: int = Field(default=3, ge=1, le=5)
    importance_reason: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_values(self):
        if any(not name.strip() or len(name) > 80 for name in self.people):
            raise ValueError("人物名称须为 1–80 字")
        self.people = list(dict.fromkeys(name.strip() for name in self.people))
        if self.end and (not self.start or self.end < self.start):
            raise ValueError("结束时间不能早于开始时间，且需要开始时间")
        return self


class EventLink(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    event: str = Field(min_length=1, max_length=100)
    relation: Literal["before", "after", "causes"]
    quote: str = Field(min_length=1, max_length=500)


MemoryGraphData.model_rebuild()

# Unresolved mentions are not identities. Keep their source facts for review.
UNRESOLVED_PEOPLE = {"她", "他", "它", "他们", "她们", "它们", "我", "你", "我们", "你们", "对方", "自己", "某人", "其", "本人", "他人"}


def graph_data(row):
    return MemoryGraphData.model_validate(row.graph or {}).model_dump(mode="json")


def build_memory_graph(rows, character_name):
    nodes = {"character": {"id": "character", "label": character_name, "type": "character", "memory_ids": []}} if character_name else {}
    edges = []
    events = {}
    by_id = {row.id: row for row in rows}
    def event_id(row):
        target = getattr(row, "event_group", None)
        return target if target in by_id and graph_data(by_id[target])["event"] else row.id
    for row in rows:
        title = graph_data(row)["event"]
        if title:
            bucket = events.setdefault(title, [])
            if event_id(row) not in bucket:
                bucket.append(event_id(row))

    def person(name, memory_id):
        name = name.strip()
        if name in UNRESOLVED_PEOPLE:
            return None
        key = "person:" + hashlib.sha256(name.encode()).hexdigest()[:16]
        node = nodes.setdefault(key, {"id": key, "label": name, "type": "person", "memory_ids": []})
        if memory_id not in node["memory_ids"]:
            node["memory_ids"].append(memory_id)
        return key

    def edge(source, target, label, row, quote=""):
        if source is None or target is None:
            return
        edges.append({"source": source, "target": target, "label": label, "memory_id": row.id,
                      "evidence_type": row.evidence_type, "quote": quote or row.source_quote})

    for row in rows:
        data = graph_data(row)
        key = "memory:" + row.id
        nodes[key] = {"id": key, "label": data["summary"] or row.content[:45], "type": "memory",
                      "memory_ids": [row.id], "importance": data["importance"], "is_core": row.is_core}
        if character_name:
            edge("character", key, "背景记忆", row)
        anchor = key
        if data["event"]:
            root = event_id(row)
            anchor = "event:" + root
            node = nodes.setdefault(anchor, {"id": anchor, "label": graph_data(by_id[root])["event"], "type": "event", "memory_ids": [],
                             "importance": data["importance"]})
            node["memory_ids"].append(row.id)
            edge(anchor, key, "记忆记录", row)
        for name in data["people"]:
            edge(person(name, row.id), anchor, "资料涉及", row)
        for relation in data["relationships"]:
            edge(person(relation["subject"], row.id), person(relation["object"], row.id), relation["predicate"], row, relation["quote"])
        for link in data["event_links"]:
            targets = events.get(link["event"], [])
            if data["event"] and len(targets) == 1 and targets[0] != event_id(row):
                edge(anchor, "event:" + targets[0], {"before": "早于", "after": "晚于", "causes": "导致"}[link["relation"]], row, link["quote"])
    return {"nodes": list(nodes.values()), "edges": edges}
