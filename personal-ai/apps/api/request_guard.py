"""本机 API 写请求保护和流式响应缓存控制，不依赖账号。"""
from starlette.requests import Request
from starlette.responses import JSONResponse


class RequestGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/")
        request = Request(scope)
        is_api = path == "/api" or path.startswith("/api/")
        if is_api and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-requested-with") != "PersonalAI":
                await JSONResponse({"detail": "请求缺少同源保护标记"}, 403)(scope, receive, send)
                return

        async def no_cache(message):
            if message["type"] == "http.response.start" and is_api:
                streaming = any(k.lower() == b"content-type" and v.startswith(b"text/event-stream") for k, v in message["headers"])
                message["headers"] = [(k, v) for k, v in message["headers"] if k.lower() != b"cache-control"]
                message["headers"].append((b"cache-control", b"no-store, no-transform" if streaming else b"no-store"))
            await send(message)

        await self.app(scope, receive, no_cache)
