# syntax=docker/dockerfile:1
#
# SinBot 容器化构建
#   · builder：uv 镜像，依据 uv.lock 在 /app/.venv 安装依赖（可复现、可缓存）
#   · runtime：python:3.12-slim，只拷贝 .venv 与代码，非 root 用户运行
#
# 构建上下文必须是仓库根目录：
#   docker build -t sinbot:latest .
#
# 运行期全部业务配置来自 Nacos，镜像内不含任何敏感信息；
# 仅需注入 Nacos 引导参数（NACOS_SERVER_ADDR / NACOS_DATA_IDS ...），详见 README。

# ------------------------------- builder -------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# UV_LINK_MODE=copy：跨阶段拷贝 .venv 时避免符号链接失效
# UV_COMPILE_BYTECODE=1：预编译字节码，缩短冷启动
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 先只拷贝依赖声明：改业务代码不会触发依赖重装
# README.md 为 pyproject.toml 中 readme 字段声明的文件，一并拷贝
COPY SinBot/pyproject.toml SinBot/uv.lock ./README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ------------------------------- runtime -------------------------------
FROM python:3.12-slim-bookworm AS runtime

# DRIVER 必须在 nonebot.init() 之前确定，且受 nacos_config.PROTECTED_KEYS 保护，
# 容器无本地 .env 时由镜像提供；Nacos 下发同名键会被忽略。
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    DRIVER=~fastapi+~websockets

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends tzdata; \
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime; \
    echo "$TZ" > /etc/timezone; \
    rm -rf /var/lib/apt/lists/*; \
    useradd --create-home --uid 10001 --shell /bin/bash app; \
    mkdir -p /app; \
    chown -R app:app /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app SinBot/ /app/

USER app
WORKDIR /app

# 无状态镜像：业务数据全部来自数据中台，容器内不落库，故不声明任何 VOLUME。
# 机器人是 OneBot V11 反向 WS 客户端，主动外连协议端，自身不监听端口，故不 EXPOSE。
# 不用 nb run：nb-cli 会引入额外初始化与潜在交互，直接跑 bot.py 更可控。
CMD ["python", "bot.py"]
