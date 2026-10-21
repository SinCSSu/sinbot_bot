from sinbot.plugins.team_manager.model.vo.member_info_vo import MemberInfoVo
from sinbot.plugins.team_manager.model.vo.team_info_vo import TeamInfoVo


class TeamDetailVo(TeamInfoVo):
    members: list[MemberInfoVo] | None = None
    team_no: int | None = None
