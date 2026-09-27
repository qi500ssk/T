"""Local web search configuration. Secrets never leave the settings store via API."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from apps.api.skills import refresh_skill_runtime
from core.capabilities.web_search import tavily_request

router = APIRouter(prefix='/api/settings/web-search', tags=['settings'])

class WebSettingsBody(BaseModel):
    enabled: bool | None = None
    api_key: str | None = Field(default=None, max_length=2000)
    clear_api_key: bool = False


def public(values):
    return {'enabled': values['enabled'], 'has_api_key': bool(values['api_key']), 'provider': 'tavily'}


@router.get('')
def get_settings(request: Request):
    return public(request.app.state.runtime_settings_store.snapshot()['web_search'])


@router.patch('')
async def update_settings(body: WebSettingsBody, request: Request):
    state = request.app.state
    async with state.runtime_settings_lock:
        values = state.runtime_settings_store.snapshot()['web_search']
        if body.api_key and body.api_key.strip():
            values['api_key'] = body.api_key.strip()
        if body.enabled is not None:
            values['enabled'] = body.enabled
        if body.clear_api_key:
            values.update(api_key='', enabled=False)
        if values['enabled'] and not values['api_key']:
            raise HTTPException(422, '请先填写 Tavily API Key')
        try:
            state.runtime_settings_store.update('web_search', values)
        except OSError:
            raise HTTPException(500, '配置保存失败，请检查本机数据目录') from None
        state.web_search_service.sync()
        refresh_skill_runtime(request.app)
        return public(values)


@router.post('/test')
async def test_connection(body: WebSettingsBody, request: Request):
    key = (body.api_key or '').strip() or request.app.state.runtime_settings_store.snapshot()['web_search']['api_key']
    if not key:
        raise HTTPException(422, '请先填写 Tavily API Key')
    try:
        await tavily_request(key, 'search', {'query': 'Tavily', 'max_results': 1, 'search_depth': 'basic', 'include_answer': False, 'auto_parameters': False})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {'ok': True, 'message': '连接成功，Key 可用于联网搜索；测试不会保存或启用配置。'}
