from dataclasses import dataclass
import json


@dataclass
class JoinTeamVo:
    def __init__(self) -> None:
        self.team_id: int | None = None
        self.member_name: str | None = None
        self.member_spec: int | None = None
        self.sub_spec: int | None = None


    def __str__(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)
