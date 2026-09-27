from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from core.capabilities.mcp import McpClient, _parse_server_config
from core.capabilities.mcp_manager import McpManager

@pytest.mark.asyncio
async def test_import_is_disabled_atomic_and_persisted(tmp_path):
    manager = McpManager(tmp_path / 'mcp.yaml', runtime_enabled=False)
    await manager.startup()
    try:
        await manager.import_users({'one': {'command': 'python', 'enabled': True, 'timeout_ms': 12000}, 'two': {'transport': 'sse', 'url': 'https://example.com/sse'}})
        assert all(not row['enabled'] for row in manager.list_status())
        assert manager.list_status()[0]['timeout_ms'] == 12000
        before = manager.config_file.read_text()
        with pytest.raises(ValueError):
            await manager.import_users({'three': {'command': 'python'}, 'one': {'command': 'python'}})
        assert manager.config_file.read_text() == before
        assert len(manager.list_status()) == 2
        with pytest.raises(ValueError):
            await manager.import_users({'three': {'command': 'python'}, 'bad': {'transport': 'sse', 'url': 'file:///tmp'}})
        assert len(manager.list_status()) == 2
    finally:
        await manager.shutdown()

@pytest.mark.asyncio
async def test_credentials_stay_only_with_same_destination(tmp_path, monkeypatch):
    manager = McpManager(tmp_path / 'mcp.yaml', runtime_enabled=False)
    await manager.startup()
    try:
        raw = {'transport': 'sse', 'url': 'https://example.com/sse', 'headers': {'Authorization': 'secret'}, 'enabled': False}
        await manager.upsert_user('remote', raw)
        seen = []
        async def connect(client):
            seen.append(client.config.headers)
        monkeypatch.setattr(McpClient, 'connect', connect)
        monkeypatch.setattr(McpClient, 'list_tools', AsyncMock(return_value=[]))
        await manager.test_config('remote', {**raw, 'headers': {}})
        await manager.test_config('remote', {**raw, 'headers': {}, 'url': 'https://other.example/sse'})
        assert seen == [{'Authorization': 'secret'}, {}]
        await manager.upsert_user('remote', {**raw, 'headers': {}, 'url': 'https://other.example/sse'})
        assert manager.list_status()[0]['header_keys'] == []
    finally:
        await manager.shutdown()

@pytest.mark.parametrize('timeout', [True, 0, 999, 300001, '30000'])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        _parse_server_config('demo', {'command': 'python', 'timeout_ms': timeout})

@pytest.mark.asyncio
async def test_sse_uses_actual_transport(monkeypatch):
    calls = []
    @asynccontextmanager
    async def transport(url, **kwargs):
        calls.append((url, kwargs))
        yield ('reader', 'writer')
    @asynccontextmanager
    async def session(*args):
        yield SimpleNamespace(initialize=AsyncMock(return_value=SimpleNamespace(serverInfo=SimpleNamespace(model_dump=lambda **k: {'name': 'demo'}))), list_tools=AsyncMock(return_value=SimpleNamespace(tools=[])))
    monkeypatch.setattr('core.capabilities.mcp.sse_client', transport)
    monkeypatch.setattr('core.capabilities.mcp.ClientSession', session)
    client = McpClient(_parse_server_config('demo', {'transport': 'sse', 'url': 'https://example.com/sse', 'timeout_ms': 12000}))
    await client.connect()
    await client.close()
    assert calls[0][1]['timeout'] == 12

def test_import_api_aliases_and_validation(client, tmp_path, monkeypatch):
    monkeypatch.setattr(client.app.state.mcp_manager, "config_file", tmp_path / "api-mcp.yaml")
    response = client.post('/api/mcp-servers/import', json={'mcpServers': {'import-http': {'type': 'http', 'url': 'https://example.com/mcp', 'headers': {'Authorization': 'test-secret'}, 'timeout_ms': 15000}, 'import-sse': {'type': 'sse', 'url': 'https://example.com/sse'}}})
    assert response.status_code == 200
    assert 'test-secret' not in response.text
    imported = {row['name']: row for row in response.json()}
    assert imported['import-http']['transport'] == 'streamable_http'
    assert imported['import-sse']['enabled'] is False
    response = client.post('/api/mcp-servers/import', json={'bad': {'command': 'python', 'headers': {'Authorization': ['test-secret']}}})
    assert response.status_code == 422
    assert 'test-secret' not in response.text
    response = client.post('/api/mcp-servers/import', json={'unsupported': {'command': 'python', 'cwd': '/ignored'}})
    assert response.status_code == 422
    for name in ('import-http', 'import-sse'):
        assert client.delete('/api/mcp-servers/' + name).status_code == 200
