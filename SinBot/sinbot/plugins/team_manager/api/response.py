"""响应封装与信封解包。

后端普遍返回 ``{"code": 0, "message": "ok", "data": ...}`` 这种信封结构，
业务代码只关心 ``data``，所以在这里统一解包；没有信封（裸 JSON）时整体当 data，
两种形态对调用方透明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import ApiBusinessError

# 未显式配置 success_codes 时，这些业务码视为成功
_DEFAULT_SUCCESS_TOKENS = frozenset({"0", "200", "ok", "success", "true"})


@dataclass(frozen=True)
class EnvelopeSpec:
    """信封字段名的约定，按真实后端契约调整这里即可。"""

    #: 业务码字段名
    code_field: str = "code"
    #: 业务数据字段名
    data_field: str = "data"
    #: 业务消息字段名
    message_field: str = "message"
    #: 视为成功的业务码集合；留空则使用 _DEFAULT_SUCCESS_TOKENS
    success_codes: tuple[Any, ...] = ()

    def is_success(self, code: Any) -> bool:
        # 响应里没有 code 字段时不做业务校验（很多接口成功才返回 body）
        if code is None:
            return True
        normalized = str(code).strip().lower()
        if self.success_codes:
            return normalized in {str(c).strip().lower() for c in self.success_codes}
        return normalized in _DEFAULT_SUCCESS_TOKENS


@dataclass(frozen=True)
class ApiResponse:
    """一次完整调用的结果，保留原始信息便于排查。"""

    status_code: int
    #: 解包后的业务数据（data 字段，或裸 JSON 本体）
    payload: Any = None
    #: 业务码（无信封时为 None）
    code: Any = None
    #: 业务消息（无信封时为 None）
    message: str | None = None
    #: 未解包的原始响应体
    raw: Any = None
    #: 原始响应文本（非 JSON 错误页排查用）
    text: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    method: str = ""
    url: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def unwrap_envelope(raw: Any, spec: EnvelopeSpec | None = None) -> tuple[Any, str | None, Any]:
    """拆信封，返回 ``(code, message, payload)``。

    非 dict 响应体（列表 / 标量）直接整体作为 payload。
    """
    spec = spec or EnvelopeSpec()
    if not isinstance(raw, dict):
        return None, None, raw

    code = raw.get(spec.code_field)
    message = raw.get(spec.message_field)
    payload = raw[spec.data_field] if spec.data_field in raw else raw
    return code, message, payload


def assert_business_ok(
    code: Any,
    message: str | None,
    spec: EnvelopeSpec | None = None,
    *,
    method: str = "",
    url: str = "",
    payload: Any = None,
) -> None:
    """业务码非成功时抛 :class:`ApiBusinessError`。"""
    spec = spec or EnvelopeSpec()
    if not spec.is_success(code):
        raise ApiBusinessError(code, message or "", payload=payload, method=method, url=url)
