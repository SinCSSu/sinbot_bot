"""端点声明与注册表。

把"请求哪个 URL"从业务代码里抽出来，集中在一个映射表里维护::

    ENDPOINTS.add("member.list_by_team", "GET /teams/{team_id}/members")

调用时只写名字和参数，路径参数自动填充、其余参数按方法自动分流到
query（GET/DELETE）或 JSON body（POST/PUT/PATCH）::

    await api_client.request("member.list_by_team", team_id=1, delete_flag="N")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from urllib.parse import quote

from .errors import ApiConfigError

_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# GET/DELETE 的剩余参数走 query，其余方法走 JSON body
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


@dataclass(frozen=True)
class Endpoint:
    """一个外部 API 端点。"""

    name: str
    method: str
    path: str

    def __post_init__(self) -> None:
        method = self.method.strip().upper()
        if method not in _ALLOWED_METHODS:
            raise ApiConfigError(f"端点 {self.name} 的 HTTP 方法非法: {self.method}")
        # 统一成 "/a/b" 形式，方便与 base_url 拼接
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "path", "/" + self.path.strip().strip("/"))

    @property
    def path_params(self) -> frozenset[str]:
        """路径模板中出现的所有 ``{xxx}`` 参数名。"""
        return frozenset(_PATH_PARAM_RE.findall(self.path))

    @property
    def has_body(self) -> bool:
        return self.method in _BODY_METHODS

    def format_path(self, values: Mapping[str, Any]) -> str:
        """用实际参数渲染路径，路径参数做 URL 编码（成员名含中文）。"""
        missing = [p for p in sorted(self.path_params) if values.get(p) is None]
        if missing:
            raise ApiConfigError(
                f"端点 {self.name} 缺少路径参数: {', '.join(missing)}；已收到: {sorted(values)}"
            )

        def _replace(match: re.Match[str]) -> str:
            return quote(str(values[match.group(1)]), safe="")

        return _PATH_PARAM_RE.sub(_replace, self.path)

    @classmethod
    def parse(cls, name: str, spec: str) -> Endpoint:
        """从 ``"GET /teams/{team_id}/members"`` 形式的字符串构造端点。"""
        parts = spec.strip().split(None, 1)
        if len(parts) != 2:
            raise ApiConfigError(f"端点 {name} 的声明格式非法: {spec!r}，应为 'METHOD /path'")
        return cls(name=name, method=parts[0], path=parts[1])

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


class EndpointRegistry:
    """端点注册表：名字 -> :class:`Endpoint`。"""

    def __init__(self, endpoints: Iterator[Endpoint] | None = None) -> None:
        self._endpoints: dict[str, Endpoint] = {}
        for endpoint in endpoints or ():
            self.register(endpoint)

    def register(self, endpoint: Endpoint) -> Endpoint:
        self._endpoints[endpoint.name] = endpoint
        return endpoint

    def add(self, name: str, spec: str) -> Endpoint:
        """以 ``"GET /path"`` 形式注册一个端点。"""
        return self.register(Endpoint.parse(name, spec))

    def get(self, name: str) -> Endpoint:
        try:
            return self._endpoints[name]
        except KeyError:
            raise ApiConfigError(
                f"未注册的端点: {name}；可用端点: {sorted(self._endpoints)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._endpoints)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, str]) -> EndpointRegistry:
        registry = cls()
        for name, spec in mapping.items():
            registry.add(name, spec)
        return registry

    def __contains__(self, name: object) -> bool:
        return name in self._endpoints

    def __len__(self) -> int:
        return len(self._endpoints)

    def __iter__(self) -> Iterator[Endpoint]:
        return iter(self._endpoints.values())

    def __repr__(self) -> str:
        return f"EndpointRegistry({', '.join(self.names())})"
