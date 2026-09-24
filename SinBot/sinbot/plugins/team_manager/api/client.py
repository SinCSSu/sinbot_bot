"""外部 API 客户端。

对 dao 暴露的最小面::

    # 走注册表里的命名端点
    teams = await api_client.request("team.list_available", group_number="12345")
    # 直接传 Endpoint 也行（临时调试用）
    raw = await api_client.request_raw("member.create", team_id=1, json={...})

设计要点：
- 单例由 :mod:`api` 包在 nonebot 启动时创建，底层复用一个 ``httpx.AsyncClient``（连接池）
- 静态 API Key 走请求头，头名可配
- 只对传输层异常、超时、5xx/429 做指数退避重试，4xx 与业务失败立即抛出
- 成功返回解包后的 ``data``，需要原始响应时用 ``request_raw``
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

import httpx
from nonebot import logger

from .endpoint import Endpoint, EndpointRegistry
from .errors import (
    ApiConfigError,
    ApiDecodeError,
    ApiStatusError,
    ApiTimeoutError,
    ApiTransportError,
)
from .response import ApiResponse, EnvelopeSpec, assert_business_ok, unwrap_envelope


class ApiClient:
    """带认证、超时、重试、信封解包的异步 HTTP 客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        api_key_header: str = "X-API-Key",
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        extra_headers: Mapping[str, str] | None = None,
        envelope: EnvelopeSpec | None = None,
        registry: EndpointRegistry | None = None,
    ) -> None:
        # 允许空 base_url 构造（迁移过渡期后端地址可能还没配），真正调用时才报错，
        # 避免配置缺失直接把 bot 启动流程打断
        self._base_url = base_url.rstrip("/") + "/" if base_url else ""
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._backoff = backoff
        self._envelope = envelope or EnvelopeSpec()
        self._registry = registry

        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers[api_key_header] = api_key
        if extra_headers:
            headers.update(extra_headers)
        self._headers = headers

        self._client = httpx.AsyncClient(
            base_url=self._base_url or "http://api-base-url-unconfigured.invalid",
            headers=self._headers,
            timeout=timeout,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ 公开 API

    async def request(
        self,
        endpoint: str | Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """调用端点并返回解包后的业务数据。"""
        response = await self.request_raw(
            endpoint, params=params, json=json, headers=headers, timeout=timeout, **kwargs
        )
        return response.payload

    async def request_raw(
        self,
        endpoint: str | Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> ApiResponse:
        """同 :meth:`request`，但返回完整的 :class:`ApiResponse`。"""
        ep = self._resolve(endpoint)
        path_values, extra = self._split_kwargs(ep, kwargs)

        query = dict(params or {})
        body = dict(json or {})
        for key, value in extra.items():
            if value is None:
                continue
            (body if ep.has_body else query)[key] = value

        return await self._send(
            ep,
            path=ep.format_path(path_values),
            params=query or None,
            json=body or None,
            headers=headers,
            timeout=timeout,
        )

    async def get(self, endpoint: str | Endpoint, **kwargs: Any) -> Any:
        return await self.request(endpoint, **kwargs)

    async def post(self, endpoint: str | Endpoint, json: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return await self.request(endpoint, json=json, **kwargs)

    async def put(self, endpoint: str | Endpoint, json: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return await self.request(endpoint, json=json, **kwargs)

    async def patch(self, endpoint: str | Endpoint, json: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return await self.request(endpoint, json=json, **kwargs)

    async def delete(self, endpoint: str | Endpoint, **kwargs: Any) -> Any:
        return await self.request(endpoint, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ 内部实现

    def _resolve(self, endpoint: str | Endpoint) -> Endpoint:
        if isinstance(endpoint, Endpoint):
            return endpoint
        if self._registry is None:
            from .registry import DEFAULT_ENDPOINTS

            self._registry = DEFAULT_ENDPOINTS
        return self._registry.get(endpoint)

    @staticmethod
    def _split_kwargs(
        endpoint: Endpoint, kwargs: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """按端点声明把关键字参数拆成「路径参数」与「其余参数」。"""
        path_params = endpoint.path_params
        path_values: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in kwargs.items():
            if key in path_params:
                path_values[key] = value
            else:
                extra[key] = value
        return path_values, extra

    async def _send(
        self,
        endpoint: Endpoint,
        *,
        path: str,
        params: Mapping[str, Any] | None,
        json: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
        timeout: float | None,
    ) -> ApiResponse:
        if not self._base_url:
            raise ApiConfigError("api_base_url 未配置，无法调用外部 API")

        request_headers = {**self._headers, **(headers or {})}
        attempts = self._max_retries + 1
        error: Exception | None = None

        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                response = await self._client.request(
                    endpoint.method,
                    path.lstrip("/"),
                    params=params,
                    json=json,
                    headers=request_headers,
                    timeout=timeout if timeout is not None else self._timeout,
                )
            except httpx.TimeoutException as exc:
                error = ApiTimeoutError(f"{endpoint.name} 请求超时: {exc}")
            except httpx.HTTPError as exc:
                error = ApiTransportError(f"{endpoint.name} 请求失败: {exc}")
            else:
                api_response = self._to_api_response(endpoint, response, path)
                error = self._validate(api_response)
                if error is None:
                    logger.debug(
                        f"[api] {endpoint.method} {path} -> {api_response.status_code} "
                        f"耗时 {time.perf_counter() - started:.3f}s"
                    )
                    return api_response

            retryable = getattr(error, "retryable", False)
            if retryable and attempt < attempts - 1:
                delay = self._backoff * (2**attempt)
                logger.warning(
                    f"[api] {endpoint.name} 第 {attempt + 1}/{attempts} 次失败: {error}；"
                    f"{delay:.2f}s 后重试"
                )
                await asyncio.sleep(delay)
                continue

            logger.error(f"[api] {endpoint.name} 调用失败: {error}")
            raise error

        raise error  # pragma: no cover  # 循环必然 return 或 raise

    def _to_api_response(self, endpoint: Endpoint, response: httpx.Response, path: str) -> ApiResponse:
        try:
            raw = response.json()
        except ValueError:
            raw = None

        # 只有 2xx 才要求响应体是 JSON：错误页（HTML/纯文本）应走 ApiStatusError 并允许重试
        if response.is_success and raw is None and response.text:
            raise ApiDecodeError(f"{endpoint.name} 响应不是合法 JSON: {response.text[:200]!r}")

        code, message, payload = unwrap_envelope(raw, self._envelope)
        return ApiResponse(
            status_code=response.status_code,
            payload=payload,
            code=code,
            message=message,
            raw=raw,
            text=response.text,
            headers=dict(response.headers),
            method=endpoint.method,
            url=str(response.request.url),
        )

    def _validate(self, response: ApiResponse) -> Exception | None:
        """HTTP 与业务码校验，返回 None 表示成功。"""
        if not response.ok:
            return ApiStatusError(
                response.status_code,
                (response.text or str(response.raw))[:500],
                method=response.method,
                url=response.url,
            )
        try:
            assert_business_ok(
                response.code,
                response.message,
                self._envelope,
                method=response.method,
                url=response.url,
                payload=response.payload,
            )
        except Exception as exc:  # noqa: BLE001  # 转成本方法的返回值语义
            return exc
        return None
