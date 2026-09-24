"""端点清单。

这是**唯一**需要按真实后端契约校准的文件：改这里，业务代码不用动。

当前路径是按 dao 现有 7 个方法的语义反推的 REST 风格占位，
后端契约确认后逐条替换即可（支持 ``{param}`` 路径模板）。
"""

from __future__ import annotations

from .endpoint import EndpointRegistry

DEFAULT_ENDPOINTS = EndpointRegistry.from_mapping(
    {
        # ---------------- team ----------------
        # team_dao.insert_new_team
        "team.create": "POST /team/createTeam",
        # team_dao.get_available_team_by_group_id
        "team.list_available": "GET /team/getAvailableTeamsByGroupNumber/{groupNumber}",
        "team.get": "GET /teams/{team_id}",
        # ---------------- member ----------------
        # member_dao.get_members_by_team_id
        "member.list_by_team": "GET /teams/{team_id}/members",
        # member_dao.get_member_by_team_id_and_member_name
        "member.get_by_name": "GET /teams/{team_id}/members/{member_name}",
        # member_dao.insert_new_member
        "member.create": "POST /teams/{team_id}/members",
        # ---------------- specialization ----------------
        # spec_dao.get_spec_id_by_name_or_nickname
        "spec.resolve": "GET /specializations/resolve",
        # spec_dao.get_mult_spec_id_by_main_id
        "spec.relate": "GET /specializations/{spec_id}/relate",
        # spec_dao.get_specs_by_ids
        "spec.batch": "GET /specializations",
    }
)
