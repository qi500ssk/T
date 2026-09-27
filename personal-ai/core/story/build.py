"""Bounded, resumable worldbook writing with durable chapter checkpoints."""
import asyncio
import json
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError
from core.story.document import Story, Person, Lore, Event, markdown
from core.files.workspaces import resolve_workspace, workspace_root
from core.rag.retrieval import tokenize_for_bm25
from core.chat.context import estimate_tokens
from core.memory.admission import memory_plan
from infrastructure.database import SessionLocal, StoryBuild, DocumentChunk

PROMPTS = Path(__file__).resolve().parents[2] / "prompts/system"


def default_output_dir():
    root = resolve_workspace(workspace_root())
    folder = root / "worldbooks"
    if not folder.exists() and not folder.is_symlink():
        folder.mkdir()
    return resolve_workspace(folder)

class ChapterPlan(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    scope: str = Field(min_length=1, max_length=2000)
    sources_needed: str = Field(default="", max_length=2000)

class Plan(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    basis: str
    source_note: str = Field(min_length=1, max_length=2000)
    characters: list[Person] = Field(min_length=1, max_length=30)
    chapters: list[ChapterPlan] = Field(min_length=2, max_length=30)
    world_entries: list[Lore] = Field(default_factory=list, max_length=60)

class ChapterOutput(BaseModel):
    events: list[Event] = Field(min_length=1, max_length=12)
    source_note: str = Field(default="", max_length=2000)

def json_text(raw):
    if raw.strip().startswith("```"):
        raw = raw.strip().split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)

def save_state(job_id, **values):
    with SessionLocal() as session:
        row = session.get(StoryBuild, job_id)
        for key, value in values.items(): setattr(row, key, value)
        session.commit()

def output_path(row):
    root = resolve_workspace(row.output_dir)
    folder = root / ("worldbook-" + row.id)
    if folder.exists(): resolve_workspace(folder)
    else: folder.mkdir()
    return resolve_workspace(folder)

def write_text(folder, name, text):
    target = folder / name
    if target.is_symlink() or (getattr(target, "is_junction", lambda: False)()):
        raise ValueError("输出文件不能为链接")
    temporary = folder / (name + ".tmp")
    if temporary.is_symlink(): raise ValueError("临时文件不能为链接")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)

def assembled(row):
    plan = row.plan
    return Story.model_validate({"format":"personal-ai-story-v1", "title":plan["title"], "basis":plan["basis"],
        "source_note":plan["source_note"], "characters":plan["characters"], "world_entries":plan.get("world_entries", []), "events":[e for chapter in row.chapters for e in chapter["events"]]})

def quality(row):
    lengths = [sum(len(e["text"]) for e in chapter["events"]) for chapter in row.chapters]
    issues = []
    if len(row.plan.get("world_entries", [])) < 6: issues.append("世界设定条目不足六条，请检查地点、组织、规则、历史与文化是否覆盖")
    if len(row.chapters) < row.request["chapter_count"]: issues.append("仍有章节未完成")
    for i, length in enumerate(lengths):
        if length < row.request["min_chapter_chars"]: issues.append(f"第 {i+1} 章正文 {length} 字，低于目标")
    for p in row.plan.get("characters", []):
        missing = [k for k in ("personality", "motivation", "speech", "relationships", "boundaries", "example_dialogue") if not p.get(k)]
        if missing: issues.append(f"{p['name']}：角色档案缺少 {', '.join(missing)}")
        if sum(len(p.get(k,"")) for k in ("description","personality","motivation","speech","relationships","boundaries","example_dialogue")) < 300:
            issues.append(f"{p['name']}：角色档案较简略，尚不足300字符，建议扩充")
    if row.plan.get("basis") != "original": issues.append("原作事实仍需核对所用来源；字数达标不代表原作覆盖完整")
    return {"narrative_chars":sum(lengths), "chapter_chars":lengths, "events":sum(len(c["events"]) for c in row.chapters), "issues":issues}

async def run_build(job_id, provider, web=None):
    try:
        with SessionLocal() as session: row = session.get(StoryBuild, job_id)
        folder = output_path(row)
        spec = row.request
        research = ""
        if spec.get("research_query"):
            if web is None: raise ValueError("联网核实不可用，请检查联网设置")
            research = await web.search({"query":spec["research_query"]})
        source_ids = spec.get("document_ids", [])
        with SessionLocal() as session:
            chunks = session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(source_ids)).order_by(DocumentChunk.document_id, DocumentChunk.chunk_index).all() if source_ids else []
        # Source excerpts are explicit and bounded; no claim of full-source coverage.
        sources = [{"document":c.document_id,"section":c.section,"text":c.content[:3000]} for c in chunks]
        save_state(job_id, status="planning" if not row.plan else "writing", error="")
        async def ask(prompt, payload):
            system = (PROMPTS / prompt).read_text(encoding="utf-8")
            user = json.dumps(payload, ensure_ascii=False)
            window = getattr(provider, "context_window_tokens", 131072)
            if estimate_tokens(system + user) + getattr(provider, "max_output_tokens", 6000) > window:
                raise ValueError("需求和资料超过当前模型上下文预算，请选择更大上下文模型或缩小本次范围")
            return json_text(await asyncio.wait_for(provider.complete([
                {"role":"system","content":system}, {"role":"user","content":user}], temperature=0.4), timeout=180))
        if not row.plan:
            correction = ""
            for attempt in range(2):
                try:
                    plan = Plan.model_validate(await ask("story_plan.md", {"brief":spec["brief"], "chapter_count":spec["chapter_count"], "source_samples":sources[:8],"web_sources":research,"schema":Plan.model_json_schema(),"correction":correction}))
                    break
                except (ValidationError, json.JSONDecodeError) as exc:
                    correction = json.dumps([{ "field":".".join(str(x) for x in e["loc"]),"message":e["msg"]} for e in exc.errors()],ensure_ascii=False)[:1500] if isinstance(exc,ValidationError) else "返回的 JSON 不完整或语法错误，请只输出合法 JSON"
                    if attempt: raise ValueError("大纲结构校验失败："+correction[:250]) from None
            if len(plan.chapters) != spec["chapter_count"] or plan.basis not in {"original","source_based","adaptation"} or len({p.id for p in plan.characters}) != len(plan.characters):
                raise ValueError("章节规划数量或人物身份不符合要求")
            row.plan = plan.model_dump()
            save_state(job_id, title=plan.title, plan=row.plan, status="awaiting_plan")
            write_text(folder, "plan.json", json.dumps(row.plan, ensure_ascii=False, indent=2))
            if research: write_text(folder, "research-plan.json", json.dumps({"query":spec["research_query"],"result":research}, ensure_ascii=False, indent=2))
            return  # Explicit plan review before spending on chapters.
        for index in range(len(row.chapters), len(row.plan["chapters"])):
            chapter = row.plan["chapters"][index]
            chapter_research = await web.search({"query":spec["research_query"]+" "+chapter["title"]}) if research else ""
            terms = set(tokenize_for_bm25(chapter["title"] + " " + chapter["scope"]))
            local_sources = sorted(sources, key=lambda s:len(terms & set(tokenize_for_bm25(str(s["section"]) + s["text"]))), reverse=True)[:6]
            payload = {"brief":spec["brief"], "plan":row.plan, "current_chapter":chapter, "event_id_prefix":f"c{index+1}_", "min_narrative_chars":spec["min_chapter_chars"],
                "previous_events":[{"title":e["title"],"summary":e["text"][-200:]} for c in row.chapters[-2:] for e in c["events"]],
                "source_excerpts":local_sources, "web_sources":chapter_research, "source_coverage":{"available_chunks":len(sources),"included_chunks":len(local_sources)}, "schema":ChapterOutput.model_json_schema()}
            error = ""
            for attempt in range(2):
                try:
                    data = await ask("story_chapter.md", {**payload, "correction":error})
                    output = ChapterOutput.model_validate(data)
                    story = Story.model_validate({"format":"personal-ai-story-v1", "title":chapter["title"],
                        "basis":row.plan["basis"], "source_note":output.source_note or row.plan["source_note"],
                        "characters":row.plan["characters"], "events":[e.model_dump() for e in output.events]})
                    renamed = {event.id:f"c{index+1}_e{n+1}" for n,event in enumerate(story.events)}
                    for n, event in enumerate(story.events):
                        event.parent_event_id = renamed.get(event.parent_event_id) if event.parent_event_id else None
                        event.id = f"c{index+1}_e{n+1}"
                        event.stage = f"{index+1:02d} {chapter['title']}"
                    if sum(len(e.text) for e in story.events) < spec["min_chapter_chars"]:
                        raise ValueError("章节正文不足，不能用摘要充当完整章节；请展开具体过程，来源不足请补充资料后继续")
                    break
                except (ValueError, KeyError) as exc:
                    error = str(exc)[:500]
                    if attempt: raise ValueError(error) from None
            existing_text = {e["text"].strip() for c in row.chapters for e in c["events"]}
            if any(e.text.strip() in existing_text for e in story.events): raise ValueError("章节重复了已保存事件，请调整大纲后重建任务")
            row.chapters = [*row.chapters, story.model_dump()]
            save_state(job_id, chapters=row.chapters, status="writing", report=quality(row))
            write_text(folder, f"chapter-{index+1:02d}.md", markdown(story))
            write_text(folder, f"sources-{index+1:02d}.json", json.dumps({"documents":local_sources,"web":chapter_research}, ensure_ascii=False, indent=2))
        final = assembled(row)
        write_text(folder, "worldbook.md", markdown(final))
        write_text(folder, "worldbook.json", final.model_dump_json(indent=2))
        for person in final.characters:
            admitted = memory_plan(final,person.id)
            personal = lambda status: [item["view"].model_dump() | {"event_id":item["event"].id,"time":item["event"].time}
                for item in admitted if item["status"] == status and not item["event"].id.startswith("lore_")]
            write_text(folder, "character-"+person.id+".json", json.dumps({"character":person.model_dump(),"memories":personal("active"),
                "candidate_memories":personal("draft"),"known_world_entries":[l.model_dump() for l in final.world_entries if person.id in l.known_by]}, ensure_ascii=False, indent=2))
        report = quality(row)
        write_text(folder, "quality.json", json.dumps(report, ensure_ascii=False, indent=2))
        save_state(job_id, status="review", report=report, error="")
    except asyncio.CancelledError:
        save_state(job_id, status="paused", error="已停止，完成章节已保存")
        raise
    except Exception as exc:
        # Never persist raw provider errors, which may include upstream credentials.
        message = str(exc)[:300] if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "模型调用或结构校验未完成，请检查模型连接与输出长度后继续"
        save_state(job_id, status="failed", error=message)
    finally:
        await provider.close()
