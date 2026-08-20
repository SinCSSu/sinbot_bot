from datetime import datetime
import jionlp
from sqlalchemy import null


def parse_date_from_input_with_parser(date_str: str) -> datetime | None:
    try:
        time = jionlp.parse_time(date_str, time_base=datetime.now(), time_type='time_point').get("time")[0]
    except ValueError:
        return None
    return time
