from nonebot import on_command, rule
from nonebot import on_startswith
from nonebot.rule import to_me

create_team = on_startswith(("开团", "创建团队", "开始团队"), rule=to_me())

view_all_team = on_startswith(("所有团队","当前团队"),rule = to_me())

view_team = on_startswith(("查询团队","查团","查看团队"),rule = to_me())