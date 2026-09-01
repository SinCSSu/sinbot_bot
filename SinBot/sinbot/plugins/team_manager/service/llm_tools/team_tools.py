from sinbot.plugins.team_manager.model.vo.create_team_vo import CreateTeamVo
from sinbot.plugins.team_manager.service.llm_service import llm_client


@llm_client.register()
def create_team_by_llm(
    error: str,  # noqa: ARG001 - LLM 约定参数，函数体内不使用
    team_name: str,
    comment: str,
    start_time: str,
    limit: bool,  # noqa: FBT001 - LLM 工具签名的 bool 参数为接口约定
) -> CreateTeamVo:
    """
    将用户的自然语言描述解析为结构化的团队信息，但不写入数据库
    【功能定位】
        这是一个数据录入工具，将非结构化的团队信息解析为结构化的团队信息
    【适用场景】
        - 用户通过自然语言描述创建团队时使用
    【目标结构】
        - team_name (varchar) :团队名称 (必填)
        - comment (varchar) : 团队描述
        - start_time (timestamp) : 团队开始时间(必填)
        - limit (bool) : 是否有限制
    【字段解析规则】
    1. 日期时间识别：
        - 具体的时间是必须的，需要精确到小时，如果没有精确到小时则返回null
        - "明天" → 当前日期 + 1 天
        - "下周一" → 下一个周一
        - "下午3点" → 15:00
        - "3点半" → 15:30
        - 如果只提时间没提日期，默认今天
    2. 团队名称识别
        - 团队名称中一般包含 “yx”，“英雄”,"普通","pt"等难度字段，有可能包含人数或者副本名称（或者简写） 比如 “25yx”，“25pt弓”，“yx”
    3.限制识别
        - 如果识别到 "无限制" "无人数限制" 这样的字段，则limit返回false，如果没有解析到限制相关的字段，则limit 返回 true
    4.团队描述识别
        - 在去掉了 开团指令(如 开团 开 创建团队等)、团队名称、团队时间、团队限制之后的描述性文本记为团队描述，比如：“今晚有事别来”，“不要鸽子精”
    【数据清洗规则】
        - 所有文本字段去除首尾空格
        - 时间统一转为 YYYY-MM-DD HH24:mi:ss格式
    【异常处理】
        - 如果缺少团队名称 开团时间 则在返回的error字段中列出
        - 如果开团时间没有精确到小时 则在返回的error 字段中列出
        - 如果识别到多个冲突信息（如既说下午五点又说下午六点），取后提到的值
    【实例】（假设当前时间为 2026-09-01 15:00:00 星期二）
        输入：明晚八点开25yx
        输出：
        ｛
            team_name:"25yx",
            comment :null,
            start_time :"2026-09-02 20:00:00",
            limit: true,
            error:[]
        ｝

        输入：开团 晚上九点普通
        输出：
        ｛
            team_name:"普通",
            comment :null,
            start_time :"2026-09-01 21:00:00",
            limit: true,
            error:[]
        ｝

        输入：开团 周三晚上六点 yx 教学团 无限制
        输出：
        ｛
            team_name:"yx",
            comment :“教学团”,
            start_time :"2026-09-02 18:00:00",
            limit: false,
            error:[]
        ｝

        输入：开团 明天晚上 yx
        输出：
        ｛
            team_name:"yx",
            comment : null,
            start_time : null,
            limit: true,
            error:["start_time"]
        ｝
    """
    create_team_vo = CreateTeamVo()
    create_team_vo.team_name = team_name
    create_team_vo.comment = comment
    create_team_vo.start_time = start_time
    create_team_vo.limit_method = limit
    return create_team_vo
