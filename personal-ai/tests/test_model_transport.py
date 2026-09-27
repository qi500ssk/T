import httpx
import pytest
from core.chat.gateway import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_structured_deepseek_rejects_empty_answer():
    captured=[]
    def respond(request):
        import json
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={"choices":[{"message":{"content":"","reasoning_content":"private"},"finish_reason":"stop"}]})
    provider=OpenAICompatibleProvider('https://example.com','secret','deepseek-v4-flash',5)
    await provider._client.aclose()
    provider._client=httpx.AsyncClient(base_url='https://example.com',transport=httpx.MockTransport(respond))
    provider.structured_output=True
    try:
        with pytest.raises(ValueError,match='没有返回正文'):
            await provider.complete([{'role':'user','content':'write JSON'}])
        assert captured[0]['thinking']=={'type':'disabled'}
        assert captured[0]['response_format']=={'type':'json_object'}
    finally: await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [True, False])
async def test_connect_failure_retries_direct_once(monkeypatch, streaming):
    attempts = []
    def failed(request):
        attempts.append('system')
        raise httpx.ConnectError('')
    def success(request):
        attempts.append('direct')
        if streaming:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices':[{'message':{'content':'OK'}}]})
    provider = OpenAICompatibleProvider('https://example.com/v1', 'secret', 'model', 5)
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(base_url='https://example.com/v1', transport=httpx.MockTransport(failed))
    monkeypatch.setattr(provider, '_direct_client', lambda: httpx.AsyncClient(base_url='https://example.com/v1', transport=httpx.MockTransport(success)))
    try:
        if streaming:
            assert ''.join([c.text async for c in provider.stream([{'role':'user','content':'test'}])]) == 'OK'
        else:
            assert await provider.complete([{'role':'user','content':'test'}]) == 'OK'
        assert attempts == ['system', 'direct']
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_both_connections_fail_with_explanation(monkeypatch):
    def failed(request):
        raise httpx.ConnectError('')
    provider = OpenAICompatibleProvider('https://example.com', 'secret', 'model', 5)
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(base_url='https://example.com', transport=httpx.MockTransport(failed))
    monkeypatch.setattr(provider, '_direct_client', lambda: httpx.AsyncClient(base_url='https://example.com', transport=httpx.MockTransport(failed)))
    try:
        with pytest.raises(RuntimeError, match='无法连接聊天模型服务'):
            await provider.complete([])
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_partial_stream_is_not_replayed(monkeypatch):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError('')
    provider = OpenAICompatibleProvider('https://example.com', 'secret', 'model', 5)
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(base_url='https://example.com', transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=BrokenStream())))
    def forbidden():
        pytest.fail('must not replay a started response')
    monkeypatch.setattr(provider, '_direct_client', forbidden)
    chunks = []
    try:
        with pytest.raises(RuntimeError, match='连接中断'):
            async for chunk in provider.stream([]):
                chunks.append(chunk.text)
        assert chunks == ['partial']
    finally:
        await provider.close()
