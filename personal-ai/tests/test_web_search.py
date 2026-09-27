import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from core.capabilities.web_search import WebSearchService, public_url, tavily_request
from core.capabilities.skills import allowed_tool_names
from core.execution.tools import TOOLS
from core.settings.runtime import RuntimeSettingsStore
from infrastructure.config import settings


def test_settings_default_key_enable_clear(client):
    assert client.get('/api/settings/web-search').json() == {'enabled': False, 'has_api_key': False, 'provider': 'tavily'}
    assert 'web_search' not in allowed_tool_names([])
    assert client.patch('/api/settings/web-search', json={'enabled': True}).status_code == 422
    saved = client.patch('/api/settings/web-search', json={'api_key': 'private-key'})
    assert saved.status_code == 200 and 'private-key' not in saved.text
    assert saved.json()['enabled'] is False
    assert client.patch('/api/settings/web-search', json={'enabled': True}).json()['enabled'] is True
    assert {'web_search', 'web_read'} <= allowed_tool_names([])
    assert 'private-key' not in client.get('/api/settings').text
    assert client.patch('/api/settings/web-search', json={'clear_api_key': True}).json()['enabled'] is False
    assert 'web_search' not in TOOLS


@pytest.mark.asyncio
async def test_saved_runner_cannot_bypass_disable(tmp_path):
    store = RuntimeSettingsStore(str(tmp_path / 'settings.json'), settings, {})
    store.update('web_search', {'enabled': True, 'api_key': 'secret'})
    service = WebSearchService(store)
    service.sync()
    runner = TOOLS['web_search'].runner
    store.update('web_search', {'enabled': False, 'api_key': 'secret'})
    service.sync()
    with pytest.raises(ValueError, match='已关闭'):
        await runner({'query': 'news'})
    service.close()


def test_migration_preserves_key_but_defaults_off(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'plugin_settings': {'web-search': {'tavily_api_key': 'old-key'}}}))
    store = RuntimeSettingsStore(str(path), settings, {})
    assert store.snapshot()['web_search'] == {'enabled': False, 'api_key': 'old-key'}
    store.update('web_search', {'enabled': False, 'api_key': ''})
    assert RuntimeSettingsStore(str(path), settings, {}).snapshot()['web_search']['api_key'] == ''


def test_connection_does_not_enable_or_save(client, monkeypatch):
    request = AsyncMock(return_value={'results': []})
    monkeypatch.setattr('apps.api.web_search.tavily_request', request)
    response = client.post('/api/settings/web-search/test', json={'api_key': 'test-only'})
    assert response.status_code == 200
    assert client.get('/api/settings/web-search').json()['has_api_key'] is False
    assert request.call_args.args[0] == 'test-only'
    request.side_effect = ValueError('Tavily Key 无效')
    response = client.post('/api/settings/web-search/test', json={'api_key': 'test-only'})
    assert response.status_code == 422 and 'test-only' not in response.text


@pytest.mark.parametrize('url', ['file:///tmp/test', 'http://localhost/a', 'http://127.0.0.1', 'https://10.0.0.1', 'http://[::1]', 'https://user:pass@example.com'])
def test_private_or_credential_urls_rejected(url):
    with pytest.raises(ValueError):
        public_url(url)


@pytest.mark.asyncio
async def test_search_is_bounded_and_returns_real_sources(monkeypatch):
    request = AsyncMock(return_value={'results': [{'title':'source','url':'https://example.com','content':'a'*3000}]*10})
    monkeypatch.setattr('core.capabilities.web_search.tavily_request', request)
    store = SimpleNamespace(snapshot=lambda: {'web_search': {'enabled': True, 'api_key': 'secret'}})
    service = WebSearchService(store)
    result = json.loads(await service.search({'query': 'news'}))
    assert len(result['results']) == 5
    assert len(result['results'][0]['content']) == 1200
    assert result['results'][0]['url'] == 'https://example.com'
    payload = request.call_args.args[2]
    assert payload['search_depth'] == 'basic' and payload['include_answer'] is False
    assert '不写入个人记忆或知识库' in result['notice']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,message', [(401,'Key'),(432,'额度'),(429,'频繁'),(500,'不可用')])
async def test_tavily_errors_mask_response_and_secret(monkeypatch, status, message):
    transport = httpx.MockTransport(lambda req: httpx.Response(status, text='private-key'))
    factory = httpx.AsyncClient
    monkeypatch.setattr('core.capabilities.web_search.httpx.AsyncClient', lambda **kwargs: factory(transport=transport, **kwargs))
    with pytest.raises(ValueError) as error:
        await tavily_request('private-key', 'search', {'query':'test'})
    assert message in str(error.value) and 'private-key' not in str(error.value)

@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [True, False])
async def test_chat_model_receives_optional_web_tools_and_execution_is_audited(monkeypatch, tmp_path, enabled):
    from core.chat.agent import run_chat
    from core.chat.gateway import StreamChunk
    from infrastructure.database import Conversation, AgentRun, ToolRun, SessionLocal
    monkeypatch.setattr(settings, 'memory_enabled', False)
    request = AsyncMock(return_value={'results': [{'title': 'Official', 'url': 'https://example.com', 'content': 'Current release'}]})
    monkeypatch.setattr('core.capabilities.web_search.tavily_request', request)
    store = RuntimeSettingsStore(str(tmp_path / 'runtime.json'), settings, {})
    store.update('web_search', {'enabled': enabled, 'api_key': 'test-only'})
    service = WebSearchService(store)
    service.sync()
    class Provider:
        async def complete(self, messages, temperature=0):
            return ''
        async def stream(self, messages, temperature=0.7, tools=None):
            available = {tool['function']['name'] for tool in tools or []}
            if 'web_search' in available and not any(m['role'] == 'tool' for m in messages):
                yield StreamChunk(tool_calls_delta=[{'index': 0, 'id': 'web-call', 'function': {'name': 'web_search', 'arguments': '{"query":"current release"}'}}])
                yield StreamChunk(finish_reason='tool_calls')
            else:
                yield StreamChunk(text='根据资料回答。', finish_reason='stop')
    with SessionLocal() as session:
        conversation = Conversation(title='web test')
        session.add(conversation)
        session.commit()
        conversation_id = conversation.id
    try:
        events = [event async for event in run_chat(Provider(), conversation_id, '查一下最新版本', skills=[])]
        assert any(event.type == 'run.completed' for event in events)
        assert request.await_count == int(enabled)
        with SessionLocal() as session:
            run = session.query(AgentRun).filter_by(conversation_id=conversation_id).one()
            assert ('web_search' in run.capability_snapshot['tools']) == enabled
            assert session.query(ToolRun).filter_by(run_id=run.id, tool='web_search').count() == int(enabled)
    finally:
        service.close()
