import asyncio
import json
from pathlib import Path
from core.story.build import run_build, assembled
from core.story.document import Story
from infrastructure.database import SessionLocal, StoryBuild


def plan():
    return {"title":"潮汐镇","basis":"original","source_note":"用户原创设定",
        "characters":[{"id":"lin","name":"林","description":"修理钟表的少女","personality":"谨慎但好奇","motivation":"找到失踪的父亲","speech":"说话简短，紧张时停顿","relationships":"知道父亲是钟表匠","boundaries":"不知道父亲的去向","example_dialogue":"你好，这座钟还会走。"}],
        "chapters":[{"title":"旧钟","scope":"发现线索"},{"title":"码头","scope":"追查线索"}],
        "world_entries":[{"id":"dock","title":"码头","kind":"place","content":"镇民交易货物的码头。","known_by":["lin"]}]}

class Provider:
    def __init__(self, replies): self.replies=iter(replies);self.closed=False
    async def complete(self, messages, temperature=0): return json.dumps(next(self.replies),ensure_ascii=False)
    async def close(self): self.closed=True

def chapter(number, short=False):
    text=(f"第{number}章：林检查钟表，发现背面刻着码头的位置。她记下线索，决定等天亮后前往。" * (1 if short else 16))
    return {"format":"personal-ai-story-v1","title":"潮汐镇","basis":"original","source_note":"原创","characters":plan()["characters"],
        "events":[{"id":"e","stage":str(number),"title":"调查","text":text,"participants":["lin"],"viewpoints":[{"character_id":"lin","knowledge":"direct","memory":"我发现了码头的线索。","quote":"林检查钟表"}]}]}

def create(tmp_path):
    with SessionLocal() as s:
        row=StoryBuild(request={"brief":"创作一个少女调查钟表谜团的原创世界书。","chapter_count":2,"min_chapter_chars":400},output_dir=str(tmp_path))
        s.add(row);s.commit();return row.id

def test_plan_review_resume_files_and_character_scope(tmp_path):
    job=create(tmp_path)
    provider=Provider([plan()]);asyncio.run(run_build(job,provider))
    with SessionLocal() as s:
        row=s.get(StoryBuild,job);assert row.status=="awaiting_plan";assert row.chapters==[]
    assert provider.closed
    # First chapter survives a later model failure.
    asyncio.run(run_build(job,Provider([chapter(1)])))
    with SessionLocal() as s:
        row=s.get(StoryBuild,job);assert row.status=="failed";assert len(row.chapters)==1
    asyncio.run(run_build(job,Provider([chapter(2)])))
    with SessionLocal() as s:
        row=s.get(StoryBuild,job);assert row.status=="review";assert len(row.chapters)==2
        story=assembled(row);assert len({e.id for e in story.events})==2
    folder=tmp_path/("worldbook-"+job)
    assert (folder/"chapter-01.md").exists() and (folder/"chapter-02.md").exists()
    assert Story.model_validate_json((folder/"worldbook.json").read_text(encoding="utf-8")).title=="潮汐镇"
    card=json.loads((folder/"character-lin.json").read_text(encoding="utf-8"))
    assert len(card["memories"])==2 and not card["candidate_memories"] and len(card["known_world_entries"])==1

def test_short_chapter_is_not_marked_complete(tmp_path):
    job=create(tmp_path);asyncio.run(run_build(job,Provider([plan()])))
    asyncio.run(run_build(job,Provider([chapter(1,True),chapter(1,True)])))
    with SessionLocal() as s:
        row=s.get(StoryBuild,job);assert row.status=="failed" and not row.chapters
    assert not (tmp_path/("worldbook-"+job)/"worldbook.md").exists()

def test_build_api_paths_and_early_import(client,tmp_path):
    job=create(tmp_path)
    assert client.post(f"/api/story-builds/{job}/import").status_code==409
    listing=client.get("/api/story-builds");assert listing.status_code==200
    assert listing.json()["jobs"][0]["status"]=="paused"
    assert client.get(f"/api/story-builds/{job}/files/missing.json").status_code==404
    result=client.post('/api/story-builds',json={"brief":"一个关于未来校园的原创世界书，请完整规划人物和故事。","output_dir":str(Path(tmp_path.anchor))})
    assert result.status_code==422
