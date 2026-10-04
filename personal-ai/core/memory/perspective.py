"""Character knowledge boundaries and evidence schema."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Perspective(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    knowledge: Literal["direct", "witnessed", "heard", "inferred", "unknown"] = "unknown"
    content: str = Field(default="", max_length=1000)
    evidence_quote: str = Field(default="", max_length=500)
    importance: int = Field(default=3, ge=1, le=5)
    importance_reason: str = Field(default="", max_length=200)
    emotion: str = Field(default="", max_length=120)
    memory_strength: float = Field(default=0.5, ge=0, le=1)
    relationship_change: str = Field(default="", max_length=240)
    confidence: float = Field(default=0, ge=0, le=1)

