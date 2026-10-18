# SinBot

NoneBot 机器人应用代码目录。

项目的完整说明（部署方式、Nacos 配置清单、目录结构等）见仓库根目录的
[README.md](../README.md)。

## 本地开发

```bash
uv sync
uv run bot.py
```

## Nacos 客户端版本约定

`pyproject.toml` 锁定 `nacos-sdk-python>=3.2.0`（v3 世代），对应：

- 包名为 `v2.nacos`（**不是** 1.x 的顶层 `nacos`）；
- async + gRPC 架构，协程入口为 `NacosConfigService.create_config_service()` /
  `get_config()` / `shutdown()`，同步包装见 `sinbot/nacos_config.py`；
- 要求 Nacos 服务端 **>= 3.x**（AI Client 相关功能需 3.1.0+）；
- gRPC 端口 = HTTP 端口 + `port_offset`（默认 1000），即 **8848 -> 9848 必须可达**。

1.x 及以下是 `from nacos import NacosClient` 的经典同步实现，与本目录代码不兼容，
二者不能互相替换；升级跨越 2.0.0 时必须同步修改 `sinbot/nacos_config.py`。

另：`3.0.0` / `3.0.1` / `3.0.2` 已被官方 yank（Agent 注册在连接断开后无法重新
注册），实际可用版本需 `>=3.0.3`。
