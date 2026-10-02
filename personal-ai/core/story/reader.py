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


def paginate(sections, limit=1500):
    pages = []
    for section in sections:
        text = section["text"].strip()
        while text:
            end = len(text) if len(text) <= limit else text.rfind("\n", limit // 2, limit)
            if end <= 0:
                boundaries = [text.rfind(mark, limit // 2, limit) for mark in "。！？.!?"]
                last = max(boundaries)
                end = last + 1 if last >= 0 else limit
            pages.append({"title": section["title"], "text": text[:end]})
            text = text[end:].lstrip()
    return pages


def story_book(story):
    sections = [{"title": "阅读说明与资料来源", "text": story.source_note}]
    for person in story.characters:
        fields = [("description", "人物档案"), ("personality", "性格"), ("motivation", "目标"),
                  ("speech", "说话方式"), ("relationships", "关系"), ("boundaries", "边界"),
                  ("example_dialogue", "原创对话示例")]
        sections.append({"title": "人物档案 · " + person.name,
            "text": "\n\n".join(label + "：" + getattr(person, field) for field, label in fields if getattr(person, field))})
    sections += [{"title": e.stage + " · " + e.title, "text": e.text} for e in story.events]
    sections += [{"title": "世界设定 · " + item.title, "text": item.content} for item in story.world_entries]
    return {"title": story.title, "synopsis": story.events[0].text[:180], "structured": True, "sections": sections}
