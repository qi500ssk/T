"""Read original document blocks, never overlapping embedding chunks."""
from core.story.document import parse_story
from core.rag.parsers import parse_document
from core.rag.ingestion import resolve_stored_file


def read_book(document, settings):
    path = resolve_stored_file(document.stored_filename, settings)
    story = None
    if document.file_type in {".md", ".txt", ".json"}:
        try:
            story = parse_story(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError):
            pass
    if story:
        return story_book(story)
    if document.file_type in {".txt", ".md"}:
        from core.story.books import decode, split_chapters
        sections = split_chapters(decode(path.read_bytes()), document.original_filename.rsplit(".", 1)[0])
        return {"title": document.original_filename.rsplit(".", 1)[0], "synopsis": sections[0]["text"][:180] if sections else "暂无正文",
            "structured": False, "sections": sections}
    parsed = parse_document(path, document.file_type, settings)
    sections = []
    for block in parsed.blocks:
        if sections and sections[-1]["title"] == block.section:
            sections[-1]["text"] += "\n\n" + block.content
        else:
            sections.append({"title": block.section, "text": block.content})
    return {"title": document.original_filename.rsplit(".", 1)[0],
            "synopsis": sections[0]["text"][:180] if sections else "暂无可阅读的正文",
            "structured": False, "sections": sections}


def story_book(story):
    sections = []
    for event in story.events:
        if sections and sections[-1]["stage"] == event.stage:
            sections[-1]["text"] += "\n\n" + event.text
        else:
            from core.story.books import CHAPTER
            title = event.stage if CHAPTER.match(event.stage) else f"第{len(sections)+1}章 {event.stage}"
            sections.append({"title": title, "stage": event.stage, "text": event.text})
    return {"title": story.title, "synopsis": story.events[0].text[:180], "structured": True, "sections": sections}
