from dataclasses import dataclass
import json

@dataclass
class JoinTeamVo:
    def __init__(self) -> None:
        self.team_name: str | None = None
        self.team_id: str | None = None
        self.member_name: str | None = None
        self.member_spec: str | None = None
        self.mult_spec:str | None = None

    def __str__(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)