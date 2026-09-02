import re
from datetime import datetime

import jionlp

# 匹配明确到小时的表达，例如：20:00、八点、8点半、下午3点
_HOUR_SPECIFIC_RE = re.compile(
    r"("
    r"\d{1,2}\s*[:：]\s*\d{1,2}"  # 20:00、8:30
    r"|[0-9一二三四五六七八九十两]+\s*点"  # 八点、8点半、十一点
    r")"
)


def is_hour_specific(date_str: str) -> bool:
    """输入是否已精确到小时，如「今晚」「明天」这类则返回 False。"""
    return bool(_HOUR_SPECIFIC_RE.search(date_str))


def parse_date_from_input_with_parser(date_str: str) -> datetime | None:
    try:
        time = jionlp.parse_time(
            date_str,
            time_base=datetime.now(),  # noqa: DTZ005 - 无时区约定，time_base 与解析结果一致
            time_type="time_point",
        ).get("time")[0]
    except ValueError:
        return None
    return time
