"""
OpenClaw 集群系统 - HTTP 客户端单例

提供全局共享的 aiohttp ClientSession，实现连接复用
"""

import asyncio
from typing import Optional

import aiohttp

from common.logging import get_logger

logger = get_logger(__name__)

_session: Optional[aiohttp.ClientSession] = None
_lock = asyncio.Lock()


async def get_session() -> aiohttp.ClientSession:
    """
    获取全局共享的 HTTP 客户端会话

    Returns:
        aiohttp.ClientSession 实例
    """
    global _session

    if _session is None or _session.closed:
        async with _lock:
            if _session is None or _session.closed:
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=20,
                    ttl_dns_cache=300,
                )
                _session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                )
                logger.debug("HTTP 客户端会话已创建")

    return _session


async def close_session():
    """关闭全局 HTTP 客户端会话"""
    global _session

    if _session and not _session.closed:
        async with _lock:
            if _session and not _session.closed:
                await _session.close()
                _session = None
                logger.debug("HTTP 客户端会话已关闭")


class HttpClient:
    """HTTP 客户端封装类"""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url.rstrip("/")

    async def get(self, path: str, **kwargs) -> aiohttp.ClientResponse:
        session = await get_session()
        url = f"{self.base_url}{path}"
        return await session.get(url, **kwargs)

    async def post(self, path: str, **kwargs) -> aiohttp.ClientResponse:
        session = await get_session()
        url = f"{self.base_url}{path}"
        return await session.post(url, **kwargs)

    async def put(self, path: str, **kwargs) -> aiohttp.ClientResponse:
        session = await get_session()
        url = f"{self.base_url}{path}"
        return await session.put(url, **kwargs)

    async def delete(self, path: str, **kwargs) -> aiohttp.ClientResponse:
        session = await get_session()
        url = f"{self.base_url}{path}"
        return await session.delete(url, **kwargs)
