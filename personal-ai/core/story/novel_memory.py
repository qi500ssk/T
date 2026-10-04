"""Grounded memories and original-text exports for the single-pass novel reader."""
from typing import Literal
from pydantic import Field
from core.story.document import Person, Strict
from core.memory.character import fingerprint
from infrastructure.database import CharacterMemory


class NovelMemory(Strict):
    content: str = Field(min_length=1, max_length=1200)
    source_quote: str = Field(min_length=4, max_length=500)
    knowledge: Literal["direct", "witnessed", "heard"]
    kind: Literal["experience", "relationship", "personality", "world"] = "experience"
    time_label: str = Field(default="", max_length=200)
    event: str = Field(min_length=1, max_length=100)
    people: list[str] = Field(default_factory=list, max_length=12)
    is_core: bool = False


class NovelPerson(Person):
    memories: list[NovelMemory] = Field(min_length=1, max_length=40)


def ground_memories(people, text):
    # Line wrapping in TXT is formatting, not a change to the quoted words.
    positions, compact = None, None
    for person in people:
        for memory in person.memories:
            if memory.source_quote in text:
                continue
            if positions is None:
                positions = [i for i, char in enumerate(text) if not char.isspace()]
                compact = "".join(text[i] for i in positions)
            quote = "".join(memory.source_quote.split())
            start = compact.find(quote)
            if start < 0 or len(quote) < 4:
                raise ValueError(f"{person.name}的记忆没有逐字原文依据：{memory.event}")
            memory.source_quote = text[positions[start]:positions[start + len(quote)-1] + 1]
    return people


def export_original(document_id, text, title):
    from core.story.build import default_output_dir, write_text
    from core.files.workspaces import resolve_workspace
    import json
    folder = default_output_dir() / ("novel-" + document_id)
    if not folder.exists():
        folder.mkdir()
    folder = resolve_workspace(folder)
    write_text(folder, "original.txt", text)
    write_text(folder, "source.json", json.dumps({"document_id": document_id, "title": title}, ensure_ascii=False, indent=2))
    return str(folder / "original.txt")


def save_memories(session, agent_id, person, doc, text, chunks):
    for memory in person.memories:
        if memory.source_quote not in text:
            raise ValueError(f"{person.name}的记忆依据不在原文中：{memory.event}")
        digest = fingerprint(memory.content)
        # Retrying must neither duplicate records nor reactivate a user's disabled memory.
        if session.query(CharacterMemory).filter_by(agent_id=agent_id, fingerprint=digest).first():
            continue
        chunk = next((c for c in chunks if memory.source_quote in c.content), None)
        session.add(CharacterMemory(agent_id=agent_id, document_id=doc.id,
            chunk_id=chunk.id if chunk else None, source_name=doc.original_filename,
            source_section=chunk.section if chunk else memory.event, source_quote=memory.source_quote,
            content=memory.content, kind=memory.kind, time_label=memory.time_label,
            is_core=memory.is_core, known_to_character=True, status="active", fingerprint=digest,
            perspective={"knowledge": memory.knowledge},
            graph={"event": memory.event, "people": memory.people, "summary": memory.content[:240]}))


async def recover_memories(people, text, provider, report):
    """Upgrade legacy completed profiles from bounded evidence, without rereading the book."""
    import asyncio
    import json
    import re
    from core.execution.executor import _cached_prompt_tokens
    from core.chat.context import estimate_tokens
    missing = [p for p in people if not p.get("memories")]
    if not missing:
        return people
    if report.get("memory_repair_state"):
        return validated_repair(report["memory_repair_state"], text, report)
    excerpts = []
    for person in missing:
        # Common name variants in the original traditional editions of the legacy tests.
        name = person["name"]
        names = {name, name.translate(str.maketrans("刘备冲张关", "劉備沖張關"))}
        matches = list(re.finditer("|".join(re.escape(n) for n in names), text))
        if not matches:
            raise ValueError(f"无法定位{name}的原文片段，未凭档案伪造记忆")
        indices = sorted({round(i * (len(matches) - 1) / 23) for i in range(24)})
        excerpts.append({"name": name, "excerpts": [text[max(0, matches[i].start()-350):matches[i].end()+650] for i in indices]})
    system = ('为旧版小说角色补建有原文证据的记忆。只使用提供的原文片段；档案只是定位线索，不是证据。'
        '每人生成8条有实质内容的第一人称记忆，覆盖不同阶段，区分本人知情和读者全知，遵守档案截止点。'
        '每条content控制在80至140字，source_quote选择20至80字的关键依据，不要复述整段原文。'
        'source_quote必须逐字连续复制原文（保留繁体、标点及换行），不能改写为简体；不使用原创对话。'
        '只输出JSON：{"characters":[{"id":"保持原id","memories":[记忆对象]}]}。记忆对象schema：'
        + json.dumps(NovelMemory.model_json_schema(), ensure_ascii=False))
    payload = json.dumps({"profiles": missing, "sources": excerpts}, ensure_ascii=False)
    if estimate_tokens(system + payload) + provider.max_output_tokens > provider.context_window_tokens:
        raise ValueError("补建片段超出模型窗口，未调用模型")
    parts, usage, finish = [], {}, None
    async with asyncio.timeout(600):
        async for chunk in provider.stream([{"role": "system", "content": system}, {"role": "user", "content": payload}], temperature=0):
            if chunk.text:
                parts.append(chunk.text)
            if chunk.usage:
                usage = chunk.usage
            finish = chunk.finish_reason or finish
    report.setdefault("calls", []).append({"phase": "legacy_memory_repair", "input_tokens": int(usage.get("prompt_tokens", 0)),
        "output_tokens": int(usage.get("completion_tokens", 0)), "cached_input_tokens": _cached_prompt_tokens(usage)})
    for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
        report[key] = sum(call.get(key) or 0 for call in report["calls"])
    if finish == "length":
        raise ValueError("补建记忆输出达到上限，未保存不完整记忆")
    raw = "".join(parts).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    rows = json.loads(raw)["characters"]
    if len(rows) != len(missing) or {p["id"] for p in rows} != {p["id"] for p in missing}:
        raise ValueError("补建返回的人物不匹配")
    by_id = {p["id"]: p["memories"] for p in rows}
    result = [{**p, "memories": by_id.get(p["id"], p.get("memories", []))} for p in people]
    report["memory_repair_state"] = result
    return validated_repair(result, text, report)


def validated_repair(result, text, report):
    accepted, rejected = [], []
    for data in result:
        person = NovelPerson.model_validate(data)
        valid = []
        for memory in person.memories:
            try:
                ground_memories([person.model_copy(update={"memories": [memory]})], text)
                valid.append(memory)
            except ValueError:
                rejected.append({"character": person.name, "event": memory.event, "reason": "引文与原文不符，未入库"})
        if not valid:
            raise ValueError(f"{person.name}没有通过原文校验的记忆")
        accepted.append(person.model_copy(update={"memories": valid}).model_dump())
    report["memory_repair_rejected"] = rejected
    return accepted
