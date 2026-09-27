import json
from datetime import datetime, timedelta, timezone
from tests.test_story_documents import book
from core.memory.admission import admission_preview
from core.story.document import Story
from core.memory.character import recall_character_memories, resolve_character_memories
from core.memory.conversation import MemoryCandidate, retrieve_memories
from core.memory.candidates import retain_candidates
from core.rag.retrieval import retrieve
from infrastructure.config import settings
from infrastructure.database import SessionLocal, CharacterMemory, DocumentChunk, WorldFact, CandidateMemory, Conversation, Memory


def important_book():
    data=book()
    data['events'][0]['viewpoints'][0].update(importance=4,significance=['decision'],importance_reason='这次散步后决定留在小镇',confidence=.95)
    return data


def imported(client,data):
    response=client.post('/api/stories/import',json={'text':json.dumps(data,ensure_ascii=False),'confirmed':True})
    assert response.status_code==200,response.text
    doc=response.json()['document_id']
    response=client.post(f'/api/stories/{doc}/characters/a')
    assert response.status_code==200,response.text
    return doc,response.json()


def test_grounded_legacy_memories_are_automatically_usable(client):
    data=book()
    report=admission_preview(Story.model_validate(data),'a')
    assert (report['active'],report['candidates'],report['excluded'])==(1,0,1)
    assert report['items'][1]['memory']==''
    doc,created=imported(client,data)
    assert created['memories']==1 and created['candidates']==0
    with SessionLocal() as s:
        assert recall_character_memories(s,created['agent_id'],'公园散步')
        assert s.query(CharacterMemory).one().status=='active'


def test_explicit_low_confidence_is_not_silently_activated(client):
    data=important_book()
    data['events'][0]['viewpoints'][0]['confidence']=0.3
    doc,created=imported(client,data)
    assert created['memories']==0
    with SessionLocal() as s:
        assert not recall_character_memories(s,created['agent_id'],'公园散步')


def test_story_attachment_cannot_bypass_viewpoint_or_disabled_memory(client):
    doc,created=imported(client,important_book());agent=created['agent_id']
    assert created['memories']==1
    with SessionLocal() as s:
        own=recall_character_memories(s,agent,'公园散步')
        assert len(own)==1 and '远行' not in own[0].content
        assert not retrieve(s,None,'秘密计划',settings,document_ids=[doc],agent_id=agent)
        assert retrieve(s,None,'秘密计划',settings,document_ids=[doc]) # source inspection still available to the user
        row=s.query(CharacterMemory).one();row.status='disabled';s.commit()
        assert not recall_character_memories(s,agent,'公园散步')
        assert not retrieve(s,None,'公园散步',settings,document_ids=[doc],agent_id=agent)


def test_edit_keeps_identity_and_missing_source_fails_closed(client):
    doc,created=imported(client,important_book());agent=created['agent_id']
    row=client.get(f'/api/characters/{agent}/memories').json()['memories'][0]
    body={'content':'我记得在公园散步。','source_quote':row['source_quote'],'status':'active',
        'perspective':{k:v for k,v in row['perspective'].items() if k in {'knowledge','content','evidence_quote','importance','importance_reason','emotion','confidence','relationship_change'}}}
    response=client.patch(f'/api/characters/{agent}/memories/{row["id"]}',json=body)
    assert response.status_code==200,response.text
    assert response.json()['perspective']['story_character_id']=='a'
    assert response.json()['perspective']['source_chunks']
    with SessionLocal() as s:
        memory=s.get(CharacterMemory,row['id']);s.delete(s.get(WorldFact,memory.world_fact_id));s.commit()
        assert not recall_character_memories(s,agent,'公园散步')
    response=client.patch(f'/api/characters/{agent}/memories/{row["id"]}',json=body)
    assert response.status_code==409


def test_long_event_tracks_all_source_chunks(client):
    data=important_book()
    data['events'][0]['text']='小雨甲独自在公园散步。'+'她仔细观察道路两旁的花草和树木。'*200+'她最后决定留在小镇。'
    data['events'][0]['viewpoints'][0]['quote']='她最后决定留在小镇。'
    doc,created=imported(client,data)
    with SessionLocal() as s:
        row=s.query(CharacterMemory).one()
        assert len(row.perspective['source_chunks'])>1
        assert row.source_quote in s.get(DocumentChunk,row.chunk_id).content
        sources=row.perspective['source_chunks']
        other=next(x for x in sources if x['id']!=row.chunk_id)
        s.get(DocumentChunk,other['id']).content='原作已改变';s.commit()
        assert not resolve_character_memories(s,[row])


def test_candidates_are_scoped_non_recallable_and_require_confirmation(client):
    _,created=imported(client,important_book());agent=created['agent_id']
    conv=client.post('/api/conversations',json={'agent_id':agent}).json()['id']
    with SessionLocal() as s:
        retain_candidates(s,[MemoryCandidate('interview','episodic','用户可能准备参加面试。',2,.6,'agent')],'default',agent,conv,3,.7)
        assert not retrieve_memories(s,'default','面试',10,agent_id=agent,conversation_id=conv)
        assert s.query(CandidateMemory).count()==1
    candidate=client.get(f'/api/characters/{agent}/memory-candidates').json()[0]
    assert client.post(f'/api/characters/default/memory-candidates/{candidate["id"]}/confirm').status_code==404
    assert client.post(f'/api/characters/{agent}/memory-candidates/{candidate["id"]}/confirm').status_code==200
    with SessionLocal() as s:
        assert len(retrieve_memories(s,'default','面试',10,agent_id=agent))==1
        assert not retrieve_memories(s,'default','面试',10,agent_id='another')


def test_candidate_dismissal_expiry_and_bound():
    with SessionLocal() as s:
        items=[MemoryCandidate(f'k{i}','episodic',f'待核对事件{i}',2,.6,'agent') for i in range(205)]
        retain_candidates(s,items,'default','a','conversation',3,.7)
        assert s.query(CandidateMemory).count()==200
        row=s.query(CandidateMemory).first();key=row.normalized_key;row.status='dismissed';s.commit()
        allowed=retain_candidates(s,[MemoryCandidate(key,'episodic','新的推测',5,.9,'agent')],'default','a','conversation',3,.7)
        assert not allowed
        row.expires_at=datetime.now(timezone.utc)-timedelta(days=1);s.commit()
        retain_candidates(s,[],'default','a','conversation',3,.7)
        assert s.query(CandidateMemory).count()==199


def test_role_deletion_requires_memory_cleanup_and_allows_clean_recreation(client):
    doc,created=imported(client,important_book());agent=created['agent_id']
    assert client.delete(f'/api/settings/agents/{agent}').status_code==409
    assert client.delete(f'/api/characters/{agent}/memories').status_code==200
    assert client.delete(f'/api/settings/agents/{agent}').status_code==200
    response=client.post(f'/api/stories/{doc}/characters/a')
    assert response.status_code==200,response.text
    assert response.json()['memories']==1
