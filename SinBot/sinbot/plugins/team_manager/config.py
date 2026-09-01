from pydantic import BaseModel


class ScopedConfig(BaseModel):
    # OpenAI 兼容接口地址，留空则使用 OpenAI 官方地址
    llm_base_url: str = ""
    # API Key，留空时使用占位符构造（需在 .env 配置 team_manager__llm_api_key）
    llm_api_key: str = ""
    # 默认对话模型名
    llm_model: str = "gpt-4o-mini"
    # 自动工具调用循环的最大轮数，防止死循环
    llm_max_turns: int = 10

class Config(BaseModel):
    """Plugin Config Here"""
    team_manager: ScopedConfig
