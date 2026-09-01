from __future__ import annotations

import datetime
import json


class CreateTeamVo:
    def __init__(self) -> None:
        self.team_name: str | None = None
        self.comment: str | None = None
        self.start_time: datetime.datetime | None = None
        self.limit_method: int | None = None
        self.create_by: str | None = None
        self.group_number: int | None = None

    def __str__(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)
