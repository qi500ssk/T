"""Source-backed metadata used by memory retrieval; no graph rendering."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=80)
    predicate: str = Field(min_length=1, max_length=80)
    object: str = Field(min_length=1, max_length=80)
    quote: str = Field(default="", max_length=500)


class MemoryMetadata(BaseModel):
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


MemoryMetadata.model_rebuild()


def memory_metadata(row):
    # Retain the persisted column name for existing character memories.
    return MemoryMetadata.model_validate(row.graph or {}).model_dump(mode="json")
