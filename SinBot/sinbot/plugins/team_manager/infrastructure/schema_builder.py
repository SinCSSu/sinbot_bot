"""根据函数签名与 docstring 自动生成 OpenAI 工具 schema。"""

from __future__ import annotations

import inspect
import re
import typing
from typing import Any, Callable

# 基础类型到 JSON Schema 类型的映射
_SIMPLE_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

_NONE_TYPE = type(None)

_ARGS_PARAM_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")


def _is_optional(annotation: Any) -> bool:
    """判断注解是否为可选类型（含 None 分支）。"""
    return any(arg is _NONE_TYPE for arg in typing.get_args(annotation))


def _resolve_literal(annotation: Any) -> dict[str, Any] | None:
    """将 Literal 注解映射为枚举 schema。"""
    values = [
        arg
        for arg in typing.get_args(annotation)
        if isinstance(arg, (str, int, float, bool))
    ]
    if not values:
        return None
    json_type = _SIMPLE_TYPE_MAP.get(type(values[0]))
    if json_type is None:
        return None
    return {"type": json_type, "enum": values}


def _resolve_optional(args: tuple[Any, ...]) -> dict[str, Any] | None:
    """将可选联合映射为 nullable schema。"""
    non_none = [arg for arg in args if arg is not _NONE_TYPE]
    if len(non_none) != 1:
        return None
    base = _resolve_type(non_none[0])
    if base is None:
        return None
    return {"anyOf": [base, {"type": "null"}]}


def _resolve_list(args: tuple[Any, ...]) -> dict[str, Any]:
    """将 list 注解映射为数组 schema。"""
    schema: dict[str, Any] = {"type": "array"}
    if not args:
        return schema
    item = _resolve_type(args[0])
    if item is not None:
        schema["items"] = item
    return schema


def _resolve_type(annotation: Any) -> dict[str, Any] | None:  # noqa: PLR0911
    """将类型注解映射为 JSON Schema 片段，无法映射时返回 None。"""
    if annotation is inspect.Parameter.empty or annotation is _NONE_TYPE:
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return _resolve_literal(annotation)
    args = typing.get_args(annotation)
    if args and any(arg is _NONE_TYPE for arg in args):
        return _resolve_optional(args)
    if origin is list:
        return _resolve_list(args)
    if origin is dict:
        return {"type": "object"}
    if isinstance(annotation, type):
        json_type = _SIMPLE_TYPE_MAP.get(annotation)
        if json_type is not None:
            return {"type": json_type}
    return None


def _flush_param(
    current_param: str | None,
    buffer: list[str],
    param_descriptions: dict[str, str],
) -> None:
    """将累积的参数描述写入结果。"""
    if current_param and buffer:
        param_descriptions[current_param] = " ".join(buffer).strip()


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """解析函数描述与参数描述（Google style 的 Args 段）。"""
    if not doc:
        return "", {}
    description_lines: list[str] = []
    param_descriptions: dict[str, str] = {}
    in_args = False
    current_param: str | None = None
    buffer: list[str] = []
    for line in inspect.cleandoc(doc).splitlines():
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            continue
        if not in_args:
            if stripped:
                description_lines.append(stripped)
            continue
        if not stripped:
            continue
        match = _ARGS_PARAM_RE.match(stripped)
        if match:
            _flush_param(current_param, buffer, param_descriptions)
            current_param, first = match.groups()
            buffer = [first]
        elif current_param is not None:
            buffer.append(stripped)
    _flush_param(current_param, buffer, param_descriptions)
    return "\n".join(description_lines).strip(), param_descriptions


def build_tool_schema(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """根据函数签名与 docstring 构建 OpenAI 工具 schema。

    Args:
        func: 要注册的可调用对象
        name: 工具名，默认取函数名
        description: 工具描述，默认取 docstring 摘要

    Returns:
        符合 OpenAI tools 参数格式的 schema 字典
    """
    tool_name = name or func.__name__
    doc_description, param_descriptions = _parse_docstring(inspect.getdoc(func))
    tool_description = description or doc_description or f"调用 {tool_name} 工具"
    try:
        type_hints = typing.get_type_hints(func)
    except (NameError, TypeError):
        type_hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in inspect.signature(func).parameters.values():
        if param.name in ("self", "cls") or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation = type_hints.get(param.name, param.annotation)
        prop = _resolve_type(annotation) or {}
        param_description = param_descriptions.get(param.name)
        if param_description:
            prop["description"] = param_description
        elif "description" not in prop:
            prop["description"] = f"参数 {param.name}"
        if param.default is not inspect.Parameter.empty and not _is_optional(
            annotation,
        ):
            prop["default"] = param.default
        properties[param.name] = prop
        # 必填性仅取决于是否声明默认值；`X | None` 无默认值仍为必填（允许传 null）
        if param.default is inspect.Parameter.empty:
            required.append(param.name)

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_description,
            "parameters": parameters,
        },
    }
