import pytest
from core.story.document import Story
from core.memory.character import resolve_character_memories
from infrastructure.database import SessionLocal, CharacterMemory, WorldFact


def book():
    return {"format":"personal-ai-story-v1","title":"双人故事","basis":"original","source_note":"用户原创设定",
      "characters":[{"id":"a","name":"小雨","description":"喜欢读书"},{"id":"b","name":"小雨","description":"另一位同名人物，喜欢画画"}],
      "events":[{"id":"e1","stage":"初遇","title":"散步","text":"小雨甲独自在公园散步。","participants":["a"],"viewpoints":[{"character_id":"a","knowledge":"direct","memory":"我在公园散步。","quote":"独自在公园散步","known_people":[]}]},
                {"id":"e2","stage":"秘密","title":"秘密计划","text":"小雨乙独自计划远行，没有告诉任何人。","participants":["b"],"viewpoints":[{"character_id":"b","knowledge":"direct","memory":"我私下计划远行。","quote":"独自计划远行","known_people":[]},{"character_id":"a","knowledge":"unknown"}]}]}


def test_confirmed_story_import_and_character_isolation(client):
    import json
    body={"text":json.dumps(book(),ensure_ascii=False)}
    preview=client.post('/api/stories/preview',json=body)
    assert preview.status_code==200 and len(preview.json()['characters'])==2
    assert client.post('/api/stories/import',json=body).status_code==422
    response=client.post('/api/stories/import',json={**body,"confirmed":True})
    assert response.status_code==200, response.text
    doc=response.json()['document_id']
    first=client.post(f'/api/stories/{doc}/characters/a')
    second=client.post(f'/api/stories/{doc}/characters/b')
    assert first.status_code==second.status_code==200
    a,b=first.json()['agent_id'],second.json()['agent_id']
    assert a!=b
    assert client.post(f'/api/stories/{doc}/characters/a').status_code==409
    with SessionLocal() as s:
        rows=s.query(CharacterMemory).filter_by(agent_id=a).all()
        resolved=resolve_character_memories(s,rows)
        assert len(resolved)==1 and '远行' not in str([(m.content,m.source_quote,m.graph) for m in resolved])
        assert len(s.query(CharacterMemory).filter_by(agent_id=b).all())==1
        assert s.query(WorldFact).filter_by(document_id=doc).count()==2
    assert len(client.get(f'/api/characters/{a}/memories').json()['memories'])==1


def test_story_rejects_invalid_identity_and_evidence():
    data=book(); data['events'][0]['viewpoints'][0]['quote']='不存在的原文'
    with pytest.raises(ValueError): Story.model_validate(data)
    data=book(); data['characters'][1]['id']='a'
    with pytest.raises(ValueError): Story.model_validate(data)
    data=book(); data['events'][0]['participants']=['missing']
    with pytest.raises(ValueError): Story.model_validate(data)
