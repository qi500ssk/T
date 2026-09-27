import asyncio
import json

import pytest

from core.memory.organize import organize_document
from core.memory.world import digest, document_graph_snapshot, extract_document_graph
from infrastructure.database import SessionLocal, Document, DocumentChunk, DocumentGraphChunk, WorldFact, GraphOrganization, PersonResolution


def fixture(conflict=False):
    with SessionLocal() as s:
        doc = Document(original_filename="生活.txt", stored_filename="organize.txt", mime_type="text/plain", file_type=".txt",
                       size_bytes=100, content_hash="organize", status="indexed", chunk_count=2, embedding_model="keyword-v1", embedding_dim=0)
        s.add(doc); s.flush()
        sources = ["后藤一里，简称一里。一天过去，第二天又过去。她每天给朋友留早餐。第一次演出开始。",
                   "一里和后藤一里是不同的两个人。" if conflict else "那场第一次演出中，一里弹了吉他。"]
        ids = []
        for index, source in enumerate(sources):
            chunk = DocumentChunk(document_id=doc.id, chunk_index=index, content=source, section="生活", embedding=[])
            s.add(chunk); s.flush()
            s.add(DocumentGraphChunk(document_id=doc.id, chunk_id=chunk.id, source_hash=digest(source), status="completed"))
            texts = ["一天过去，第二天又过去。", "她每天给朋友留早餐。", "第一次演出开始。"] if index == 0 else [source]
            for text in texts:
                event = "第一次演出" if "演出" in text else ""
                fact = WorldFact(document_id=doc.id, chunk_id=chunk.id, source_hash=digest(source), content=text, source_quote=text,
                                 graph={"people":["一里", "后藤一里"], "event":event}, status="draft")
                s.add(fact); s.flush(); ids.append(fact.id)
        s.commit()
        return doc.id, ids


class Organizer:
    def __init__(self, invalid=False, pause=False):
        self.calls = []; self.invalid = invalid; self.pause = pause; self.waiting = asyncio.Event(); self.closed = False
    async def complete(self, messages, temperature=0):
        data = json.loads(messages[-1]["content"]); self.calls.append(data)
        if self.pause and len(self.calls) == 2:
            self.waiting.set(); await asyncio.Event().wait()
        reviews = []
        for f in data["facts"]:
            transition = f["content"].startswith("一天")
            target = next((c for c in data["catalog"] if "第一次演出开始" in c["content"]), None) if "弹了吉他" in f["content"] else None
            reviews.append({"id":f["id"], "useful":not transition, "category":"transition" if transition else "event", "confidence":.98,
                            "reason":"纯过渡" if transition else "人物习惯或实际事件", "quote":"伪造依据" if self.invalid else f["quote"],
                            "same_event_as":target["id"] if target else "", "target_quote":target["quote"] if target else ""})
        identity = {"name":"一里", "target":"后藤一里", "decision":"same", "confidence":.99, "reason":"原文明确简称", "quote":"后藤一里，简称一里。"}
        if "不同的两个人" in data["source"]:
            identity.update(decision="different", reason="原文明确区分", quote="一里和后藤一里是不同的两个人。")
        return json.dumps({"complete":True, "reviews":reviews, "identities":[identity] if "后藤一里" in data["source"] else []}, ensure_ascii=False)
    async def close(self): self.closed = True


def snapshot(doc):
    with SessionLocal() as s: return document_graph_snapshot(s, s.get(Document, doc))


@pytest.mark.asyncio
async def test_automatic_filter_identity_and_shared_event_preserve_sources():
    doc, ids = fixture()
    provider = Organizer()
    await extract_document_graph(doc, provider, 12000, organize=True, organize_only=True)
    data = snapshot(doc)
    assert provider.closed and len(provider.calls) == 2
    assert data["organization"]["status"] == "completed"
    assert [f["id"] for f in data["filtered_facts"]] == [ids[0]]
    assert any("早餐" in f["content"] for f in data["facts"])
    assert {n["label"] for n in data["nodes"] if n["type"] == "person"} == {"后藤一里"}
    events = [n for n in data["nodes"] if n["type"] == "event"]
    assert len(events) == 1 and set(events[0]["memory_ids"]) == {ids[2], ids[3]}
    with SessionLocal() as s:
        assert s.query(WorldFact).count() == 4
        assert "一天过去" in s.query(DocumentChunk).filter_by(document_id=doc).first().content
    again = Organizer(); await organize_document(doc, again, 12000)
    assert not again.calls


@pytest.mark.asyncio
async def test_conflicting_later_context_prevents_automatic_name_merge():
    doc, _ = fixture(conflict=True)
    await organize_document(doc, Organizer(), 12000)
    data = snapshot(doc)
    assert not data["identity_rules"]
    assert data["organization"]["uncertain"]
    assert {n["label"] for n in data["nodes"] if n["type"] == "person"} == {"一里", "后藤一里"}


@pytest.mark.asyncio
async def test_invalid_evidence_does_not_hide_facts():
    doc, _ = fixture()
    await organize_document(doc, Organizer(invalid=True), 12000)
    data = snapshot(doc)
    assert data["organization"]["status"] == "partial"
    assert len(data["facts"]) == 4 and not data["filtered_facts"] and not data["identity_rules"]


@pytest.mark.asyncio
async def test_cancellation_preserves_review_batches_and_defers_all_changes():
    doc, _ = fixture()
    provider = Organizer(pause=True)
    task = asyncio.create_task(extract_document_graph(doc, provider, 12000, organize=True, organize_only=True))
    await asyncio.wait_for(provider.waiting.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    data = snapshot(doc)
    assert data["organization"]["status"] == "paused" and data["organization"]["processed"] == 1
    assert not data["filtered_facts"] and not data["identity_rules"] and provider.closed
    resume = Organizer(); await organize_document(doc, resume, 12000)
    assert len(resume.calls) == 1 and snapshot(doc)["organization"]["status"] == "completed"


@pytest.mark.asyncio
async def test_manual_restore_and_undo_are_not_overwritten(client):
    doc, ids = fixture()
    await organize_document(doc, Organizer(), 12000)
    data = snapshot(doc); rule_id = data["identity_rules"][0]["id"]
    assert client.delete(f"/api/documents/{doc}/graph/identities/{rule_id}").status_code == 200
    f = data["filtered_facts"][0]
    body = {k:f[k] for k in ("content", "source_quote", "time_label", "evidence_type", "graph")}; body["status"] = "active"
    assert client.patch(f"/api/documents/{doc}/graph/facts/{ids[0]}", json=body).status_code == 200
    with SessionLocal() as s:
        job = s.get(GraphOrganization, doc); job.status = "partial"; s.commit()
    await organize_document(doc, Organizer(), 12000)
    data = snapshot(doc)
    assert not data["identity_rules"] and not data["filtered_facts"]
    assert any(f["id"] == ids[0] for f in data["facts"])


@pytest.mark.asyncio
async def test_manual_distinction_wins_and_small_budget_is_explicit():
    doc, _ = fixture()
    with SessionLocal() as s:
        s.add(PersonResolution(document_id=doc, name="一里", target="后藤一里", decision="different")); s.commit()
    provider = Organizer(); await organize_document(doc, provider, 10)
    assert not provider.calls and snapshot(doc)["organization"]["status"] == "partial"
    await organize_document(doc, Organizer(), 12000)
    assert snapshot(doc)["identity_rules"][0]["decision"] == "different"
