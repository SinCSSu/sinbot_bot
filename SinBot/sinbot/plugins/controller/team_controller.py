from nonebot import on_command
from nonebot import on_startswith
from nonebot.rule import to_me

create_team = on_startswith(("开团", "创建团队", "开始团队"), rule=to_me())
