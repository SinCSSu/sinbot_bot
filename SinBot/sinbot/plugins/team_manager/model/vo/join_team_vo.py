from dataclasses import dataclass
import json

@dataclass
class JoinTeamVo:
    def __init__(self) -> None:
        self.team_name: str | None = None
        self.team_id: int | None = None
        self.team_no : str | None = None
        self.member_name: str | None = None
        self.member_spec: int | None = None
        self.member_spec_input :str | None= None
        self.sub_spec:int | None = None
        self.group_number : str | None = None
        self.member_id : str | None = None

    def __str__(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)