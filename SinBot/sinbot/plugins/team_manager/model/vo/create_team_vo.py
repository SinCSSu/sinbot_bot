from __future__ import annotations

import datetime
import json


class CreateTeamVo:
    def __init__(self) -> None:
        self.team_name: str | None = None
        self.comment: str | None = None
        self.dungeon :str | None = None
        self.start_time: datetime.datetime | None = None
        self.limit_method: int | None = None
        self.group_number: str | None= None
        self.created_by: str | None=None

    def __str__(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)
