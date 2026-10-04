"""Fetch public novel sources without silently treating an introduction as a book."""
import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from core.capabilities.web_search import public_url


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.parts = []
        self.hidden = 0
        self.href = ""
        self.anchor = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "a":
            self.href = dict(attrs).get("href", "")
            self.anchor = []
        if tag in {"p", "div", "br", "h1", "h2", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.href:
            self.links.append((self.href, "".join(self.anchor).strip()))
            self.href = ""

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)
            if self.href:
                self.anchor.append(value)


async def fetch(url, max_bytes):
    """Bound response sizes and validate public DNS targets at every redirect."""
    async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False) as client:
        for _ in range(6):
            url = public_url(url)
            host = urlsplit(url).hostname
            addresses = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                raise ValueError("小说来源必须是公开网络地址")
            async with client.stream("GET", url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("小说文件超过上传大小限制")
                raw = bytes(data)
                for encoding in ("utf-8-sig", "gb18030"):
                    try:
                        return raw.decode(encoding), str(response.url), response.headers.get("content-type", "")
                    except UnicodeError:
                        pass
                raise ValueError("小说来源不是可识别的文本文件")
    raise ValueError("小说链接重定向过多")


async def obtain_novel(spec, web, max_bytes):
    candidates = [spec["url"]] if spec.get("url") else []
    if not candidates:
        raw = await web.search({"query": spec["search_query"] + " 全文 完整 TXT 下载"})
        import json
        candidates = [row["url"] for row in json.loads(raw).get("results", [])]
    attempts = []
    for candidate in candidates[:5]:
        try:
            text, url, mime = await fetch(candidate, max_bytes)
            if "html" not in mime and not text.lstrip().lower().startswith(("<!doctype", "<html")):
                if len(text.strip()) >= 10000:
                    return text, url, attempts
                raise ValueError("返回文字过少，不能作为完整长篇小说")
            page = Page()
            page.feed(text)
            downloads = [urljoin(url, href) for href, label in page.links if ".txt" in href.lower() or "plain text" in label.lower()]
            for link in list(dict.fromkeys(downloads))[:5]:
                content, source, kind = await fetch(link, max_bytes)
                if "html" not in kind and len(content.strip()) >= 10000:
                    return content, source, attempts
            # A complete online edition can be read directly; catalogs/intros must not pass.
            content = "\n".join(part.strip() for part in page.parts if part.strip())
            if len(content) >= 50000 and len(page.links) < 80:
                return content, url, attempts
            raise ValueError("找到简介或目录，但未找到可读取的完整正文或 TXT 链接")
        except (ValueError, httpx.HTTPError, OSError) as exc:
            attempts.append({"url": candidate, "reason": str(exc)[:300]})
    raise ValueError("未取得完整小说正文；已尝试：" + "; ".join(f"{item['url']}：{item['reason']}" for item in attempts))
