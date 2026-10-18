"""外部 API 调用框架。

对外只需要三个入口::

    from ..api import get_api_client
    from ..api.codec import to_entities, to_payload

    client = get_api_client()
    payload = await client.request("member.list_by_team", team_id=team_id)
    members = to_entities(Member, payload)

生命周期由插件在 nonebot 启动时托管（见 ``plugins/team_manager/__init__.py``）；
单元测试里可以用 :func:`set_api_client` 注入假实现。
"""

from __future__ import annotations

from nonebot import logger

from .client import ApiClient
from .endpoint import Endpoint, EndpointRegistry
from .errors import (
    ApiBusinessError,
    ApiConfigError,
    ApiDecodeError,
    ApiError,
    ApiStatusError,
    ApiTimeoutError,
    ApiTransportError,
)
from .response import ApiResponse, EnvelopeSpec

__all__ = [
    "ApiClient",
    "ApiResponse",
    "ApiError",
    "ApiConfigError",
    "ApiTransportError",
    "ApiTimeoutError",
    "ApiStatusError",
    "ApiBusinessError",
    "ApiDecodeError",
    "Endpoint",
    "EndpointRegistry",
    "EnvelopeSpec",
    "get_api_client",
    "init_api_client",
    "set_api_client",
    "shutdown_api_client",
]

_client: ApiClient | None = None


def init_api_client(config: object | None = None) -> ApiClient:
    """按插件配置创建全局客户端（nonebot on_startup 回调）。"""
    global _client

    if config is None:
        from nonebot import get_plugin_config

        from ..config import Config

        config = get_plugin_config(Config).team_manager

    if _client is not None:
        return _client

    base_url = getattr(config, "api_base_url", "")
    if not base_url:
        logger.warning("[api] 未配置 TEAM_MANAGER__API_BASE_URL，外部 API 调用将全部失败")

    success_codes = tuple(
        item.strip() for item in str(getattr(config, "api_success_codes", "") or "").split(",") if item.strip()
    )

    _client = ApiClient(
        base_url=base_url,
        api_key=getattr(config, "api_keys", "") or "",
        api_key_header=getattr(config, "api_key_header", "") or "X-API-Key",
        timeout=float(getattr(config, "api_timeout", 10.0)),
        max_retries=int(getattr(config, "api_max_retries", 2)),
        backoff=float(getattr(config, "api_retry_backoff", 0.5)),
        envelope=EnvelopeSpec(success_codes=success_codes),
    )
    logger.info(f"[api] 外部 API 客户端已初始化: {base_url}")
    return _client


def get_api_client() -> ApiClient:
    """获取全局客户端；未初始化时抛 :class:`ApiConfigError`。"""
    if _client is None:
        raise ApiConfigError("ApiClient 尚未初始化，请检查插件启动流程或手动调用 init_api_client()")
    return _client


def set_api_client(client: ApiClient | None) -> None:
    """替换全局客户端（测试注入 / 热更新配置用）。"""
    global _client
    _client = client


async def shutdown_api_client() -> None:
    """关闭底层连接池（nonebot on_shutdown 回调）。"""
    global _client
    if _client is None:
        return
    await _client.aclose()
    _client = None
    logger.info("[api] 外部 API 客户端已关闭")
