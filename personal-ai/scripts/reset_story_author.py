"""One-time user-authorized reset of three specified local profiles."""
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy import or_
from infrastructure.config import settings
from infrastructure.database import (SessionLocal, AgentRun, CharacterExtraction, Conversation, CharacterMemory,
    Memory, ProjectAgentAccess, Document, Activity)
from core.chat.character import load_character
from core.settings.runtime import default_agent_profile

EXPECTED = {"default", "ee3759deb80b4f50a26971dc58926696", "4a6a2a7dc4384b99bbd97ebc65335d10"}
path = Path(settings.runtime_settings_file).resolve()
raw = json.loads(path.read_text(encoding="utf-8"))
profiles = raw.get("agents", {}).get("items", [])
if {p["id"] for p in profiles} != EXPECTED:
    raise SystemExit("Profiles changed; refusing to delete unrelated profiles")
with SessionLocal() as session:
    if session.query(AgentRun).filter_by(status="running").first() or session.query(CharacterExtraction).filter_by(status="running").first():
        raise SystemExit("Running tasks found; finish or stop them before reset")
    from infrastructure.database import DocumentGraphChunk, GraphOrganization
    if session.query(DocumentGraphChunk).filter_by(status="running").first() or session.query(GraphOrganization).filter_by(status="running").first():
        raise SystemExit("Running graph task found; stop it before reset")
    conversations = [r.id for r in session.query(Conversation).filter(Conversation.agent_id.in_(EXPECTED))]
backup = path.parent / "backups" / ("before-story-author-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
backup.mkdir(parents=True)
shutil.copy2(path, backup / "runtime-settings.json")
from infrastructure.database import engine
with sqlite3.connect(engine.url.database) as source, sqlite3.connect(backup / "personal-ai.db") as target:
    source.backup(target)
avatar_root=Path(settings.agent_avatar_storage_dir).resolve()
source_avatar=avatar_root / "4a6a2a7dc4384b99bbd97ebc65335d10.png"
shutil.copy2(source_avatar, avatar_root / "story-author.png")
with SessionLocal() as session:
    session.query(Activity).filter(Activity.conversation_id.in_(conversations)).delete(synchronize_session=False)
    session.commit()
from apps.api.main import delete_conversation
for cid in conversations:
    delete_conversation(cid)
with SessionLocal() as session:
    background=session.query(CharacterMemory).filter(CharacterMemory.agent_id.in_(EXPECTED)).delete(synchronize_session=False)
    session.query(CharacterExtraction).filter(CharacterExtraction.agent_id.in_(EXPECTED)).delete(synchronize_session=False)
    memory=session.query(Memory).filter(or_(Memory.scope_key.in_(EXPECTED | set(conversations)), Memory.source_conversation_id.in_(conversations))).delete(synchronize_session=False)
    session.query(ProjectAgentAccess).filter(ProjectAgentAccess.agent_id.in_(EXPECTED)).delete(synchronize_session=False)
    session.query(Document).filter(Document.agent_id.in_(EXPECTED)).update({"agent_id":None},synchronize_session=False)
    session.commit()
profile={"id":"story-author","profile_name":"故事文档助手",**default_agent_profile(load_character(settings.character_file))}
raw["agents"]={"active_agent_id":"story-author","items":[profile]}
raw.pop("agent",None)
temp=path.with_suffix(".reset.tmp")
temp.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding="utf-8")
temp.replace(path)
print(json.dumps({"conversations_deleted":len(conversations),"background_memories_deleted":background,"chat_memories_deleted":memory,"backup":str(backup),"active_agent":"story-author"}))
