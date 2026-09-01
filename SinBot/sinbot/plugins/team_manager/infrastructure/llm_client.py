"""基于 OpenAI SDK 的 LLM 客户端，支持工具注册与自动工具调用。"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, cast

from nonebot import logger
from openai import AsyncOpenAI

from sinbot.plugins.team_manager.infrastructure.schema_builder import build_tool_schema

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletionMessage,
        ChatCompletionMessageParam,
        ChatCompletionMessageToolCall,
        ChatCompletionToolParam,
    )

# api_key 为空时的占位符，避免 SDK 参数校验报错
_PLACEHOLDER_API_KEY = "EMPTY"


@dataclass
class ToolResult:
    """一次工具调用的执行结果（原始返回值，未字符串化）。"""

    name: str
    tool_call_id: str
    value: Any


@dataclass
class LLMChatResult:
    """一次 chat 调用的封装结果。"""

    reply: str
    messages: list[ChatCompletionMessageParam]
    tool_call_turns: int
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class ToolDefinition:
    """已注册工具的运行时定义。"""

    func: Callable[..., Any]
    schema: dict[str, Any]


class LLMClient:
    """LLM 客户端：注册可调用工具，并与模型进行带自动工具调用的对话。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        model: str,
        max_turns: int = 10,
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        self._tools: dict[str, ToolDefinition] = {}
        self._client = AsyncOpenAI(
            api_key=api_key or _PLACEHOLDER_API_KEY,
            base_url=base_url,
        )

    def register(
        self,
        name: str | None = None,
        *,
        description: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """装饰器形式注册可调用函数。

        Args:
            name: 工具名，缺省时取函数名
            description: 工具描述，缺省时取函数 docstring 摘要

        Returns:
            原函数装饰器
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.register_tool(name or func.__name__, func, description=description)
            return func

        return decorator

    def register_tool(
        self,
        name: str,
        func: Callable[..., Any],
        *,
        description: str | None = None,
    ) -> None:
        """手动注册可调用函数。

        Args:
            name: 工具名
            func: 可调用对象（同步或异步）
            description: 工具描述，缺省时取函数 docstring 摘要
        """
        if name in self._tools:
            logger.warning(f"LLM 工具 {name} 重复注册，将覆盖原实现")
        schema = build_tool_schema(func, name=name, description=description)
        self._tools[name] = ToolDefinition(func=func, schema=schema)
        logger.debug(f"已注册 LLM 工具: {name}")

    async def aclose(self) -> None:
        """关闭底层异步客户端连接（进程退出或测试结束时调用）。"""
        await self._client.close()

    def _build_tool_params(self) -> list[ChatCompletionToolParam]:
        """将已注册工具转换为 OpenAI tools 参数。"""
        return [
            cast("ChatCompletionToolParam", tool.schema)
            for tool in self._tools.values()
        ]

    async def _execute_tool(self, tool_call: ChatCompletionMessageToolCall) -> Any:
        """执行一次工具调用，返回原始返回值；失败时返回错误信息字符串。"""
        # tool_calls 联合类型含无 function 字段的自定义工具，动态访问以兼容
        function = getattr(tool_call, "function", None)
        if function is None:
            return f"工具调用类型不支持: {tool_call.type}"
        tool = self._tools.get(function.name)
        if tool is None:
            return f"工具 {function.name} 未注册"
        try:
            arguments = json.loads(function.arguments or "{}")
            if not isinstance(arguments, dict):
                return f"工具 {function.name} 参数格式错误"
            if inspect.iscoroutinefunction(tool.func):
                return await tool.func(**arguments)
            return tool.func(**arguments)
        except Exception as e:  # noqa: BLE001 - 工具执行失败需兜底回传模型
            logger.warning(f"工具 {function.name} 执行失败: {e}")
            return f"工具执行错误: {e}"

    async def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        max_turns: int | None = None,
    ) -> LLMChatResult:
        """与模型对话，并自动执行模型发起的工具调用。

        Args:
            messages: 对话消息列表（调用方负责维护历史上下文）
            max_turns: 工具调用循环最大轮数，缺省用客户端默认值

        Returns:
            封装结果：最终回复、完整消息历史、工具调用轮数与各工具原始返回值
        """
        turns_limit = max_turns or self.max_turns
        history: list[ChatCompletionMessageParam] = list(messages)
        tool_call_turns = 0
        tool_results: list[ToolResult] = []
        tools = self._build_tool_params() if self._tools else None
        for _ in range(turns_limit):
            request: dict[str, Any] = {"model": self.model, "messages": history}
            if tools:
                request["tools"] = tools
            response = await self._client.chat.completions.create(**request)
            assistant_message = response.choices[0].message
            history.append(_assistant_to_param(assistant_message))
            if not assistant_message.tool_calls:
                break
            tool_call_turns += 1
            for tool_call in assistant_message.tool_calls:
                function = getattr(tool_call, "function", None)
                if function is None:
                    logger.warning(f"忽略不支持的 LLM 工具调用类型: {tool_call.type}")
                    continue
                value = await self._execute_tool(tool_call)
                tool_results.append(
                    ToolResult(
                        name=function.name,
                        tool_call_id=tool_call.id,
                        value=value,
                    ),
                )
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(value),
                    },
                )
        else:
            logger.warning(
                f"LLM 工具调用达到上限 {turns_limit} 轮，未获得最终文本回复",
            )
        logger.info(f"LLM 对话完成，工具调用 {tool_call_turns} 轮")
        return LLMChatResult(
            reply=_extract_reply(history),
            messages=history,
            tool_call_turns=tool_call_turns,
            tool_results=tool_results,
        )


def _assistant_to_param(message: ChatCompletionMessage) -> ChatCompletionMessageParam:
    """将 SDK 助手消息对象转换为消息参数字典，统一历史为 dict 形态。"""
    param: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        function_calls: list[dict[str, Any]] = []
        for tool_call in message.tool_calls:
            function = getattr(tool_call, "function", None)
            if function is None:
                continue
            function_calls.append(
                {
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": function.name,
                        "arguments": function.arguments,
                    },
                },
            )
        param["tool_calls"] = function_calls
    return cast("ChatCompletionMessageParam", param)


def _extract_reply(messages: list[ChatCompletionMessageParam]) -> str:
    """从消息历史中提取最后一条非空助手回复。"""
    for message in reversed(messages):
        if message["role"] != "assistant":
            continue
        content = message["content"]
        if isinstance(content, str) and content:
            return content
    return ""
