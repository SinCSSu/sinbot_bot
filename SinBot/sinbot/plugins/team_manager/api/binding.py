"""声明式 API 绑定层（对标 Java 的 Feign / Retrofit 动态代理）。

在 :mod:`.contract` 里用装饰器声明"接口"，由 :class:`ApiFacade` 在运行时把每个
方法绑定成真正的 HTTP 调用::

    class TeamApi:
        @post("/team/createTeam", headers={"X-Group-Number": "{group_number}"})
        async def create(self, team: CreateTeamVo) -> None: ...

        @get("/team/getAvailableTeamsByGroupNumber/{group_number}")
        async def list_available(self, group_number: str) -> list[Team]: ...

    await api.team.create(vo)                      # 方法名/参数都有 IDE 提示与跳转
    teams = await api.team.list_available("12345") # 返回值自动解码成 list[Team]

参数分流规则（``self`` 自动忽略）:

================================  ==========================================
声明                               去向
================================  ==========================================
名字命中 ``{path_param}``           URL 路径（自动 URL 编码）
``Annotated[T, Header("X-Foo")]``  请求头
``Annotated[str, RawBody()]``      原始请求体（原样发送，不做 JSON 编码）
VO / dataclass / pydantic 模型      JSON body（自动 :func:`to_payload`）
其余                               GET/DELETE → query；其余方法 → 并入 body
================================  ==========================================

返回值按返回注解自动解码：``list[Team]`` → 实体列表；``Team | None`` → 单个实体
（空响应返回 ``None``）；``int`` / ``dict`` / ``None`` → 原样返回。
"""

from __future__ import annotations

import dataclasses
import datetime
import functools
import inspect
import re
import typing
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any, Callable, Mapping, get_args, get_origin, get_type_hints
from urllib.parse import quote

from .errors import ApiConfigError

__all__ = [
    "ApiFacade",
    "BoundApi",
    "Endpoint",
    "Header",
    "HttpSpec",
    "RawBody",
    "delete",
    "get",
    "patch",
    "post",
    "put",
]

#: 装饰器挂在函数上的元信息属性名
_SPEC_ATTR = "__http_spec__"

_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

#: GET/DELETE 的剩余参数走 query，其余方法走 JSON body
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

#: 这些类型即便有 ``__dict__`` 也按标量处理，不会被当成请求体对象
_ATOMIC_TYPES = (
    str,
    int,
    float,
    bool,
    bytes,
    bytearray,
    datetime.datetime,
    datetime.date,
    datetime.time,
    Decimal,
    uuid.UUID,
)


# ---------------------------------------------------------------------- 端点


@dataclass(frozen=True)
class Endpoint:
    """一个外部 API 端点：HTTP 方法 + 路径模板。"""

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
        """用实际参数渲染路径，路径参数做 URL 编码（成员名可能含中文）。"""
        missing = [p for p in sorted(self.path_params) if values.get(p) is None]
        if missing:
            raise ApiConfigError(
                f"端点 {self.name} 缺少路径参数: {', '.join(missing)}；已收到: {sorted(values)}"
            )

        def _replace(match: re.Match[str]) -> str:
            return quote(str(values[match.group(1)]), safe="")

        return _PATH_PARAM_RE.sub(_replace, self.path)

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


@dataclass(frozen=True)
class Header:
    """``Annotated[str, Header("X-Group-Number")]``：把该参数放进同名请求头。"""

    name: str


@dataclass(frozen=True)
class RawBody:
    """``Annotated[str, RawBody()]``：该参数原样作为请求体发送。

    用于后端直接处理原始文本（例如把整条群消息交给服务端解析）的场景：
    不做 JSON 编码，请求体就是参数字符串本身。
    """


@dataclass(frozen=True)
class HttpSpec:
    """一个声明式方法携带的全部 HTTP 元信息。"""

    name: str
    method: str
    path: str
    #: 请求头模板，``{xxx}`` 依次从路径参数、请求体字段、其余参数中取值
    headers: Mapping[str, str] = field(default_factory=dict)
    #: 请求体里时间字段的序列化格式，见 :func:`~.codec.to_payload`
    datetime_format: str = "iso"
    #: 由 method + path 派生，构造时校验
    endpoint: Endpoint = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", Endpoint(self.name, self.method, self.path))


F = typing.TypeVar("F", bound=Callable[..., Any])


def _request(method: str) -> Callable[..., Callable[[F], F]]:
    """生成 ``@get`` / ``@post`` / ... 装饰器工厂。"""

    def decorator(
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        datetime_format: str = "iso",
    ) -> Callable[[F], F]:
        def wrap(func: F) -> F:
            spec = HttpSpec(
                name=f"{func.__qualname__}",
                method=method,
                path=path,
                headers=dict(headers or {}),
                datetime_format=datetime_format,
            )
            setattr(func, _SPEC_ATTR, spec)
            return func

        return wrap

    return decorator


get = _request("GET")
post = _request("POST")
put = _request("PUT")
patch = _request("PATCH")
delete = _request("DELETE")


# ---------------------------------------------------------------------- 绑定


def _find_header(hint: Any) -> str | None:
    """从 ``Annotated[T, Header("X-Foo")]`` 里取出请求头名。"""
    if get_origin(hint) is not Annotated:
        return None
    for meta in get_args(hint)[1:]:
        if isinstance(meta, Header):
            return meta.name
    return None


def _is_raw_body(hint: Any) -> bool:
    """判断注解是否是 ``Annotated[T, RawBody()]``（参数原样作为请求体）。"""
    if get_origin(hint) is not Annotated:
        return False
    return any(isinstance(meta, RawBody) for meta in get_args(hint)[1:])


def _is_payload_value(value: Any) -> bool:
    """判断一个参数值是否应整体序列化成请求体（VO / dataclass / pydantic 模型）。"""
    if isinstance(value, _ATOMIC_TYPES):
        return False
    if isinstance(value, (list, tuple, set, frozenset, dict, Mapping)):
        return False
    return hasattr(value, "__dict__") or dataclasses.is_dataclass(value)


def _render_headers(templates: Mapping[str, str], context: Mapping[str, Any]) -> dict[str, str]:
    """渲染请求头模板；引用的参数缺失视为契约错误，值为 None 则跳过该请求头。"""
    rendered: dict[str, str] = {}
    for name, template in templates.items():
        keys = _PATH_PARAM_RE.findall(template)
        missing = [key for key in keys if key not in context]
        if missing:
            raise ApiConfigError(
                f"请求头 {name} 的模板 {template!r} 找不到可用的参数: {missing}；可用: {sorted(context)}"
            )
        if any(context[key] is None for key in keys):
            continue
        rendered[name] = _PATH_PARAM_RE.sub(lambda m: str(context[m.group(1)]), template)
    return rendered


class BoundApi:
    """把 :class:`HttpSpec` 与一个 async 函数绑定成可调用的 HTTP 方法。

    等价于 Java 里 Feign 为接口方法创建的代理实现：调用方只看到普通协程函数。
    """

    def __init__(
        self,
        spec: HttpSpec,
        func: Callable[..., Any],
        client_getter: Callable[[], Any],
    ) -> None:
        self._spec = spec
        self._client_getter = client_getter

        # 去掉 self：绑定后 api.team.create(vo) 拿到的是 BoundApi 实例，不会再自动传实例
        signature = inspect.signature(func)
        self._signature = signature.replace(
            parameters=[p for name, p in signature.parameters.items() if name != "self"]
        )
        hints = get_type_hints(func, include_extras=True)
        self._return_hint = hints.get("return")
        self._header_params = {
            name: header
            for name in self._signature.parameters
            if (header := _find_header(hints.get(name)))
        }
        self._raw_body_param = next(
            (name for name in self._signature.parameters if _is_raw_body(hints.get(name))),
            None,
        )
        functools.update_wrapper(self, func)

    @property
    def spec(self) -> HttpSpec:
        return self._spec

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from .codec import decode_payload, to_payload

        try:
            bound = self._signature.bind(*args, **kwargs)
        except TypeError as exc:
            raise ApiConfigError(f"{self._spec.name} 参数不匹配: {exc}") from None
        bound.apply_defaults()
        values = dict(bound.arguments)

        endpoint = self._spec.endpoint
        # 1) 路径参数
        path_values = {p: values.pop(p) for p in endpoint.path_params if p in values}
        # 2) Annotated[..., Header("X-Foo")] 里的请求头
        headers = {
            self._header_params[name]: values.pop(name) for name in list(values) if name in self._header_params
        }
        # 2.1) Annotated[str, RawBody()]：原样作为请求体，不做 JSON 编码
        raw_body: Any = None
        if self._raw_body_param is not None:
            raw_body = values.pop(self._raw_body_param, None)
        # 3) 剩下的一分为二：VO 对象摊平进请求体，标量走 query 或并入 body
        payload: dict[str, Any] = {}
        plain: dict[str, Any] = {}
        for key, value in values.items():
            if value is None:
                continue
            if _is_payload_value(value):
                payload.update(to_payload(value, datetime_format=self._spec.datetime_format))
            else:
                plain[key] = value

        headers.update(_render_headers(self._spec.headers, {**plain, **path_values, **payload}))

        client = self._client_getter()
        response = await client.request_raw(
            endpoint,
            json=payload or None,
            content=raw_body,
            headers=headers or None,
            **path_values,
            **plain,
        )
        return decode_payload(response.payload, self._return_hint)

    def __repr__(self) -> str:
        return f"<BoundApi {self._spec.endpoint}>"


class ApiFacade:
    """声明式 API 的统一入口（等价于 Java 里注入 Feign 接口）。

    ``client_getter`` 是惰性取值函数而非实例，这样 :func:`~.set_api_client`
    替换全局客户端后无需重新挂载（测试注入假实现同理）::

        api = ApiFacade(get_api_client).mount(team=TeamApi(), member=MemberApi())
        await api.team.create(vo)
    """

    def __init__(self, client_getter: Callable[[], Any]) -> None:
        self._client_getter = client_getter
        self._groups: dict[str, Any] = {}

    def mount(self, **groups: Any) -> ApiFacade:
        """挂载 API 分组，键名即调用时的 ``api.<键名>``。"""
        for alias, group in groups.items():
            self._groups[alias] = _bind_group(group, self._client_getter)
        return self

    def groups(self) -> list[str]:
        return sorted(self._groups)

    def endpoints(self) -> list[str]:
        """列出已挂载的全部端点，形如 ``TeamApi.create``。"""
        return [member.spec.endpoint.name for group in self._groups.values() for member in vars(group).values() if isinstance(member, BoundApi)]

    def __getattr__(self, alias: str) -> Any:
        # __getattr__ 只在常规查找失败时触发；用 __dict__ 避免在 __init__ 完成前递归
        groups = self.__dict__.get("_groups", {})
        try:
            return groups[alias]
        except KeyError:
            raise AttributeError(
                f"未挂载的 API 分组: {alias!r}；可用分组: {sorted(groups)}"
            ) from None

    def __repr__(self) -> str:
        return f"ApiFacade({', '.join(self.groups())})"


def _bind_group(group: Any, client_getter: Callable[[], Any]) -> Any:
    """把分组实例上所有带 :class:`HttpSpec` 的函数就地替换成 :class:`BoundApi`。"""
    bound_count = 0
    for name, member in inspect.getmembers(type(group), inspect.isfunction):
        spec: HttpSpec | None = getattr(member, _SPEC_ATTR, None)
        if spec is None:
            continue
        setattr(group, name, BoundApi(spec, member, client_getter))
        bound_count += 1
    if bound_count == 0:
        raise ApiConfigError(
            f"{type(group).__name__} 没有声明任何端点，检查是否漏了 @get/@post 装饰器"
        )
    return group
