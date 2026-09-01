"""LLM 基础设施层单元测试（不依赖 nonebot 运行时环境）。"""

from __future__ import annotations

import asyncio
import importlib.abc
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Literal

_SINBOT_ROOT = Path(__file__).resolve().parents[1]
_INFRA_DIR = _SINBOT_ROOT / "plugins" / "team_manager" / "infrastructure"


def _load_module(module_name: str, file_name: str) -> ModuleType:
    """直接加载模块文件，绕过 team_manager 包的插件副作用。"""
    spec = importlib.util.spec_from_file_location(module_name, _INFRA_DIR / file_name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader: importlib.abc.Loader = spec.loader
    # typeshed 未声明 Loader.exec_module，但 importlib 运行时提供该方法
    loader.exec_module(module)  # pyright: ignore[reportAttributeAccessIssue]
    return module


schema_builder = _load_module(
    "sinbot.plugins.team_manager.infrastructure.schema_builder",
    "schema_builder.py",
)
llm_client_module = _load_module(
    "sinbot.plugins.team_manager.infrastructure.llm_client",
    "llm_client.py",
)
build_tool_schema = schema_builder.build_tool_schema
LLMClient = llm_client_module.LLMClient
LLMChatResult = llm_client_module.LLMChatResult


class SchemaBuilderTest(unittest.TestCase):
    """build_tool_schema 的类型映射与 docstring 解析。"""

    def test_basic_types(self) -> None:
        def add(a: int, b: float) -> float:
            """计算两数之和。

            Args:
                a: 第一个数
                b: 第二个数
            """
            return a + b

        schema = build_tool_schema(add)
        function = schema["function"]
        self.assertEqual(function["name"], "add")
        self.assertIn("计算两数之和", function["description"])
        parameters = function["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(parameters["required"], ["a", "b"])
        self.assertEqual(parameters["properties"]["a"]["type"], "integer")
        self.assertEqual(parameters["properties"]["a"]["description"], "第一个数")
        self.assertEqual(parameters["properties"]["b"]["type"], "number")

    def test_optional_param_not_required(self) -> None:
        def greet(name: str, _title: str | None = None) -> str:
            """打招呼。

            Args:
                name: 姓名
                _title: 称呼
            """
            return name

        schema = build_tool_schema(greet)
        parameters = schema["function"]["parameters"]
        self.assertEqual(parameters["required"], ["name"])
        title_prop = parameters["properties"]["_title"]
        self.assertEqual(title_prop["anyOf"][1]["type"], "null")

    def test_literal_enum(self) -> None:
        def set_mode(mode: Literal["fast", "safe"]) -> str:
            """设置模式。

            Args:
                mode: 模式名称
            """
            return mode

        schema = build_tool_schema(set_mode)
        mode_prop = schema["function"]["parameters"]["properties"]["mode"]
        self.assertEqual(mode_prop["type"], "string")
        self.assertEqual(mode_prop["enum"], ["fast", "safe"])

    def test_list_type(self) -> None:
        def pick(names: list[str]) -> str:
            """选择名字。"""
            return names[0]

        schema = build_tool_schema(pick)
        names_prop = schema["function"]["parameters"]["properties"]["names"]
        self.assertEqual(names_prop["type"], "array")
        self.assertEqual(names_prop["items"]["type"], "string")

    def test_optional_without_default_is_required(self) -> None:
        def fetch(user_id: int | None) -> str:
            """按用户 ID 查询，允许空值。"""
            return str(user_id)

        schema = build_tool_schema(fetch)
        parameters = schema["function"]["parameters"]
        # `X | None` 无默认值仍为必填（允许传 null），不能依赖默认值省略
        self.assertEqual(parameters["required"], ["user_id"])
        user_prop = parameters["properties"]["user_id"]
        self.assertEqual(user_prop["anyOf"][0]["type"], "integer")
        self.assertEqual(user_prop["anyOf"][1]["type"], "null")


class LLMClientRegisterTest(unittest.TestCase):
    """LLMClient 的 register 装饰器与手动注册。"""

    def test_register_decorator(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        @client.register()
        async def get_weather(city: str) -> str:
            """查询天气。

            Args:
                city: 城市名
            """
            return f"{city} 晴"

        self.assertIn("get_weather", client._tools)
        schema = client._tools["get_weather"].schema
        self.assertEqual(schema["function"]["name"], "get_weather")
        self.assertEqual(
            schema["function"]["parameters"]["properties"]["city"]["description"],
            "城市名",
        )

    def test_register_decorator_with_name(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        @client.register("do_math")
        def double(x: int) -> int:
            """翻倍。"""
            return x * 2

        self.assertIn("do_math", client._tools)
        self.assertEqual(client._tools["do_math"].schema["function"]["name"], "do_math")

    def test_register_tool_manual(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        def double(x: int) -> int:
            """翻倍。"""
            return x * 2

        client.register_tool("manual_tool", double, description="手动注册工具")
        schema = client._tools["manual_tool"].schema
        self.assertEqual(schema["function"]["description"], "手动注册工具")

    def test_build_tool_params(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        def double(x: int) -> int:
            """翻倍。"""
            return x * 2

        client.register_tool("double", double)
        params = client._build_tool_params()
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]["function"]["name"], "double")


class LLMClientChatTest(unittest.TestCase):
    """LLMClient 的自动工具调用循环。"""

    def test_chat_auto_tool_call(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        @client.register()
        def double(x: int) -> int:
            """翻倍。"""
            return x * 2

        calls: list[dict] = []

        async def fake_create(**kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            if len(calls) == 1:
                message = SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            type="function",
                            function=SimpleNamespace(
                                name="double",
                                arguments='{"x": 21}',
                            ),
                        ),
                    ],
                    content=None,
                )
            else:
                message = SimpleNamespace(tool_calls=None, content="结果是 42")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

        async def run() -> LLMChatResult:
            return await client.chat([{"role": "user", "content": "21 的两倍是多少？"}])

        result: LLMChatResult = asyncio.run(run())
        self.assertEqual(result.reply, "结果是 42")
        self.assertEqual(result.tool_call_turns, 1)
        tool_messages = [m for m in result.messages if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0]["content"], "42")
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_1")

    def test_chat_without_tools(self) -> None:
        client = LLMClient(api_key="", model="test-model")
        calls: list[dict] = []

        async def fake_create(**kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            message = SimpleNamespace(tool_calls=None, content="你好")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

        async def run() -> LLMChatResult:
            return await client.chat([{"role": "user", "content": "你好"}])

        result: LLMChatResult = asyncio.run(run())
        self.assertEqual(result.reply, "你好")
        self.assertEqual(result.tool_call_turns, 0)
        self.assertNotIn("tools", calls[0])

    def test_chat_tool_error_handled(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        @client.register()
        def divide(a: int, b: int) -> int:
            """除法。"""
            return a // b

        async def fake_create(**kwargs: object) -> SimpleNamespace:  # noqa: ARG001
            message = SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id="call_err",
                        type="function",
                        function=SimpleNamespace(
                            name="divide",
                            arguments='{"a": 1, "b": 0}',
                        ),
                    ),
                ],
                content=None,
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

        async def run() -> LLMChatResult:
            return await client.chat(
                [{"role": "user", "content": "1 除以 0"}],
                max_turns=1,
            )

        result: LLMChatResult = asyncio.run(run())
        tool_messages = [m for m in result.messages if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("工具执行错误", tool_messages[0]["content"])

    def test_chat_unregistered_tool(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        async def fake_create(**kwargs: object) -> SimpleNamespace:  # noqa: ARG001
            message = SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id="call_ghost",
                        type="function",
                        function=SimpleNamespace(
                            name="ghost_tool",
                            arguments="{}",
                        ),
                    ),
                ],
                content=None,
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

        async def run() -> LLMChatResult:
            return await client.chat(
                [{"role": "user", "content": "调用未注册工具"}],
                max_turns=1,
            )

        result: LLMChatResult = asyncio.run(run())
        tool_messages = [m for m in result.messages if m["role"] == "tool"]
        self.assertEqual(tool_messages[0]["content"], "工具 ghost_tool 未注册")

    def test_chat_invalid_arguments(self) -> None:
        client = LLMClient(api_key="", model="test-model")

        @client.register()
        def double(x: int) -> int:
            """翻倍。"""
            return x * 2

        async def fake_create(**kwargs: object) -> SimpleNamespace:  # noqa: ARG001
            message = SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id="call_bad",
                        type="function",
                        function=SimpleNamespace(
                            name="double",
                            arguments="[]",
                        ),
                    ),
                ],
                content=None,
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

        async def run() -> LLMChatResult:
            return await client.chat([{"role": "user", "content": "翻倍"}], max_turns=1)

        result: LLMChatResult = asyncio.run(run())
        tool_messages = [m for m in result.messages if m["role"] == "tool"]
        self.assertEqual(tool_messages[0]["content"], "工具 double 参数格式错误")

    def test_chat_max_turns_exhausted(self) -> None:
        client = LLMClient(api_key="", model="test-model", max_turns=2)

        @client.register()
        def ping() -> str:
            """回声。"""
            return "pong"

        calls: list[dict] = []

        async def fake_create(**kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            message = SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id=f"call_{len(calls)}",
                        type="function",
                        function=SimpleNamespace(name="ping", arguments="{}"),
                    ),
                ],
                content=None,
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        client._client.chat.completions.create = fake_create  # type: ignore[method-assign]

        async def run() -> LLMChatResult:
            return await client.chat([{"role": "user", "content": "ping"}])

        result: LLMChatResult = asyncio.run(run())
        self.assertEqual(result.tool_call_turns, 2)
        # 耗尽后无最终文本回复，reply 为空但循环已安全终止
        self.assertEqual(result.reply, "")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
