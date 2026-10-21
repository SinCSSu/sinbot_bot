from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeamInfoVo(BaseModel):
    """后端返回的团队信息（响应 ``data`` 的字段，snake_case 对齐）。

    必须是带字段注解的 pydantic 模型：:func:`~sinbot.plugins.team_manager.api.codec.decode_payload`
    靠这些注解把响应 JSON 装成对象，后端多给的字段由 ``extra="ignore"`` 丢弃。
    """

    model_config = ConfigDict(extra="ignore")

    team_id: int | None = None
    team_name: str | None = None
    group_number: str | None = None
    dungeon: str | None = None
    comment: str | None = None
    start_time: datetime | None = None
    overtime_time: datetime | None = None
    limit_method: int | None = None
    locker: str | None = None
    salary: int | None = None
    create_by: str | None = None
    team_no : int | None = None

