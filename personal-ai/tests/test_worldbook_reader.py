import json
import pytest
from pathlib import Path
from tests.test_story_documents import book
from infrastructure.config import settings
from infrastructure.database import SessionLocal, StoryBuild, Message, CandidateMemory, engine, _upgrade_sqlite_schema
from core.story.reader import paginate
from sqlalchemy import inspect, text


def test_upload_structured_book_reader_and_character_memory(client):
    data=book()
    data['events'][0]['text'] += '\n\n' + '她走过熟悉的路。'*500
    response=client.post('/api/files',files={'file':('世界书.json',json.dumps(data,ensure_ascii=False).encode(),'application/json')})
    assert response.status_code==201,response.text
    identity=response.json()['id']
    catalog=client.get('/api/worldbooks').json()
    assert catalog[0]['structured'] is True
    first=client.get(f'/api/worldbooks/{identity}').json()
    assert first['total']>2 and 'personal-ai-story' not in first['content']['text']
    pages=[client.get(f'/api/worldbooks/{identity}?page={i}').json()['content']['text'] for i in range(first['total'])]
    assert sum(t.count('她走过熟悉的路。') for t in pages)==500
    assert data['source_note'] in '\n'.join(pages)
    assert data['characters'][0]['description'] in '\n'.join(pages)
    assert client.get(f'/api/worldbooks/{identity}?page=999').status_code==404
    created=client.post(f'/api/stories/{identity}/characters/a').json()
    assert created['memories']==1 and created['candidates']==0
    memories=client.get('/api/characters/'+created['agent_id']+'/memories').json()['memories']
    assert len(memories)==1 and memories[0]['source_available']


def test_reader_does_not_stop_at_twenty_chunks(client):
    content='\n\n'.join(f'第 {i} 段独特正文。'+'叙述故事。'*100 for i in range(70))
    response=client.post('/api/files',files={'file':('长篇.txt',content.encode(),'text/plain')})
    assert response.status_code==201
    identity=response.json()['id']
    first=client.get(f'/api/worldbooks/{identity}').json()
    last=client.get(f'/api/worldbooks/{identity}?page={first["total"]-1}').json()
    assert '第 69 段' in last['content']['text']


@pytest.mark.skipif(engine.dialect.name != 'sqlite', reason='SQLite stamped revision repair')
def test_repair_stamped_database_without_candidate_table():
    CandidateMemory.__table__.drop(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='sqlite_20260923_10'"))
    _upgrade_sqlite_schema()
    assert 'candidate_memories' in inspect(engine).get_table_names()


def test_chat_generation_uses_validated_latest_proposal_and_default_folder(client,tmp_path,monkeypatch):
    from apps.api import story_builds
    from apps.api.main import app
    store=app.state.runtime_settings_store
    agents=store.snapshot()['agents']
    profile=agents['items'][0]
    # Use API to edit test-only profile; production prompts are untouched.
    payload={key:profile[key] for key in ('profile_name','name','role','language','tone','verbosity','humor','formality','proactivity')}
    result=client.patch('/api/settings/agents/'+profile['id'],json={**payload,'custom_instructions':'story-build story-questions'})
    assert result.status_code==200,result.text
    conv=client.post('/api/conversations',json={'agent_id':profile['id']}).json()['id']
    proposal={'brief':'写一个原创校园世界，少女寻找失踪的钟表，所有角色视角彼此隔离。','chapter_count':2,'min_chapter_chars':400}
    with SessionLocal() as s:
        message=Message(conversation_id=conv,role='assistant',content='```story-build\n'+json.dumps(proposal)+'\n```',status='completed')
        s.add(message);s.commit();mid=message.id
    monkeypatch.setattr(settings,'workspace_root_dir',str(tmp_path))
    monkeypatch.setattr(story_builds,'launch',lambda *args: None)
    monkeypatch.setattr(settings,'llm_provider','mock')
    status=client.get('/api/story-builds/conversation/'+conv)
    assert status.status_code==200,status.text
    assert status.json()['proposal']['chapter_count']==2
    result=client.post('/api/story-builds/conversation/'+conv+'/start',json={'message_id':mid})
    assert result.status_code==200,result.text
    again=client.post('/api/story-builds/conversation/'+conv+'/start',json={'message_id':mid})
    assert again.json()['id']==result.json()['id']
    with SessionLocal() as s:
        job=s.get(StoryBuild,result.json()['id'])
        assert Path(job.output_dir)==tmp_path/'worldbooks'
        assert (Path(job.output_dir)/('worldbook-'+job.id)).is_dir()
    assert client.post('/api/story-builds/conversation/'+conv+'/start',json={'message_id':'outdated'}).status_code==409
