"""外部 API 调用异常体系。

调用方（未来的 dao）只需要围绕 :class:`ApiError` 做兜底，
需要区分"能不能重试"时看 :attr:`ApiError.retryable`::

    try:
        data = await api_client.request("member.list_by_team", team_id=team_id)
    except ApiError as e:
        if e.retryable:
            ...  # 交给上层重试或提示稍后再试
        else:
            ...  # 参数/业务问题，重试没意义
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """所有外部 API 异常的基类。"""

    #: 该异常是否值得重试。仅传输层失败与 5xx/429 为 True。
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ApiConfigError(ApiError):
    """配置缺失、端点未注册、路径参数缺失等编码期问题。"""


class ApiTransportError(ApiError):
    """传输层失败：连接不上、DNS 失败、TLS 错误等。可重试。"""

    retryable = True


class ApiTimeoutError(ApiTransportError):
    """请求超时。可重试（注意：写操作重试前需确认接口幂等）。"""

    retryable = True


class ApiStatusError(ApiError):
    """服务端返回了非 2xx 的 HTTP 状态码。"""

    def __init__(
        self,
        status_code: int,
        body: str = "",
        *,
        method: str = "",
        url: str = "",
        retryable: bool | None = None,
    ) -> None:
        super().__init__(f"{method} {url} 返回 HTTP {status_code}")
        self.status_code = status_code
        self.body = body
        self.method = method
        self.url = url
        # 5xx 与 429 视为服务端临时故障，可以退避重试；其余（4xx）重试无意义
        self.retryable = retryable if retryable is not None else (
            status_code >= 500 or status_code == 429
        )


class ApiBusinessError(ApiError):
    """HTTP 成功，但响应信封中的业务码表示失败。"""

    def __init__(
        self,
        code: Any = None,
        message: str = "",
        *,
        payload: Any = None,
        method: str = "",
        url: str = "",
    ) -> None:
        super().__init__(f"{method} {url} 业务失败: code={code} message={message}")
        self.code = code
        self.business_message = message
        self.payload = payload
        self.method = method
        self.url = url


class ApiDecodeError(ApiError):
    """响应体不是合法 JSON，或结构与预期不符（无法映射成实体）。"""
