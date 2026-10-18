# SinBot

## How to start

1. generate project using `nb create` .
2. create your plugin using `nb plugin create` .
3. writing your plugins under `sinbot/plugins` folder.
4. run your bot using `nb run --reload` .

## Documentation

See [Docs](https://nonebot.dev/)

## Nacos 配置说明

除 `DRIVER=~fastapi+~websockets` 外，**所有运行配置都从 Nacos 拉取**。

### 环境要求

| 项 | 要求 | 说明 |
| --- | --- | --- |
| Nacos 服务端 | **>= 3.x** | 本项目使用 nacos-sdk-python 3.x（async + gRPC），与 2.x 服务端不兼容 |
| HTTP 端口 | `8848` | 配置查询、服务端发现 |
| gRPC 端口 | `9848` | **必须可达**，SDK 按 `8848 + port_offset(默认 1000)` 自动推导 |
| Python | `>= 3.10` | 见 `SinBot/pyproject.toml` |

> 若 Nacos 跑在 Docker 里，容器需同时映射两个端口，例如
> `-p 8848:8848 -p 9848:9848`；只映射 8848 会导致 gRPC 通道建立失败。

启动时 `bot.py` 会在 `nonebot.init()` 之前调用 `sinbot/nacos_config.py` 的
`load_nacos_config()`：拉取配置 → 解析 properties → 写入 `os.environ`。之后
NoneBot 全局配置、`nonebot_plugin_orm`、OneBot 适配器以及各插件的 pydantic
配置模型都沿用原有读取方式，**业务代码零改动**。

### 为什么 `DRIVER` 留在本地

`DRIVER` 必须在 `nonebot.init()` 之前确定，而 Nacos 客户端本身也要在 init 之前
运行，二者都依赖本地引导配置，因此 `DRIVER` 与 `NACOS_*` 一起保留在 `SinBot/.env`。
`DRIVER` 受硬保护：即使 Nacos 也下发了该键，也会被忽略。

### 本地引导配置（`SinBot/.env`）

复制 `.env.example` 为 `.env` 后填写。每项**都可以改用系统环境变量提供**
（系统环境变量优先级更高，适合容器化部署）。

| 键 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `DRIVER` | 是 | - | 驱动声明，不迁移 |
| `NACOS_SERVER_ADDR` | 是 | - | Nacos 地址，如 `127.0.0.1:8848`，多个用逗号分隔 |
| `NACOS_DATA_IDS` | 是 | - | 按声明顺序拉取，后者覆盖前者的同名键 |
| `NACOS_NAMESPACE` | 否 | 空（public） | 命名空间 ID |
| `NACOS_GROUP` | 否 | `DEFAULT_GROUP` | 配置分组 |
| `NACOS_USERNAME` / `NACOS_PASSWORD` | 否 | 空 | 无鉴权时留空 |
| `NACOS_TIMEOUT` | 否 | `10` | 单个 dataId 拉取超时（秒） |
| `NACOS_ALLOW_FAILURE` | 否 | `false` | 拉取失败是否降级为告警继续启动 |

> `NACOS_ALLOW_FAILURE=false` 为快速失败：Nacos 不可达、dataId 不存在或内容为空
> 都会直接终止启动。这是默认行为，因为配置缺失会导致更隐蔽的运行时故障。

### Nacos 上的 dataId 清单

| dataId | 内容 |
| --- | --- |
| `sinbot-common.properties` | 全局配置：环境、日志、数据库、OneBot 连接 |
| `sinbot-team-manager.properties` | `team_manager` 插件配置（`TEAM_MANAGER__*`） |

按模块拆分便于分权限管理；多环境通过 `NACOS_NAMESPACE` 或不同的 dataId 列表区分
（`ENVIRONMENT` 本身已迁入 Nacos，dataId 命名不要依赖它，否则会循环依赖）。

### 迁移对照表

`sinbot-common.properties`：

| 键 | 原值 | 来源 |
| --- | --- | --- |
| `ENVIRONMENT` | `dev` | `.env` |
| `API_TIMEOUT` | `120` | `.env` |
| `SQLALCHEMY_DATABASE_URL` | `sqlite+aiosqlite:///./sinbot.db` | `.env` |
| `LOG_LEVEL` | `DEBUG` | `.env.dev` |
| `ONEBOT_ACCESS_TOKEN` | 敏感值，取原 `.env.dev` 中的值 | `.env.dev` |
| `ONEBOT_WS_URLS` | `["ws://10.0.0.196:3001"]` | `.env.dev` |

`sinbot-team-manager.properties`：

| 键 | 原值 | 来源 |
| --- | --- | --- |
| `TEAM_MANAGER__LLM_BASE_URL` | `https://api.deepseek.com` | `.env` |
| `TEAM_MANAGER__LLM_MODEL` | `deepseek-v4-flash` | `.env` |
| `TEAM_MANAGER__API_BASE_URL` | `http://127.0.0.1:18080` | `.env` |
| `TEAM_MANAGER__API_KEY_HEADER` | `X-Api-Key` | `.env` |
| `TEAM_MANAGER__API_TIMEOUT` | `10` | `.env` |
| `TEAM_MANAGER__API_MAX_RETRIES` | `2` | `.env` |

补充：`plugin/team_manager/config.py` 中还有若干字段此前未配置（一直走默认值），
如需调参可直接在 Nacos 增加：`TEAM_MANAGER__LLM_API_KEY`、`TEAM_MANAGER__API_KEY`、
`TEAM_MANAGER__LLM_MAX_TURNS`、`TEAM_MANAGER__API_RETRY_BACKOFF`、
`TEAM_MANAGER__API_SUCCESS_CODES`。

> 注意：`API_TIMEOUT`（NoneBot 全局）与 `TEAM_MANAGER__API_TIMEOUT`（插件）是两个
> 独立的键，不要合并。

### 配置项热更新

当前为**启动时拉取一次**，不注册监听（NoneBot 多数配置在 init 时已固化，热更实际
生效范围有限）。修改 Nacos 配置后重启即生效。

### properties 语法

支持 `#` / `!` 注释、`=` 与 `:` 分隔、反斜杠续行、`\n` / `\t` 转义：

```properties
# 注释
ENVIRONMENT=dev
ONEBOT_WS_URLS=["ws://10.0.0.196:3001"]
```

## Docker 部署

镜像不含任何业务配置与敏感信息，只有 `DRIVER` 固定写在镜像内；启动时仍从 Nacos
拉取全部业务配置。

### 目录约定

`SinBot/` 的内容被铺到容器内的 `/app`（不是 `/app/SinBot`），因为 `bot.py` 用相对
CWD 的路径加载插件（`./sinbot/plugins/jm_download`），且 `.env` 也位于该目录。

### 构建与启动

```bash
# 1. 准备引导配置（只含 NACOS_* 与 TZ）
cp .env.deploy.example .env.deploy   # 填写 NACOS_SERVER_ADDR 等

# 2. 构建并后台启动
docker compose up -d --build

# 3. 查看日志
docker compose logs -f sinbot
```

也可以只用 Docker：

```bash
docker build -t sinbot:latest .
docker run -d --name sinbot --restart unless-stopped \
  --env-file .env.deploy \
  sinbot:latest
```

### 无状态与持久化

业务数据全部由数据中台提供，容器内不落库，因此镜像**不声明任何卷**，可以随意
重建或横向扩容。

唯一的运行期落盘是 `jm_download` 插件下载的 PDF，输出目录为
`sinbot/plugins/jm_download/download_path`，默认随容器生命周期丢弃；需要跨重建
保留产物时，在 `docker-compose.yml` 中启用 `sinbot-jm` 卷。

### 连接宿主机上的 NapCat

机器人是 OneBot V11 **反向 WS 客户端**，主动外连协议端，容器不监听任何端口，
因此没有 `EXPOSE`。若 Nacos 上的 `ONEBOT_WS_URLS` 是回环地址（如
`ws://127.0.0.1:3001`）：

- Linux：在 `docker-compose.yml` 中启用 `network_mode: host`；
- Windows / macOS（Docker Desktop）：把 URL 改为 `ws://host.docker.internal:3001`，
  或启用 `extra_hosts: ["host.docker.internal:host-gateway"]`。

### 说明

- 构建使用 `uv sync --frozen` 依据 `uv.lock` 安装依赖，结果可复现；升级依赖请先
  在本地执行 `uv lock` 提交新的 `uv.lock` 再重新构建。
- 镜像以非 root 用户（`app`，UID 10001）运行。
- `NACOS_ALLOW_FAILURE` 默认 `false`：Nacos 不可达时容器会退出并由
  `restart: unless-stopped` 重试，属于预期的快速失败语义。
- `.dockerignore` 已排除 `SinBot/.env*`、`.env.deploy`、`sinbot.db`、`__pycache__`
  等，避免本地配置与数据库被打进镜像。
