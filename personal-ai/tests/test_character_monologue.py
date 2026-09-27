import json
import httpx
import pytest
from core.chat.gateway import OpenAICompatibleProvider

@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [True, False])
async def test_deepseek_requests_disable_extra_thinking(streaming):
    def respond(request):
        payload = json.loads(request.content)
        assert payload['thinking'] == {'type': 'disabled'}
        if streaming:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}]})
    provider = OpenAICompatibleProvider('https://example.com', 'test', 'deepseek-v4-flash', 30)
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(base_url='https://example.com', transport=httpx.MockTransport(respond))
    try:
        if streaming:
            assert ''.join([c.text async for c in provider.stream([])]) == 'OK'
        else:
            assert await provider.complete([]) == 'OK'
    finally:
        await provider.close()
