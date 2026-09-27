"""Deterministic import: event boundaries precede embedding token splitting."""
import json
from collections import Counter
from types import SimpleNamespace
from core.story.document import markdown, stable_id, index_events
from core.rag.chunking import split_into_chunks
from core.rag.parsers import ParsedBlock
from core.rag.ingestion import save_file, content_hash, resolve_stored_file
from core.memory.world import digest
from infrastructure.database import Document, DocumentChunk, DocumentGraphChunk, WorldFact, SessionLocal


def import_story(story, provider, settings):
    data = markdown(story).encode("utf-8")
    fingerprint = content_hash(data)
    with SessionLocal() as session:
        existing = session.query(Document).filter_by(content_hash=fingerprint).first()
        if existing:
            return existing.id
    config = SimpleNamespace(**settings.model_dump())
    config.rag_chunk_max_tokens = min(settings.rag_chunk_max_tokens, getattr(provider, "max_tokens", settings.rag_chunk_max_tokens) - 8)
    pieces = []
    for event in index_events(story):
        for part in split_into_chunks([ParsedBlock(event.stage + " > " + event.title, event.text)], provider.count_tokens, config):
            pieces.append((event, part))
    if not pieces:
        raise ValueError("故事没有可导入的事件正文")
    piece_counts = Counter(event.id for event, _ in pieces)
    vectors = []
    for start in range(0, len(pieces), settings.embedding_batch_size):
        vectors.extend(provider.embed_documents([part.content for _, part in pieces[start:start+settings.embedding_batch_size]]))
    if len(vectors) != len(pieces):
        raise ValueError("向量数量与事件片段不一致")
    stored = save_file(data, ".md", settings)
    try:
        with SessionLocal() as session:
            doc = Document(original_filename=story.title + ".md", stored_filename=stored, mime_type="text/markdown", file_type=".md",
                size_bytes=len(data), content_hash=fingerprint, status="indexed", chunk_count=len(pieces),
                embedding_model=provider.model_name, embedding_dim=provider.dimension)
            session.add(doc); session.flush()
            people = {p.id: p.name + " [" + p.id + "]" for p in story.characters}
            for index, ((event, part), vector) in enumerate(zip(pieces, vectors, strict=True)):
                chunk = DocumentChunk(document_id=doc.id, chunk_index=index, section=part.section, content=part.content, embedding=vector)
                session.add(chunk); session.flush()
                session.add(DocumentGraphChunk(document_id=doc.id, chunk_id=chunk.id, source_hash=digest(chunk.content), status="completed"))
                session.add(WorldFact(id=stable_id(doc.id, event.id, str(index)), document_id=doc.id, chunk_id=chunk.id,
                    source_hash=digest(chunk.content), content=chunk.content[:1200], source_quote=chunk.content[:500], time_label=event.time,
                    graph={"event": event.title, "stage":event.stage, "story_event_id":event.id,
                        "source_chunk_count":piece_counts[event.id], "people":[people[p] for p in event.participants]}, status="active"))
            session.commit()
            return doc.id
    except Exception:
        resolve_stored_file(stored, settings).unlink(missing_ok=True)
        raise
