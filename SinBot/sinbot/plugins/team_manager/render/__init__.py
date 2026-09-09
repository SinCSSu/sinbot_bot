"""团队阵容面板渲染能力包。

- Pillow 按旧 bot 图片原样复刻"五列网格"阵容图（外功列 0/1、内功列 2/3、
  坦/奶/未知列 4），数据由 DAO 查询，输出 PNG bytes。

入口函数见 ``panel_service``；本包不主动向群发送消息，发送交由调用方
"""
from .panel_service import render_team_panel_for_team  # noqa: F401

__all__ = [
    "render_team_panel_for_team",
]
