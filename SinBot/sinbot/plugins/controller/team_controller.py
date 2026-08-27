from nonebot import on_command
from nonebot import on_startswith
from nonebot.rule import to_me

create_team = on_startswith(("开团", "创建团队", "开始团队"), rule=to_me())

join_team = on_startswith(("报团","加入团队","报名","抱团"),rule=to_me())