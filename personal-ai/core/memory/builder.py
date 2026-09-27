"""L2 → L3：从已审核世界事实构建角色视角草稿，只保存引用与主观记忆。"""
import asyncio
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from core.memory.world import digest
from core.memory.identity import rules_for, aliases_for
from infrastructure.database import CharacterMemory, DocumentChunk, WorldFact, SessionLocal


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


async def build_character_drafts(agent_id, character_name, fact_ids, provider, input_budget):
    from core.chat.context import estimate_tokens
    prompt = (Path(__file__).resolve().parents[2] / "prompts/memory/perspective.md").read_text(encoding="utf-8")
    result = {"created": 0, "unknown": 0, "existing": 0, "failed": 0}
    try:
        async with asyncio.timeout(180):
            for fact_id in dict.fromkeys(fact_ids):
                with SessionLocal() as session:
                    fact = session.get(WorldFact, fact_id)
                    chunk = session.get(DocumentChunk, fact.chunk_id) if fact else None
                    if not fact or fact.status != "active" or not chunk or fact.source_hash != digest(chunk.content):
                        result["failed"] += 1
                        continue
                    if session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
                            CharacterMemory.world_fact_id == fact_id).first():
                        result["existing"] += 1
                        continue
                    # 仅处理选中的事实及其证据，不发送全文或所有角色的知识。
                    evidence, graph, fact_content = fact.source_quote, fact.graph, fact.content
                    identity_rules = rules_for(session, fact.document_id)
                    alias_map = aliases_for(identity_rules)
                    relevant_names = set(graph.get("people", [])) | {character_name}
                    relevant_roots = {alias_map.get(n, n) for n in relevant_names}
                    relevant_rules = [r for r in identity_rules if r["name"] in relevant_names or
                        r["target"] in relevant_names or alias_map.get(r["name"], r["name"]) in relevant_roots]
                    user_text = json.dumps({"character": character_name, "fact": fact.content,
                        "evidence": evidence, "time": fact.time_label, "confirmed_identities": relevant_rules}, ensure_ascii=False)
                if estimate_tokens(prompt + user_text) > input_budget:
                    result["failed"] += 1
                    continue
                try:
                    async with asyncio.timeout(60):
                        output = await provider.complete([{"role": "system", "content": prompt}, {"role": "user", "content": user_text}], temperature=0)
                    raw = output.strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    perspective = Perspective.model_validate_json(raw)
                    if perspective.knowledge == "unknown":
                        result["unknown"] += 1
                        continue
                    if not perspective.content or not perspective.evidence_quote or perspective.evidence_quote not in evidence:
                        result["failed"] += 1
                        continue
                    with SessionLocal() as session:
                        current = session.get(WorldFact, fact_id)
                        if not current or current.status != "active" or current.source_quote != evidence or current.graph != graph or current.content != fact_content or rules_for(session, current.document_id) != identity_rules:
                            result["failed"] += 1
                            continue
                        session.add(CharacterMemory(agent_id=agent_id, world_fact_id=fact_id,
                            content=perspective.content, status="draft", known_to_character=True,
                            evidence_type="inference" if perspective.knowledge == "inferred" else "fact",
                            fingerprint=digest(agent_id + fact_id), source_name="世界事实引用",
                            perspective=perspective.model_dump(), graph={}))
                        session.commit()
                        result["created"] += 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    result["failed"] += 1
    except TimeoutError:
        result["failed"] += max(0, len(set(fact_ids)) - sum(result.values()))
    finally:
        await provider.close()
    return result
