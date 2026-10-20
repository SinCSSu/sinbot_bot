"""API JSON 与实体/VO 之间的转换。

dao 改造时用它做最后一公里，保证 ``service`` / ``render`` 拿到的还是原来的
``Team`` / ``Member`` / ``Specialization`` 对象，上层零改动::

    # 声明式接口下这两步由 binding.BoundApi 自动完成，一般不用手写
    payload = await api_client.request("member.list_by_team", team_id=team_id)
    members = to_entities(Member, payload)

    body = to_payload(join_team_vo, fields=["team_id", "member_name", ...])
    await api_client.request("member.create", team_id=team_id, json=body)

映射规则：
- 字段名按实体列名匹配，匹配不上再试 camelCase -> snake_case，仍匹配不上则忽略
- 时间字段支持 ISO 字符串（含 ``Z`` 后缀）、``"%Y-%m-%d %H:%M:%S"``、时间戳（秒）
- 数值/字符串按列类型强制转换，转换失败保留原值由上层处理

返回方向由 :func:`decode_payload` 按声明式方法的返回注解自动完成。
"""

from __future__ import annotations

import datetime
import inspect
import re
import types
import typing
from typing import Any, Iterable, Mapping, TypeVar, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect

from .errors import ApiDecodeError

T = TypeVar("T")

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower()


def _parse_datetime(value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time.min)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.datetime.fromtimestamp(value)
    if not isinstance(value, str):
        raise ApiDecodeError(f"无法解析为时间: {value!r}")

    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ApiDecodeError(f"无法解析为时间: {value!r}")


def _column_python_types(entity_cls: type) -> dict[str, Any]:
    """实体列名 -> 该列的 Python 类型。"""
    result: dict[str, Any] = {}
    for key, column in sa_inspect(entity_cls).columns.items():
        try:
            result[key] = column.type.python_type
        except NotImplementedError:  # pragma: no cover  # 极少数自定义类型
            result[key] = None
    return result


def _coerce(value: Any, python_type: Any) -> Any:
    if value is None or python_type is None:
        return value
    if python_type is datetime.datetime:
        return _parse_datetime(value)
    if python_type is bool and isinstance(value, str):
        return value.strip().lower() in {"1", "true", "y", "yes"}
    try:
        return python_type(value)
    except (TypeError, ValueError):
        return value


def to_entity(
    entity_cls: type[T],
    payload: Mapping[str, Any] | None,
    *,
    field_map: Mapping[str, str] | None = None,
    ignore_unknown: bool = True,
) -> T:
    """把一个 JSON 对象转成实体实例（未提供的字段保持 None）。"""
    if payload is None:
        raise ApiDecodeError(f"{getattr(entity_cls, '__name__', entity_cls)} 的响应数据为空")
    if not isinstance(payload, Mapping):
        raise ApiDecodeError(
            f"{getattr(entity_cls, '__name__', entity_cls)} 期望 JSON 对象，实际: {type(payload).__name__}"
        )

    types = _column_python_types(entity_cls)
    field_map = field_map or {}
    kwargs: dict[str, Any] = {}

    for key, value in payload.items():
        target = field_map.get(key, key)
        if target not in types:
            target = _camel_to_snake(target)
        if target not in types:
            if ignore_unknown:
                continue
            raise ApiDecodeError(
                f"{getattr(entity_cls, '__name__', entity_cls)} 无字段 {key!r}"
            )
        kwargs[target] = _coerce(value, types[target])

    return entity_cls(**kwargs)


def to_entities(
    entity_cls: type[T],
    payload: Any,
    *,
    field_map: Mapping[str, str] | None = None,
    ignore_unknown: bool = True,
) -> list[T]:
    """把一个 JSON 数组转成实体列表；空响应返回空列表。"""
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ApiDecodeError(
            f"{getattr(entity_cls, '__name__', entity_cls)} 期望 JSON 数组，实际: {type(payload).__name__}"
        )
    return [
        to_entity(entity_cls, item, field_map=field_map, ignore_unknown=ignore_unknown)
        for item in payload
    ]


def to_payload(
    source: Any,
    *,
    fields: Iterable[str] | None = None,
    exclude: Iterable[str] = (),
    datetime_format: str = "iso",
) -> dict[str, Any]:
    """把实体 / VO / 字典转成可发送的请求体。

    ORM 实体按列取值，普通对象与字典按现有属性取值；时间统一序列化为 ISO 字符串。
    """
    if source is None:
        return {}

    excluded = set(exclude)
    wanted = list(fields) if fields is not None else None

    if isinstance(source, Mapping):
        keys = wanted or list(source)
        raw_items = {key: source.get(key) for key in keys}
    else:
        try:
            column_keys = list(sa_inspect(type(source)).columns.keys())
        except Exception:  # noqa: BLE001  # 不是 ORM 实体，退化为 __dict__
            column_keys = list(vars(source).keys())
        keys = wanted or column_keys
        raw_items = {key: getattr(source, key, None) for key in keys}

    result: dict[str, Any] = {}
    for key, value in raw_items.items():
        if key in excluded or value is None:
            continue
        if isinstance(value, datetime.datetime):
            result[key] = value.isoformat() if datetime_format == "iso" else value.strftime(datetime_format)
        elif isinstance(value, datetime.date):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


# ------------------------------------------------------------------ 响应解码


def _is_entity(candidate: Any) -> bool:
    """判断注解类型是否是 SQLAlchemy ORM 实体（即能按列名解码）。"""
    if not inspect.isclass(candidate):
        return False
    try:
        sa_inspect(candidate).mapper
    except Exception:  # noqa: BLE001  # 未映射的类会抛 NoInspectionAvailable 等
        return False
    return True


def _is_pydantic_model(candidate: Any) -> bool:
    """判断注解类型是否是 pydantic 模型（VO 这类非 ORM 类型靠它按注解解码）。"""
    return inspect.isclass(candidate) and issubclass(candidate, BaseModel)


def decode_payload(payload: Any, hint: Any) -> Any:
    """按声明式方法的返回注解把响应数据解码成实体。

    ============================  ============================================
    返回注解                       结果
    ============================  ============================================
    ``list[Team]``                :func:`to_entities`，空响应返回 ``[]``
    ``Team \| None``               :func:`to_entity`，空响应返回 ``None``
    ``list[TeamInfoVo]``          逐个 ``model_validate``，空响应返回 ``[]``
    ``TeamInfoVo``                ``model_validate``，空响应返回 ``None``
    ``int`` / ``dict`` / ``None``  原样返回
    ============================  ============================================

    pydantic 模型（VO）与 ORM 实体走不同的解码路径：前者按字段注解，
    后者按数据库列名。
    """
    if hint is None or hint is Any:
        return payload

    origin = get_origin(hint)

    # Optional[Team] / Team | None：去掉 None 后按唯一剩余类型递归
    if origin in (typing.Union, types.UnionType):
        args = [arg for arg in get_args(hint) if arg is not type(None)]
        return decode_payload(payload, args[0]) if len(args) == 1 else payload

    if origin in (list, tuple, set, frozenset):
        args = [arg for arg in get_args(hint) if arg is not Ellipsis]
        item = args[0] if args else Any
        if _is_entity(item):
            return to_entities(item, payload)
        if _is_pydantic_model(item):
            return [item.model_validate(entry) for entry in payload or []]
        return list(payload or [])

    if _is_entity(hint):
        return to_entity(hint, payload) if payload is not None else None

    if _is_pydantic_model(hint):
        return hint.model_validate(payload) if payload is not None else None

    return payload
