from pydantic import BaseModel


class ScopedConfig(BaseModel):
    # 注意：以下字段全部由 Nacos 下发（sinbot-team-manager.properties），
    # 通过 TEAM_MANAGER__<字段名> 环境变量注入，本地 .env 不再维护。

    # OpenAI 兼容接口地址，留空则使用 OpenAI 官方地址
    llm_base_url: str = ""
    # API Key，留空时使用占位符构造（在 Nacos 配置 team_manager__llm_api_key）
    llm_api_key: str = ""
    # 默认对话模型名
    llm_model: str = "gpt-4o-mini"
    # 自动工具调用循环的最大轮数，防止死循环
    llm_max_turns: int = 10

    # ---------- 外部 API（数据持久化后端）----------
    # 后端根地址，例如 https://api.example.com；留空时所有调用直接失败
    api_base_url: str = ""
    # 静态 API Key（在 Nacos 配置 team_manager__api_key）
    api_key: str = ""
    # 携带 API Key 的请求头名
    api_key_header: str = "X-API-Key"
    # 单次请求超时（秒）
    api_timeout: float = 10.0
    # 传输层失败 / 5xx / 429 的最大重试次数（0 表示不重试）
    api_max_retries: int = 2
    # 重试退避基数（秒），第 n 次等待 backoff * 2**n
    api_retry_backoff: float = 0.5
    # 视为成功的业务码，逗号分隔；留空则使用默认集合 0/200/ok/success/true
    api_success_codes: str = ""

class Config(BaseModel):
    """Plugin Config Here"""
    team_manager: ScopedConfig
