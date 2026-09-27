"""Character-scoped admission; missing significance stays reviewable, never guessed."""
from core.story.document import index_events


def memory_plan(story, character_id):
    items = []
    for event in index_events(story):
        view = next((v for v in event.viewpoints if v.character_id == character_id), None)
        if view is None or view.knowledge == "unknown":
            items.append({"event": event, "view": view, "status": "excluded", "reason": "没有该角色知情的依据"})
            continue
        # Legacy worldbooks have grounded viewpoints but no scoring fields. The
        # validated quote + explicit knower is sufficient for episodic recall;
        # importance is a retrieval ranking, not a manual approval requirement.
        scored = bool(view.significance or view.importance_reason or view.confidence != 0.5)
        grounded = bool(view.memory.strip() and view.quote and view.quote in event.text)
        keep = grounded and (not scored or view.confidence >= 0.8)
        items.append({"event": event, "view": view, "status": "active" if keep else "draft",
                      "reason": (view.importance_reason or "世界书明确记录该人物知情，并有正文依据") if keep else "可信度不足，不参与聊天召回"})
    return items


def admission_preview(story, character_id):
    rows = memory_plan(story, character_id)
    return {"active": sum(r["status"] == "active" for r in rows),
            "candidates": sum(r["status"] == "draft" for r in rows),
            "excluded": sum(r["status"] == "excluded" for r in rows),
            "items": [{"event_id": r["event"].id, "title": r["event"].title, "time": r["event"].time,
                       "status": r["status"], "reason": r["reason"],
                       "memory": r["view"].memory if r["view"] and r["status"] != "excluded" else ""}
                      for r in rows]}
