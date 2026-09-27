"""Validate assistant proposals server-side before presenting a writing action."""
import re
from pydantic import BaseModel, ConfigDict, Field


class StoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(min_length=20, max_length=16000)
    chapter_count: int = Field(default=12, ge=2, le=30)
    min_chapter_chars: int = Field(default=800, ge=400, le=2500)
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    research_query: str = Field(default="", max_length=200)


def parse_proposal(content):
    match = re.search(r"```story-build\s*\n(.*?)\n```", content, re.S)
    if not match:
        return None
    try:
        return StoryProposal.model_validate_json(match[1])
    except ValueError:
        return None
