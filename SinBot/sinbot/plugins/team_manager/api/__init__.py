"""外部 API 调用框架。

业务代码只需要一个入口——门面对象 :data:`api`::

    from ..api import api

    await api.team.create(create_team_vo)                    # 开团
    teams = await api.team.list_available(group_number="12") # 自动解码成 list[Team]

一切 HTTP 细节（URL、method、请求头、参数分流、返回值解码）都在
:mod:`.contract` 里声明，调用点看不到；新增接口只需在 contract 里加一个带
``@get`` / ``@post`` 的方法。

需要绕开声明式层做临时调试时，仍可拿到底层客户端::

    from ..api import get_api_client

    raw = await get_api_client().request_raw(endpoint, params={...})

生命周期由插件在 nonebot 启动时托管（见 ``plugins/team_manager/__init__.py``）；
单元测试里可以用 :func:`set_api_client` 注入假实现，门面会自动跟随。
"""

from __future__ import annotations

from nonebot import logger

from ..config import parse_api_keys
from .binding import ApiFacade, BoundApi, Endpoint, Header, RawBody, delete, get, patch, post, put
from .client import ApiClient
from .contract import MemberApi, SpecApi, TeamApi
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
    # 门面（业务代码主要用它）
    "api",
    "ApiFacade",
    # 声明式契约
    "TeamApi",
    "MemberApi",
    "SpecApi",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "Header",
    "RawBody",
    "BoundApi",
    # 底层（调试 / 自定义用）
    "ApiClient",
    "ApiResponse",
    "Endpoint",
    "EnvelopeSpec",
    # 异常
    "ApiError",
    "ApiConfigError",
    "ApiTransportError",
    "ApiTimeoutError",
    "ApiStatusError",
    "ApiBusinessError",
    "ApiDecodeError",
    # 生命周期
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

    api_keys = parse_api_keys(getattr(config, "api_keys", "") or "")
    if base_url and not api_keys:
        logger.warning(
            "[api] 未配置 API Key（Nacos 里是 team_manager.api-keys），"
            "请求将不携带认证头，后端可能返回 401/403"
        )
    elif len(api_keys) > 1:
        logger.info(f"[api] 配置了 {len(api_keys)} 个 API Key，请求头只携带第一个")

    success_codes = tuple(
        item.strip() for item in str(getattr(config, "api_success_codes", "") or "").split(",") if item.strip()
    )

    _client = ApiClient(
        base_url=base_url,
        api_key=api_keys[0] if api_keys else "",
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
    """替换全局客户端（测试注入 / 热更新配置用）。

    门面 :data:`api` 每次调用时才取值，所以替换后无需重新挂载。
    """
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


#: 声明式 API 门面：``api.<分组>.<方法>(...)``
api = ApiFacade(get_api_client).mount(
    team=TeamApi(),
    member=MemberApi(),
    spec=SpecApi(),
)
