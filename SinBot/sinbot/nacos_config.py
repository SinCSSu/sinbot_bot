"""Nacos 配置引导加载模块。

在 ``nonebot.init()`` 之前调用 :func:`load_nacos_config`：从 Nacos 拉取配置并写入
``os.environ``，使 NoneBot 全局配置、``nonebot_plugin_orm``、``nonebot-adapter-onebot``
以及各插件的 pydantic 配置模型都能沿用原有读取方式，业务代码零改动。

为什么必须在 ``nonebot.init()`` 之前：

* ``DRIVER`` / ``LOG_LEVEL`` / ``SQLALCHEMY_DATABASE_URL`` 等由 NoneBot 与 ORM 插件在
  init 阶段固化；
* ``team_manager`` 插件在**模块导入时**就执行 ``get_plugin_config(Config)`` 并立即构造
  ``LLMClient``，晚于 init 注入会拿到空配置。

本地 ``.env`` 仅保留 ``DRIVER`` 与连接 Nacos 所需的 ``NACOS_*`` 引导配置（bootstrap），
其余业务配置全部由 Nacos 下发。

引导参数读取优先级：``os.environ`` > 本地 ``.env``（此时 NoneBot 自己的 dotenv 加载
尚未发生，必须由本模块自行读取 ``.env``）。

关于 nacos-sdk-python 版本：

* 本项目锁定 ``>=3.2.0``（v3 世代），其 API 为 ``from v2.nacos import ...``，
  基于 **async + gRPC**，且要求 Nacos 服务端 **>= 3.x**；
* 1.x 及以下才是 ``from nacos import NacosClient`` 的经典同步实现，两者不兼容，
  不能互相替换；
* v3 的 gRPC 端口 = HTTP 端口 + ``port_offset``（默认 1000），即 8848 → 9848，
  部署时需确保该端口可达。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from nonebot import logger

__all__ = [
    "NacosBootstrap",
    "NacosConfigError",
    "afetch_nacos_config",
    "fetch_nacos_config",
    "load_bootstrap",
    "load_nacos_config",
    "parse_config",
    "parse_properties",
]

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
"""本地引导配置文件（SinBot/.env），只含 DRIVER 与 NACOS_* 引导参数。"""

PROTECTED_KEYS = frozenset({"DRIVER"})
"""永不从 Nacos 覆盖的键：驱动必须在 ``nonebot.init()`` 之前就已确定。"""

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y"})
_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r", "f": "\f"}


class NacosConfigError(RuntimeError):
    """Nacos 配置引导失败（缺少引导参数或拉取异常且不允许降级）。"""


@dataclass(frozen=True)
class NacosBootstrap:
    """连接 Nacos 所需的最小引导配置。

    只来自系统环境变量或本地 ``.env``，不可能来自 Nacos 本身。
    """

    server_addr: str
    """Nacos 服务地址，如 ``127.0.0.1:8848``；多个用逗号分隔。"""

    data_ids: tuple[str, ...]
    """按声明顺序拉取的 dataId 列表，后者覆盖前者的同名键。"""

    namespace: str = ""
    """命名空间 ID，留空表示 public。"""

    group: str = "DEFAULT_GROUP"
    """配置分组。"""

    username: str = ""
    password: str = ""
    ak: str = ""
    sk: str = ""
    timeout: float = 10.0
    """单个 dataId 的拉取超时（秒）。"""

    allow_failure: bool = False
    """拉取失败时是否降级为告警继续启动（默认快速失败）。"""


def _unescape(text: str) -> str:
    """按 properties 规则反转义：``\\n`` / ``\\t`` / ``\\=`` / ``\\\\`` 等。"""
    result: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length:
            nxt = text[index + 1]
            result.append(_ESCAPE_MAP.get(nxt, nxt))
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _iter_logical_lines(content: str):
    """合并以奇数个反斜杠结尾的续行。"""
    buffer: list[str] = []
    for line in content.splitlines():
        stripped = line.rstrip("\r\n")
        trailing = len(stripped) - len(stripped.rstrip("\\"))
        if trailing % 2 == 1:
            buffer.append(stripped[:-1])
            continue
        buffer.append(stripped)
        yield "".join(buffer)
        buffer.clear()
    if buffer:
        yield "".join(buffer)


def _split_key_value(line: str) -> tuple[str, str]:
    """切分键与值（Java properties 语义）。

    键在第一个未转义的 ``=`` / ``:`` / 空白处结束；随后跳过空白与紧随的一个
    ``=`` 或 ``:``，剩余部分即为值。这样 ``B = 2`` 的值才是 ``2`` 而不是 ``= 2``。
    """
    escaped = False
    end = len(line)
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in "=:" or char.isspace():
            end = index
            break

    key = _unescape(line[:end]).strip()
    rest = line[end:].lstrip()
    if rest[:1] in ("=", ":"):
        rest = rest[1:]
    return key, _unescape(rest).strip()


def parse_properties(content: str) -> dict[str, str]:
    """解析 Nacos properties 文本为键值对。

    支持 ``#`` / ``!`` 注释、``=`` 与 ``:`` 分隔、反斜杠续行、``\\n`` / ``\\t`` 等转义。
    """
    parsed: dict[str, str] = {}
    for logical in _iter_logical_lines(content):
        line = logical.strip()
        if not line or line[0] in "#!":
            continue
        key, value = _split_key_value(line)
        if not key:
            logger.warning(f"Nacos 配置存在空键行，已跳过: {line!r}")
            continue
        parsed[key] = value
    return parsed


class _UniqueKeyLoader(yaml.SafeLoader):
    """禁止重复键的 SafeLoader。

    YAML 规范不允许同一层级出现重复键，但 PyYAML 默认静默保留最后一个，
    对配置来说是灾难（例如两个 ``team_manager:`` 块会让前一个整体丢失）。
    """


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise NacosConfigError(
                f"Nacos 配置存在重复键 {key!r}（第 {key_node.start_mark.line + 1} 行）："
                f"请合并为同一个块，否则同名键会被静默覆盖"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _flatten(node: dict[Any, Any], prefix: str = "") -> dict[str, str]:
    """把嵌套字典扁平化为 ``环境变量名 -> 字符串值``。

    ``{"team_manager": {"llm_model": "x"}}`` -> ``{"TEAM_MANAGER__LLM_MODEL": "x"}``；
    列表/字典值按 JSON 序列化（NoneBot 的 ``ONEBOT_WS_URLS`` 就要求这种形式）。
    """
    flat: dict[str, str] = {}
    for key, value in node.items():
        env_key = f"{prefix}__{key}" if prefix else str(key)
        env_key = env_key.upper()
        if isinstance(value, dict):
            flat.update(_flatten(value, env_key))
        elif isinstance(value, (list, tuple)):
            flat[env_key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            flat[env_key] = "true" if value else "false"
        elif value is None:
            continue
        elif isinstance(value, str):
            flat[env_key] = value
        else:
            flat[env_key] = str(value)
    return flat


def parse_config(content: str) -> dict[str, str]:
    """解析 Nacos 配置内容，自动识别 YAML 与 properties 两种格式。

    Nacos 控制台创建配置时可以选择格式：选 YAML 写嵌套结构、选 Properties 写
    ``KEY=VALUE``。两种都需要支持——按 YAML 尝试解析，得到映射就按嵌套扁平化；
    否则回退 :func:`parse_properties`。

    Raises:
        NacosConfigError: YAML 存在重复键（否则会被静默覆盖）。
    """
    try:
        document = yaml.load(content, Loader=_UniqueKeyLoader)
    except NacosConfigError:
        raise
    except yaml.YAMLError:
        document = None
    if isinstance(document, dict):
        return _flatten(document)
    return parse_properties(content)


def _as_bool(raw: str, default: bool) -> bool:
    if not raw:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _as_float(raw: str, default: float) -> float:
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"NACOS_TIMEOUT 不是合法数字({raw!r})，回退为 {default}")
        return default


def load_bootstrap(env_file: Path | str | None = None) -> NacosBootstrap:
    """读取引导配置：系统环境变量优先，缺失键回退本地 ``.env``。

    Raises:
        NacosConfigError: 缺少 ``NACOS_SERVER_ADDR`` 或 ``NACOS_DATA_IDS``。
    """
    path = Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
    file_values: dict[str, str] = {}
    if path.is_file():
        file_values = {
            key: value
            for key, value in dotenv_values(path, encoding="utf-8").items()
            if value is not None
        }
    else:
        logger.warning(f"未找到本地引导配置文件 {path}，仅使用系统环境变量")

    def read(key: str, default: str = "") -> str:
        value = os.environ.get(key)
        if not value:
            value = file_values.get(key, default)
        return value

    server_addr = read("NACOS_SERVER_ADDR").strip()
    if not server_addr:
        raise NacosConfigError(
            "缺少 Nacos 引导参数 NACOS_SERVER_ADDR，请在系统环境变量或 "
            f"{path} 中配置"
        )

    raw_data_ids = read("NACOS_DATA_IDS").replace(";", ",")
    data_ids = tuple(part.strip() for part in raw_data_ids.split(",") if part.strip())
    if not data_ids:
        raise NacosConfigError(
            f"缺少 Nacos 引导参数 NACOS_DATA_IDS，请在系统环境变量或 {path} 中配置"
        )

    bootstrap = NacosBootstrap(
        server_addr=server_addr,
        data_ids=data_ids,
        namespace=read("NACOS_NAMESPACE").strip(),
        group=read("NACOS_GROUP", "DEFAULT_GROUP").strip() or "DEFAULT_GROUP",
        username=read("NACOS_USERNAME").strip(),
        password=read("NACOS_PASSWORD"),
        ak=read("NACOS_AK").strip(),
        sk=read("NACOS_SK").strip(),
        timeout=_as_float(read("NACOS_TIMEOUT"), 10.0),
        allow_failure=_as_bool(read("NACOS_ALLOW_FAILURE"), False),
    )
    logger.info(
        f"Nacos 引导参数就绪: server={bootstrap.server_addr} "
        f"group={bootstrap.group} dataIds={list(bootstrap.data_ids)}"
    )
    return bootstrap


async def afetch_nacos_config(bootstrap: NacosBootstrap) -> dict[str, str]:
    """异步拉取：按 ``data_ids`` 顺序逐个拉取并按序合并（后者覆盖前者）。

    nacos-sdk-python 3.x 已重写为 async + gRPC 架构，真正的拉取逻辑在此，
    :func:`fetch_nacos_config` 只是它的同步包装。

    Raises:
        NacosConfigError: 拉取失败且 ``allow_failure`` 为 ``False``。
    """
    try:
        from v2.nacos import (
            ClientConfigBuilder,
            ConfigParam,
            GRPCConfig,
            NacosConfigService,
        )
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确指引
        raise NacosConfigError(
            "未安装 nacos-sdk-python(v3)，请先执行 uv sync 安装依赖"
        ) from exc

    timeout_ms = int(bootstrap.timeout * 1000)
    client_config = (
        ClientConfigBuilder()
        .server_address(bootstrap.server_addr)
        .namespace_id(bootstrap.namespace or "")
        .username(bootstrap.username or None)
        .password(bootstrap.password or None)
        .access_key(bootstrap.ak or None)
        .secret_key(bootstrap.sk or None)
        .timeout_ms(timeout_ms)
        .grpc_config(GRPCConfig(grpc_timeout=timeout_ms))
        .log_level("WARN")
        .build()
    )
    # v3 没有 no_snapshot 参数，等价开关是 disable_use_config_cache：服务端返回
    # 400 时不再回退本地快照，否则"配置缺失"会被伪装成"配置有值"，破坏快速失败
    # 语义。注意 ClientConfigBuilder 没有对应方法，只能在 build() 后直接赋值
    # （ClientConfig 上默认为 False）。
    client_config.disable_use_config_cache = True

    client = await NacosConfigService.create_config_service(client_config)
    merged: dict[str, str] = {}
    try:
        for data_id in bootstrap.data_ids:
            try:
                content = await client.get_config(
                    ConfigParam(data_id=data_id, group=bootstrap.group)
                )
            except Exception as exc:
                message = (
                    f"Nacos 拉取失败: dataId={data_id} "
                    f"group={bootstrap.group}: {exc!r}"
                )
                if not bootstrap.allow_failure:
                    raise NacosConfigError(message) from exc
                logger.warning(f"{message}（已降级跳过）")
                continue

            if not content or not content.strip():
                # 服务端返回 300（配置不存在）时 SDK 会吞掉异常返回空串，落到这里。
                message = (
                    f"Nacos 配置不存在或为空: dataId={data_id} "
                    f"group={bootstrap.group}"
                )
                if not bootstrap.allow_failure:
                    raise NacosConfigError(message)
                logger.warning(message)
                continue

            parsed = parse_config(content)
            merged.update(parsed)
            # 只打印键名，避免敏感值（token / api_key / 密码）进入日志
            logger.info(
                f"Nacos 配置已加载: dataId={data_id} "
                f"共 {len(parsed)} 项 -> {sorted(parsed)}"
            )
    finally:
        # v3 持有 gRPC 长连接与后台监听协程，必须显式关闭，否则进程退出时挂起。
        await client.shutdown()
    return merged


def fetch_nacos_config(bootstrap: NacosBootstrap) -> dict[str, str]:
    """同步入口：内部起一个临时事件循环执行 :func:`afetch_nacos_config`。

    由 ``bot.py`` 在 ``nonebot.init()`` 之前调用，此时主线程还没有运行中的
    事件循环，使用 ``asyncio.run`` 是安全的。
    """
    return asyncio.run(afetch_nacos_config(bootstrap))


def load_nacos_config(env_file: Path | str | None = None) -> dict[str, str]:
    """入口：从 Nacos 拉取配置并注入 ``os.environ``。

    返回实际注入的键值对。受 :data:`PROTECTED_KEYS` 保护的键不会被 Nacos 覆盖。
    """
    bootstrap = load_bootstrap(env_file)
    remote = fetch_nacos_config(bootstrap)

    applied: dict[str, str] = {}
    for key, value in remote.items():
        if key in PROTECTED_KEYS:
            logger.warning(
                f"Nacos 下发了受保护的配置项 {key}，已忽略（本地 .env 优先）"
            )
            continue
        if not value.strip():
            # NoneBot 的 EnvSettings 会把每个顶层配置项（不含 "__" 的键，如 TEAM_MANAGER）
            # 按 JSON 解析，空值会抛 ``SettingsError: error parsing env var "team_manager"``。
            # Nacos 里出现这种键通常是漏写字段名（应写 TEAM_MANAGER__XXX）或写成了 YAML。
            logger.warning(
                f"Nacos 配置项 {key} 的值为空，已跳过：NoneBot 会把键 {key} 当作顶层"
                f'配置项并按 JSON 解析，空值会直接导致启动失败；'
                f"若本意是配置插件字段，请写成 {key}__字段名=值 的形式"
            )
            continue
        os.environ[key] = value
        applied[key] = value

    if applied:
        logger.success(f"已从 Nacos 注入 {len(applied)} 项配置: {sorted(applied)}")
    else:
        logger.warning("Nacos 未下发任何配置，将完全依赖本地环境变量与默认值")
    return applied
