"""Nacos 引导加载模块的单元测试（不联网、不依赖真实 Nacos 服务）。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import ModuleType

from sinbot.nacos_config import (
    NacosBootstrap,
    NacosConfigError,
    afetch_nacos_config,
    fetch_nacos_config,
    load_bootstrap,
    load_nacos_config,
    parse_config,
    parse_properties,
)

_BOOTSTRAP_KEYS = (
    "NACOS_SERVER_ADDR",
    "NACOS_DATA_IDS",
    "NACOS_NAMESPACE",
    "NACOS_GROUP",
    "NACOS_USERNAME",
    "NACOS_PASSWORD",
    "NACOS_AK",
    "NACOS_SK",
    "NACOS_TIMEOUT",
    "NACOS_ALLOW_FAILURE",
)


@contextlib.contextmanager
def _clean_bootstrap_env():
    """隔离引导相关的环境变量，避免相互污染。"""
    saved = {key: os.environ.get(key) for key in _BOOTSTRAP_KEYS}
    for key in _BOOTSTRAP_KEYS:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _patch_nacos(handler):
    """用假的 ``v2.nacos`` 模块替换真实 SDK，记录构造参数与调用。

    nacos-sdk-python 3.x 的包名是 ``v2.nacos``（而非 1.x 的 ``nacos``），
    因此必须同时注入顶层 ``v2`` 包与 ``v2.nacos`` 子模块——
    ``from v2.nacos import X`` 会先解析顶层包 ``v2``，只补子模块不够。
    """
    captured: dict = {}

    class ConfigParam:
        def __init__(self, data_id="", group="", **kwargs):
            self.data_id = data_id
            self.group = group
            for key, value in kwargs.items():
                setattr(self, key, value)

    class ClientConfig:
        """模拟 ``ClientConfig`` 的默认字段（被测代码会覆盖）。"""

        def __init__(self):
            self.disable_use_config_cache = False

    class GRPCConfig:
        def __init__(self, grpc_timeout=None, port_offset=None, **kwargs):
            self.grpc_timeout = grpc_timeout
            self.port_offset = port_offset

    class ClientConfigBuilder:
        def __init__(self):
            self._values: dict = {}
            self._config = ClientConfig()

        def __getattr__(self, name):
            def _setter(value):
                self._values[name] = value
                setattr(self._config, name, value)
                return self

            return _setter

        def build(self):
            captured.update(self._values)
            return self._config

    class NacosConfigService:
        def __init__(self, client_config):
            self.client_config = client_config

        @staticmethod
        async def create_config_service(client_config):
            return NacosConfigService(client_config)

        async def get_config(self, param):
            captured.setdefault("calls", []).append((param.data_id, param.group))
            # 记录被测代码是否真的关掉了本地快照回退
            captured["final_disable_use_config_cache"] = (
                self.client_config.disable_use_config_cache
            )
            return handler(param.data_id, param.group)

        async def shutdown(self):
            captured["shutdown"] = True

    module = ModuleType("v2.nacos")
    module.ClientConfig = ClientConfig
    module.ClientConfigBuilder = ClientConfigBuilder
    module.ConfigParam = ConfigParam
    module.GRPCConfig = GRPCConfig
    module.NacosConfigService = NacosConfigService

    top = ModuleType("v2")
    top.nacos = module

    original_v2 = sys.modules.get("v2")
    original_v2nacos = sys.modules.get("v2.nacos")
    sys.modules["v2"] = top
    sys.modules["v2.nacos"] = module
    try:
        yield captured
    finally:
        for key, value in (("v2", original_v2), ("v2.nacos", original_v2nacos)):
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def _missing_env_file() -> Path:
    """返回一个确定不存在的 .env 路径，避免测试读到项目真实的 .env。"""
    path = Path(tempfile.gettempdir()) / "sinbot_absent_bootstrap.env"
    path.unlink(missing_ok=True)
    return path


def _write_env(content: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".env", delete=False, encoding="utf-8"
    )
    with handle:
        handle.write(content)
    return Path(handle.name)


class ParsePropertiesTest(unittest.TestCase):
    """properties 文本解析。"""

    def test_basic_and_comments(self):
        content = """
        # 井号注释
        ! 感叹号注释
        A=1

        B = 2
        """
        self.assertEqual(parse_properties(content), {"A": "1", "B": "2"})

    def test_colon_and_whitespace_separator(self):
        self.assertEqual(
            parse_properties("A: 1\nB 2\n"),
            {"A": "1", "B": "2"},
        )

    def test_value_keeps_inner_content(self):
        self.assertEqual(
            parse_properties('ONEBOT_WS_URLS=["ws://10.0.0.196:3001"]'),
            {"ONEBOT_WS_URLS": '["ws://10.0.0.196:3001"]'},
        )

    def test_continuation_line(self):
        self.assertEqual(parse_properties("LONG=a\\\n    b\n"), {"LONG": "a    b"})

    def test_escape_sequences(self):
        self.assertEqual(parse_properties(r"PATH=C:\\temp"), {"PATH": r"C:\temp"})
        self.assertEqual(parse_properties(r"NOTE=a\nb"), {"NOTE": "a\nb"})

    def test_key_without_value(self):
        self.assertEqual(parse_properties("EMPTY"), {"EMPTY": ""})

    def test_trailing_backslash_pair_is_not_continuation(self):
        self.assertEqual(parse_properties("A=x\\\\\nB=y"), {"A": "x\\", "B": "y"})


class ParseConfigTest(unittest.TestCase):
    """Nacos 内容格式自动识别：YAML 扁平化 / properties 回退。"""

    def test_yaml_nested_is_flattened(self):
        content = (
            "environment: dev\n"
            "log_level: DEBUG\n"
            "team_manager:\n"
            "  llm_base_url: https://api.deepseek.com\n"
            "  api_timeout: 10\n"
        )
        self.assertEqual(
            parse_config(content),
            {
                "ENVIRONMENT": "dev",
                "LOG_LEVEL": "DEBUG",
                "TEAM_MANAGER__LLM_BASE_URL": "https://api.deepseek.com",
                "TEAM_MANAGER__API_TIMEOUT": "10",
            },
        )

    def test_yaml_list_becomes_json(self):
        self.assertEqual(
            parse_config('onebot_ws_urls: ["ws://1.2.3.4:3001"]'),
            {"ONEBOT_WS_URLS": '["ws://1.2.3.4:3001"]'},
        )

    def test_multi_level_nesting(self):
        self.assertEqual(
            parse_config("team_manager:\n  llm:\n    model: m\n"),
            {"TEAM_MANAGER__LLM__MODEL": "m"},
        )

    def test_properties_falls_back(self):
        self.assertEqual(parse_config("A=1\nB=2"), {"A": "1", "B": "2"})
        self.assertEqual(
            parse_config('ONEBOT_WS_URLS=["ws://10.0.0.196:3001"]'),
            {"ONEBOT_WS_URLS": '["ws://10.0.0.196:3001"]'},
        )

    def test_duplicate_key_raises(self):
        content = (
            "team_manager:\n"
            "  llm_model: a\n"
            "team_manager:\n"
            "  llm_model: b\n"
        )
        with self.assertRaises(NacosConfigError):
            parse_config(content)


class LoadBootstrapTest(unittest.TestCase):
    """引导参数：系统环境变量优先，缺失键回退 .env。"""

    def test_missing_server_addr_raises(self):
        with _clean_bootstrap_env():
            with self.assertRaises(NacosConfigError):
                load_bootstrap(_missing_env_file())

    def test_missing_data_ids_raises(self):
        with _clean_bootstrap_env():
            os.environ["NACOS_SERVER_ADDR"] = "127.0.0.1:8848"
            with self.assertRaises(NacosConfigError):
                load_bootstrap(_missing_env_file())

    def test_env_file_fallback(self):
        env_file = _write_env(
            "NACOS_SERVER_ADDR=10.0.0.1:8848\n"
            "NACOS_DATA_IDS=common.properties,team.properties\n"
            "NACOS_GROUP=MY_GROUP\n"
            "NACOS_TIMEOUT=3.5\n"
            "NACOS_ALLOW_FAILURE=true\n"
        )
        try:
            with _clean_bootstrap_env():
                bootstrap = load_bootstrap(env_file)
        finally:
            env_file.unlink(missing_ok=True)

        self.assertEqual(bootstrap.server_addr, "10.0.0.1:8848")
        self.assertEqual(bootstrap.data_ids, ("common.properties", "team.properties"))
        self.assertEqual(bootstrap.group, "MY_GROUP")
        self.assertEqual(bootstrap.timeout, 3.5)
        self.assertTrue(bootstrap.allow_failure)

    def test_system_env_overrides_env_file(self):
        env_file = _write_env(
            "NACOS_SERVER_ADDR=10.0.0.1:8848\nNACOS_DATA_IDS=common.properties\n"
        )
        try:
            with _clean_bootstrap_env():
                os.environ["NACOS_SERVER_ADDR"] = "192.168.1.1:8848"
                bootstrap = load_bootstrap(env_file)
        finally:
            env_file.unlink(missing_ok=True)

        self.assertEqual(bootstrap.server_addr, "192.168.1.1:8848")
        self.assertEqual(bootstrap.data_ids, ("common.properties",))

    def test_defaults(self):
        with _clean_bootstrap_env():
            os.environ["NACOS_SERVER_ADDR"] = "127.0.0.1:8848"
            os.environ["NACOS_DATA_IDS"] = "a.properties"
            bootstrap = load_bootstrap(_missing_env_file())

        self.assertEqual(bootstrap.group, "DEFAULT_GROUP")
        self.assertEqual(bootstrap.namespace, "")
        self.assertEqual(bootstrap.timeout, 10.0)
        self.assertFalse(bootstrap.allow_failure)


class FetchNacosConfigTest(unittest.TestCase):
    """多 dataId 拉取合并与失败策略。"""

    def _bootstrap(self, **kwargs) -> NacosBootstrap:
        base = {
            "server_addr": "127.0.0.1:8848",
            "data_ids": ("common.properties", "team.properties"),
            "group": "G",
        }
        base.update(kwargs)
        return NacosBootstrap(**base)  # type: ignore[arg-type]

    def test_merge_order_later_wins(self):
        content = {
            "common.properties": "A=1\nB=1\n",
            "team.properties": "B=2\nC=3\n",
        }
        with _patch_nacos(lambda data_id, group: content[data_id]) as captured:
            merged = fetch_nacos_config(self._bootstrap())

        self.assertEqual(merged, {"A": "1", "B": "2", "C": "3"})
        self.assertEqual(captured["server_address"], "127.0.0.1:8848")
        self.assertEqual(captured["namespace_id"], "")
        # 按声明顺序拉取，后者覆盖前者
        self.assertEqual(
            captured["calls"],
            [("common.properties", "G"), ("team.properties", "G")],
        )
        # v3 没有 no_snapshot 参数，等价开关是 disable_use_config_cache：
        # 服务端返回 400 时不再回退本地快照，否则"配置缺失"会被伪装成"配置有值"。
        self.assertTrue(captured["final_disable_use_config_cache"])
        # 超时默认 10 秒 -> grpc_timeout 10000ms
        self.assertEqual(captured["grpc_config"].grpc_timeout, 10000)
        # gRPC 长连接必须显式关闭，否则进程退出时挂起
        self.assertTrue(captured["shutdown"])

    def test_async_entry_matches_sync_result(self):
        """同步入口与异步协程入口结果一致。"""
        content = {
            "common.properties": "A=1\n",
            "team.properties": "B=2\n",
        }
        handler = lambda data_id, group: content[data_id]  # noqa: E731
        with _patch_nacos(handler):
            sync_result = fetch_nacos_config(self._bootstrap())
        with _patch_nacos(handler):
            async_result = asyncio.run(afetch_nacos_config(self._bootstrap()))

        self.assertEqual(sync_result, async_result)
        self.assertEqual(sync_result, {"A": "1", "B": "2"})

    def test_failure_raises_by_default(self):
        def boom(data_id, group):
            raise OSError("connection refused")

        with _patch_nacos(boom):
            with self.assertRaises(NacosConfigError):
                fetch_nacos_config(self._bootstrap())

    def test_failure_degrades_when_allowed(self):
        def boom(data_id, group):
            raise OSError("connection refused")

        with _patch_nacos(boom):
            merged = fetch_nacos_config(self._bootstrap(allow_failure=True))
        self.assertEqual(merged, {})

    def test_empty_content_raises_by_default(self):
        with _patch_nacos(lambda data_id, group: ""):
            with self.assertRaises(NacosConfigError):
                fetch_nacos_config(self._bootstrap())

    def test_none_content_degrades_when_allowed(self):
        with _patch_nacos(lambda data_id, group: None):
            merged = fetch_nacos_config(self._bootstrap(allow_failure=True))
        self.assertEqual(merged, {})


class LoadNacosConfigTest(unittest.TestCase):
    """注入 os.environ 与 DRIVER 保护。"""

    def test_injects_and_protects_driver(self):
        bootstrap = NacosBootstrap(
            server_addr="127.0.0.1:8848", data_ids=("common.properties",)
        )
        remote = {
            "DRIVER": "~httpx",
            "LOG_LEVEL": "DEBUG",
            "TEAM_MANAGER__LLM_MODEL": "deepseek-v4-flash",
        }
        with unittest.mock.patch(
            "sinbot.nacos_config.load_bootstrap", return_value=bootstrap
        ), unittest.mock.patch(
            "sinbot.nacos_config.fetch_nacos_config", return_value=remote
        ):
            with _clean_bootstrap_env():
                os.environ.pop("DRIVER", None)
                try:
                    applied = load_nacos_config()
                    self.assertEqual(
                        os.environ["TEAM_MANAGER__LLM_MODEL"], "deepseek-v4-flash"
                    )
                    self.assertEqual(os.environ["LOG_LEVEL"], "DEBUG")
                    # DRIVER 受保护：既不被注入，也不被覆盖
                    self.assertNotIn("DRIVER", os.environ)
                    self.assertNotIn("DRIVER", applied)
                finally:
                    for key in ("LOG_LEVEL", "TEAM_MANAGER__LLM_MODEL"):
                        os.environ.pop(key, None)

    def test_empty_value_skipped(self):
        """空值键必须跳过：NoneBot 会把顶层配置项按 JSON 解析而报错。"""
        bootstrap = NacosBootstrap(
            server_addr="127.0.0.1:8848", data_ids=("team-manager.properties",)
        )
        remote = {"TEAM_MANAGER": "", "TEAM_MANAGER__LLM_MODEL": "deepseek-v4-flash"}
        with unittest.mock.patch(
            "sinbot.nacos_config.load_bootstrap", return_value=bootstrap
        ), unittest.mock.patch(
            "sinbot.nacos_config.fetch_nacos_config", return_value=remote
        ):
            with _clean_bootstrap_env():
                os.environ.pop("TEAM_MANAGER", None)
                try:
                    applied = load_nacos_config()
                    self.assertNotIn("TEAM_MANAGER", os.environ)
                    self.assertNotIn("TEAM_MANAGER", applied)
                    self.assertEqual(
                        os.environ["TEAM_MANAGER__LLM_MODEL"], "deepseek-v4-flash"
                    )
                finally:
                    os.environ.pop("TEAM_MANAGER", None)
                    os.environ.pop("TEAM_MANAGER__LLM_MODEL", None)

    def test_existing_driver_not_overwritten(self):
        bootstrap = NacosBootstrap(
            server_addr="127.0.0.1:8848", data_ids=("common.properties",)
        )
        with unittest.mock.patch(
            "sinbot.nacos_config.load_bootstrap", return_value=bootstrap
        ), unittest.mock.patch(
            "sinbot.nacos_config.fetch_nacos_config",
            return_value={"DRIVER": "~httpx", "A": "1"},
        ):
            with _clean_bootstrap_env():
                os.environ["DRIVER"] = "~fastapi+~websockets"
                try:
                    load_nacos_config()
                    self.assertEqual(os.environ["DRIVER"], "~fastapi+~websockets")
                    self.assertEqual(os.environ["A"], "1")
                finally:
                    os.environ.pop("A", None)
                    os.environ.pop("DRIVER", None)


if __name__ == "__main__":
    unittest.main()
