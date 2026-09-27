from apps.api.main import app
from infrastructure.database import SessionLocal, CharacterMemory, Document, WorldFact
from tests.test_person_identity import identity_fixture


def test_delete_all_background_memories_scoped_and_all_states(client):
    doc, fact, memory = identity_fixture()
    with SessionLocal() as session:
        for status in ("draft", "disabled", "rejected"):
            session.add(CharacterMemory(agent_id="default", content=status, status=status))
        other = CharacterMemory(agent_id="other", content="其他角色", status="active")
        session.add(other); session.commit(); other_id = other.id
    response = client.delete("/api/characters/default/memories")
    assert response.status_code == 200
    assert response.json()["deleted"] == 4
    with SessionLocal() as session:
        assert session.get(CharacterMemory, memory) is None
        assert session.get(CharacterMemory, other_id).content == "其他角色"
        assert session.get(Document, doc) is not None
        assert session.get(WorldFact, fact) is not None
    assert client.delete("/api/characters/default/memories").json()["deleted"] == 0
    assert client.delete("/api/characters/missing/memories").status_code == 404


def test_delete_all_blocks_background_writers(client):
    _, _, memory = identity_fixture()
    app.state.character_tasks["test"] = object()
    try:
        assert client.delete("/api/characters/default/memories").status_code == 409
        with SessionLocal() as session:
            assert session.get(CharacterMemory, memory) is not None
    finally:
        app.state.character_tasks.clear()
