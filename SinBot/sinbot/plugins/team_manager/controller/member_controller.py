from nonebot import on_command
from nonebot import on_startswith
from nonebot.rule import to_me

join_team = on_startswith(("报团","加入团队","报名","抱团"),rule=to_me())

my_team = on_startswith(msg=("我报的团"),rule= to_me())