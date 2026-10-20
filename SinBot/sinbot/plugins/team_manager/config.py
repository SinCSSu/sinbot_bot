import json

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def parse_api_keys(value: object) -> list[str]:
    """把各种写法的 API Key 配置归一成去重后的字符串列表。

    兼容三种来源（Nacos 里同一份配置还有别的应用在用，不能强制改格式）：

    * YAML 列表：``api-keys: ['k1', 'k2']`` -> ``["k1", "k2"]``
    * JSON 串：环境变量被扁平化后的 ``'["k1", "k2"]'`` -> ``["k1", "k2"]``
    * 单个字符串：``api_keys: k1`` / ``TEAM_MANAGER__API_KEYS=k1`` -> ``["k1"]``
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                return parse_api_keys(json.loads(text))
            except ValueError:
                return [text]
        return [text]
    if isinstance(value, (list, tuple, set)):
        keys: list[str] = []
        for item in value:
            for key in parse_api_keys(item):
                if key not in keys:
                    keys.append(key)
        return keys
    return [str(value)]


class ScopedConfig(BaseModel):
    # 注意：以下字段全部由 Nacos 下发（sinbot-team-manager.properties），
    # 通过 TEAM_MANAGER__<字段名> 环境变量注入，本地 .env 不再维护。

    model_config = ConfigDict(populate_by_name=True)

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
    # 静态 API Key 列表（Nacos 里写作 team_manager.api-keys）。
    # 兼容 ``api-keys`` / ``api_keys`` 两种键名与「列表 / JSON 串 / 单字符串」三种写法；
    # 请求头只携带一个值，实际使用列表中的第一个。
    api_keys: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("api_keys", "api-keys", "api_key", "api-key"),
    )
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

    @field_validator("api_keys", mode="before")
    @classmethod
    def _normalize_api_keys(cls, value: object) -> list[str]:
        return parse_api_keys(value)


class Config(BaseModel):
    """Plugin Config Here"""
    team_manager: ScopedConfig
