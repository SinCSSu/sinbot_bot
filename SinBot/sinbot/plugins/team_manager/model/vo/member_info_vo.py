from pydantic import BaseModel, ConfigDict


class MemberInfoVo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    member_id: int | None = None
    team_id: int | None = None
    member_qq_number: str | None = None
    member_name: str | None = None
    specialization: int | None = None
    sub_spec: int | None = None
