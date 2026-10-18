"""外部 API 契约。

这是**唯一**需要按真实后端契约校准的文件：改这里，业务代码不用动。

写法对标 Java 的 Feign 接口——一个类就是一组接口，一个方法就是一个端点：
- 路径里的 ``{xxx}`` 自动匹配同名方法参数
- ``@post(headers={"X-Foo": "{bar}"})`` 里的 ``{bar}`` 从路径参数或请求体字段取值
- VO / dataclass 参数自动摊平成 JSON body，返回注解自动解码成实体

当前路径是按 dao 现有方法的语义反推的 REST 风格占位，后端契约确认后逐条替换即可。
"""

from __future__ import annotations

from ..model.entity.member import Member
from ..model.entity.specialization import Specialization
from ..model.entity.team import Team
from ..model.vo.create_team_vo import CreateTeamVo
from ..model.vo.join_team_vo import JoinTeamVo
from .binding import get, post

__all__ = ["MemberApi", "SpecApi", "TeamApi"]


class TeamApi:
    """团队相关接口。"""

    @post(
        "/team/createTeam",
        headers={"X-Group-Number": "{group_number}", "X-Operator-Qq": "{created_by}"},
        datetime_format="%Y-%m-%d %H:%M:%S",
    )
    async def create(self, team: CreateTeamVo) -> None:
        """开团（对应 team_dao.insert_new_team）。"""

    @get("/team/getAvailableTeamsByGroupNumber/{group_number}")
    async def list_available(self, group_number: str) -> list[Team]:
        """查询群里仍在进行的团队（对应 team_dao.get_available_team_by_group_id）。"""

    @get("/teams/{team_id}")
    async def get(self, team_id: int) -> Team | None:
        """按 id 查单个团队。"""


class MemberApi:
    """团队成员相关接口。"""

    @get("/teams/{team_id}/members")
    async def list_by_team(self, team_id: int, delete_flag: str = "N") -> list[Member]:
        """按团队查未删除成员（对应 member_dao.get_members_by_team_id）。"""

    @get("/teams/{team_id}/members/{member_name}")
    async def get_by_name(self, team_id: int, member_name: str) -> Member | None:
        """按团队 + 成员名查，用于重复报团校验。"""

    @post("/teams/{team_id}/members")
    async def create(self, team_id: int, member: JoinTeamVo) -> None:
        """报名（对应 member_dao.insert_new_member）。"""


class SpecApi:
    """心法相关接口。"""

    @get("/specializations/resolve")
    async def resolve(self, name: str) -> int:
        """按名称或别名解析心法 id（对应 spec_dao.get_spec_id_by_name_or_nickname）。"""

    @get("/specializations/{spec_id}/relate")
    async def relate(self, spec_id: int) -> Specialization | None:
        """查关联心法（对应 spec_dao.get_mult_spec_id_by_main_id）。"""

    @get("/specializations")
    async def batch(self, spec_ids: list[int]) -> list[Specialization]:
        """批量查心法（对应 spec_dao.get_specs_by_ids）。"""
