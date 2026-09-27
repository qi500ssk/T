"""Bounded, resumable source review. Apply only after every source batch is checked."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from core.memory.identity import aliases_for, rules_for
from core.memory.graph import UNRESOLVED_PEOPLE
from infrastructure.database import SessionLocal, DocumentChunk, WorldFact, GraphOrganization, PersonResolution, CharacterMemory

PROMPT = Path(__file__).resolve().parents[2] / "prompts/memory/organize.md"


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str
    useful: bool
    category: Literal["event", "relationship", "trait", "background", "transition", "decoration", "repetition", "unknown"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)
    same_event_as: str = ""
    target_quote: str = Field(default="", max_length=500)


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    decision: Literal["same", "different", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    complete: bool
    reviews: list[Review] = Field(max_length=8)
    identities: list[Identity] = Field(default_factory=list, max_length=30)


def source_data(session, document_id):
    chunks = session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index).all()
    hashes = {c.id: hashlib.sha256(c.content.encode()).hexdigest() for c in chunks}
    facts = [{"id": f.id, "chunk_id": f.chunk_id, "content": f.content, "quote": f.source_quote, "graph": f.graph,
              "time": f.time_label} for f in session.query(WorldFact).filter(WorldFact.document_id == document_id).order_by(WorldFact.id)
             if f.source_hash == hashes.get(f.chunk_id) and f.status not in {"rejected", "stale"}]
    signature = hashlib.sha256(json.dumps([hashes, facts], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return [(c.id, c.content) for c in chunks], facts, signature


def organization_snapshot(session, document_id):
    row = session.get(GraphOrganization, document_id)
    if not row:
        return {"status": "pending", "processed": 0, "total": 0, "filtered": [], "uncertain": [], "groups": {}}
    state = row.state or {}
    current = source_data(session, document_id)[2] == row.signature
    return {"status": row.status if current else "outdated", "processed": len(state.get("reports", {})),
            "total": state.get("total", 0), "error": row.error, "filtered": state.get("filtered", []),
            "uncertain": state.get("uncertain", []), "auto_rule_ids": state.get("auto_rule_ids", []),
            "groups": state.get("groups", {}) if current and row.status == "completed" else {}}


def remember_override(session, document_id, rule):
    job = session.get(GraphOrganization, document_id)
    if not job:
        job = GraphOrganization(document_id=document_id, state={})
        session.add(job)
    state = deepcopy(job.state or {})
    pair = sorted([rule.name, rule.target])
    state["blocked_pairs"] = [*state.get("blocked_pairs", []), pair]
    state["auto_rule_ids"] = [rid for rid in state.get("auto_rule_ids", []) if rid != rule.id]
    job.state = state


def invalidate_memories(session, document_id):
    ids = session.query(WorldFact.id).filter(WorldFact.document_id == document_id)
    session.query(CharacterMemory).filter(CharacterMemory.world_fact_id.in_(ids), CharacterMemory.status == "active").update({"status": "draft"}, synchronize_session=False)


def apply_reports(session, document_id, facts, job):
    state = deepcopy(job.state)
    reviews = [r for report in state["reports"].values() for r in report["reviews"]]
    review_by_id = {r["id"]: r for r in reviews}
    proposals = [r for report in state["reports"].values() for r in report["identities"]]
    blocked = {tuple(pair) for pair in state.get("blocked_pairs", [])}
    uncertain = []
    ambiguous = {r["name"] for r in proposals if r["decision"] == "uncertain"}
    decisions = {}
    for p in proposals:
        decisions.setdefault(tuple(sorted([p["name"], p["target"]])), set()).add(p["decision"])
    # Resolve explicit distinctions first so transitive merges cannot override them.
    rules = rules_for(session, document_id)
    for p in sorted(proposals, key=lambda r: r["decision"] != "different"):
        pair = tuple(sorted([p["name"], p["target"]]))
        if pair in blocked or any({r["name"], r["target"]} == set(pair) for r in rules):
            continue
        if p["confidence"] < .9 or p["decision"] == "uncertain" or len(decisions[pair]) > 1 or (p["decision"] == "same" and ({p["name"], p["target"]} & ambiguous)):
            uncertain.append(p); continue
        candidate = {k: p[k] for k in ("name", "target", "decision")}
        try:
            aliases_for([*rules, candidate])
        except ValueError:
            uncertain.append(p); continue
        row = PersonResolution(document_id=document_id, **candidate)
        session.add(row); session.flush()
        state.setdefault("auto_rule_ids", []).append(row.id)
        rules.append({**candidate, "id": row.id})
    by_id = {f["id"]: f for f in facts}
    filtered, groups = [], {}
    for r in reviews:
        fact = session.get(WorldFact, r["id"])
        if fact.status == "active":  # Explicitly accepted or restored by a human.
            continue
        if r["useful"] and fact.status == "filtered":
            fact.status = "draft"
        if not r["useful"] and r["category"] in {"transition", "decoration", "repetition"} and r["confidence"] >= .9:
            # Repetition needs a verified target; information-bearing daily life stays.
            target_review = review_by_id.get(r["same_event_as"], {})
            if r["category"] != "repetition" or target_review.get("useful") is True:
                fact.status = "filtered"
                filtered.append({"id": fact.id, "reason": r["reason"], "quote": r["quote"]})
        elif not r["useful"] or r["confidence"] < .9:
            uncertain.append({"fact_id": r["id"], "reason": r["reason"], "quote": r["quote"]})
        target = r["same_event_as"]
        if target and r["confidence"] >= .9 and fact.graph.get("event") and by_id[target]["graph"].get("event"):
            a, b = fact.graph, by_id[target]["graph"]
            if a.get("start") and b.get("start") and a["start"] != b["start"]:
                uncertain.append({"fact_id": r["id"], "reason": "同一事件候选日期冲突，未归并"}); continue
            root, seen = target, {r["id"]}
            while root in groups and root not in seen:
                seen.add(root); root = groups[root]
            if root not in seen:
                groups[r["id"]] = root
    # Flatten validated event references. Source facts and additional information remain.
    for key in groups:
        while groups[key] in groups:
            groups[key] = groups[groups[key]]
    state.update(filtered=filtered, groups=groups, uncertain=uncertain)
    job.state, job.status, job.error = state, "completed", ""
    if filtered or groups or state.get("auto_rule_ids"):
        invalidate_memories(session, document_id)


async def organize_document(document_id, provider, input_budget):
    from core.chat.context import estimate_tokens
    prompt = PROMPT.read_text(encoding="utf-8")
    with SessionLocal() as session:
        chunks, facts, signature = source_data(session, document_id)
        job = session.get(GraphOrganization, document_id)
        if job and job.signature == signature and job.status == "completed":
            return
        if not job:
            job = GraphOrganization(document_id=document_id, state={}); session.add(job)
        state = deepcopy(job.state or {})
        if job.signature != signature:
            for rid in state.get("auto_rule_ids", []):
                old = session.get(PersonResolution, rid)
                if old: session.delete(old)
            if state.get("auto_rule_ids"): invalidate_memories(session, document_id)
            state = {"reports": {}, "blocked_pairs": state.get("blocked_pairs", [])}
        state.setdefault("reports", {})
        job.signature, job.status, job.state, job.error = signature, "running", state, ""
        manual_rules = rules_for(session, document_id)
        session.commit()
    names = sorted({n for f in facts for n in f["graph"].get("people", [])} | {n for f in facts for r in f["graph"].get("relationships", []) for n in (r["subject"], r["object"])})
    batches = []
    try:
        # Each call gets the full current source chunk and a bounded event catalog.
        for chunk_id, source in chunks:
            local = [f for f in facts if f["chunk_id"] == chunk_id]
            pending = local[:] or [None]
            while pending:
                batch = [f for f in pending[:8] if f]
                catalog = [f for f in facts if f["chunk_id"] != chunk_id and f["graph"].get("event")][:24]
                def payload():
                    return {"source": source, "facts": batch, "catalog": catalog,
                            "names": sorted(names, key=lambda n: n not in source)[:200], "confirmed_identities": manual_rules}
                while estimate_tokens(prompt + json.dumps(payload(), ensure_ascii=False)) > input_budget:
                    if catalog: catalog.pop()
                    elif len(batch) > 1: batch.pop()
                    else: raise ValueError("自动整理超出上下文预算，请使用更大上下文模型或减小分块")
                key = f"{chunk_id}:{len(local) - len(pending)}"
                batches.append((key, payload()))
                del pending[:max(1, len(batch))]
        with SessionLocal() as session:
            job = session.get(GraphOrganization, document_id)
            state = deepcopy(job.state); state["total"] = len(batches)
            state["reports"] = {key: report for key, report in state["reports"].items() if any(key == k and
                {r["id"] for r in report["reviews"]} == {f["id"] for f in payload["facts"]} for k, payload in batches)}
            job.state = state; session.commit()
        async with asyncio.timeout(1200):
            for key, payload in batches:
                await asyncio.sleep(0)
                with SessionLocal() as session:
                    job = session.get(GraphOrganization, document_id)
                    if key in job.state.get("reports", {}): continue
                async with asyncio.timeout(120):
                    raw = await provider.complete([{"role":"system", "content":prompt}, {"role":"user", "content":json.dumps(payload, ensure_ascii=False)}], temperature=0)
                if raw.strip().startswith("```"): raw = raw.strip().split("\n", 1)[1].rsplit("```", 1)[0]
                report = Report.model_validate_json(raw)
                local = {f["id"]: f for f in payload["facts"]}
                available = {f["id"]: f for f in [*payload["facts"], *payload["catalog"]]}
                if not report.complete or len(report.reviews) != len(local) or {r.id for r in report.reviews} != set(local):
                    raise ValueError("模型尚未完成当前片段审核，已保留进度，可继续")
                for r in report.reviews:
                    if r.quote not in local[r.id]["quote"]:
                        raise ValueError("整理结果的原文依据不匹配，未应用")
                    if r.same_event_as and (r.same_event_as not in available or r.same_event_as == r.id or not r.target_quote or r.target_quote not in available[r.same_event_as]["quote"]):
                        raise ValueError("事件归并目标或依据无效，未应用")
                for r in report.identities:
                    if r.name not in names or r.target not in names or r.name == r.target or r.name in UNRESOLVED_PEOPLE or r.target in UNRESOLVED_PEOPLE or r.quote not in payload["source"] or (r.decision != "uncertain" and (r.name not in r.quote or r.target not in r.quote)):
                        raise ValueError("人物身份依据不足，未自动合并")
                with SessionLocal() as session:
                    job = session.get(GraphOrganization, document_id)
                    if source_data(session, document_id)[2] != signature:
                        raise ValueError("原文或事实已变化，请重新整理")
                    state = deepcopy(job.state); state["reports"][key] = report.model_dump(); job.state = state; session.commit()
        with SessionLocal() as session:
            job = session.get(GraphOrganization, document_id)
            if source_data(session, document_id)[2] != signature: raise ValueError("资料已变化，请重新整理")
            apply_reports(session, document_id, facts, job); session.commit()
    except (Exception, asyncio.CancelledError) as exc:
        with SessionLocal() as session:
            job = session.get(GraphOrganization, document_id)
            if job:
                job.status = "paused" if isinstance(exc, asyncio.CancelledError) else "partial"
                job.error = str(exc) if type(exc) is ValueError else "自动整理未完成，已保留原记录与进度，可继续"
                session.commit()
        if isinstance(exc, asyncio.CancelledError): raise
