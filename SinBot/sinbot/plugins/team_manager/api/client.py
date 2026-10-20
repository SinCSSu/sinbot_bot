"""外部 API 客户端（传输层）。

业务代码一般经由 :mod:`.binding` 的声明式门面 :data:`~.api` 间接触达这里；
只有临时调试、或者想绕开 contract 直接发请求时才用本模块::

    from ..api import get_api_client
    from ..api.binding import Endpoint

    raw = await get_api_client().request_raw(Endpoint("tmp", "GET", "/ping"))

设计要点：
- 单例由 :mod:`api` 包在 nonebot 启动时创建，底层复用一个 ``httpx.AsyncClient``（连接池）
- 静态 API Key 走请求头，头名可配
- 只对传输层异常、超时、5xx/429 做指数退避重试，4xx 与业务失败立即抛出
- 成功返回解包后的 ``data``，需要原始响应时用 ``request_raw``
- 端点一律传 :class:`~.binding.Endpoint` 对象；构造时注入 ``registry`` 才支持字符串名
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

import httpx
from nonebot import logger

from .binding import Endpoint
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
        registry: Any | None = None,
    ) -> None:
        """``registry`` 为可选的 ``EndpointRegistry``（仅用于兼容按字符串名取端点）。"""
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
        content: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """调用端点并返回解包后的业务数据。"""
        response = await self.request_raw(
            endpoint,
            params=params,
            json=json,
            content=content,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )
        return response.payload

    async def request_raw(
        self,
        endpoint: str | Endpoint,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        content: str | bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> ApiResponse:
        """同 :meth:`request`，但返回完整的 :class:`ApiResponse`。

        ``content`` 用于「原样发送请求体」的场景（不做 JSON 编码），此时不能再传
        ``json`` 或额外的请求体字段。
        """
        ep = self._resolve(endpoint)
        path_values, extra = self._split_kwargs(ep, kwargs)

        query = dict(params or {})
        body = dict(json or {})
        for key, value in extra.items():
            if value is None:
                continue
            if content is not None and ep.has_body:
                raise ApiConfigError(
                    f"{ep.name} 已指定原始请求体 content，不能再附带请求体字段: {key}"
                )
            (body if ep.has_body else query)[key] = value

        if content is not None:
            if not ep.has_body:
                raise ApiConfigError(f"{ep.name} 是 {ep.method} 请求，不支持原始请求体 content")
            if body:
                raise ApiConfigError(
                    f"{ep.name} 的 content 与 json 只能二选一，已收到 json 字段: {sorted(body)}"
                )

        return await self._send(
            ep,
            path=ep.format_path(path_values),
            params=query or None,
            json=body or None,
            content=content,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ 内部实现

    _SENSITIVE_HEADER_PARTS = ("authorization", "key", "token", "secret", "cookie")

    def _build_url(self, path: str, params: Mapping[str, Any] | None) -> str:
        """拼出用于日志的完整 URL（含查询串）。"""
        url = str(self._client.base_url.join(path.lstrip("/")))
        if params:
            query = str(httpx.QueryParams(params))
            if query:
                url = f"{url}{'&' if '?' in url else '?'}{query}"
        return url

    def _mask_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        """日志用：把认证类请求头的值打码，避免密钥落盘。"""
        masked: dict[str, str] = {}
        for name, value in headers.items():
            lowered = name.lower()
            if any(part in lowered for part in self._SENSITIVE_HEADER_PARTS):
                masked[name] = "***" if value else ""
            else:
                masked[name] = value
        return masked

    def _resolve(self, endpoint: str | Endpoint) -> Endpoint:
        if isinstance(endpoint, Endpoint):
            return endpoint
        if self._registry is not None:
            return self._registry.get(endpoint)
        raise ApiConfigError(
            f"端点名 {endpoint!r} 无法解析：请传 Endpoint 对象，"
            f"或改用 api/contract.py 中声明的接口（api.<分组>.<方法>）"
        )

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
        content: str | bytes | None,
        headers: Mapping[str, str] | None,
        timeout: float | None,
    ) -> ApiResponse:
        if not self._base_url:
            raise ApiConfigError("api_base_url 未配置，无法调用外部 API")

        request_headers = {**self._headers, **(headers or {})}
        # 原始请求体默认按文本发送；要别的 Content-Type 在 headers 里显式覆盖
        if content is not None and not any(
            key.lower() == "content-type" for key in request_headers
        ):
            request_headers["Content-Type"] = "text/plain; charset=utf-8"
        attempts = self._max_retries + 1
        error: Exception | None = None
        url = self._build_url(path, params)

        for attempt in range(attempts):
            started = time.perf_counter()
            logger.debug(
                f"[api] 出站请求 {endpoint.method} {url} "
                f"(第 {attempt + 1}/{attempts} 次)"
            )
            logger.debug(f"[api] 请求头: {self._mask_headers(request_headers)}")
            logger.debug(
                f"[api] 请求体: {content if content is not None else (dict(json) if json else None)}"
            )
            try:
                response = await self._client.request(
                    endpoint.method,
                    path.lstrip("/"),
                    params=params,
                    json=json,
                    content=content,
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
