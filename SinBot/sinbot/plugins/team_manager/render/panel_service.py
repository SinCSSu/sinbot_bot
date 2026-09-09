"""团队阵容面板渲染服务（Pillow，复刻旧 bot 图片）。

数据流：``Team`` -> 查全部未删除成员 -> 批量查 ``Specialization`` 映射 ->
分桶（内/外/坦/奶/未知）-> 分列成五列列表（``_layout_columns``）->
Pillow 按列绘制五列网格阵容图 -> 返回 PNG bytes。

版式以 ``SinBot/old_bot/img.py::GetImg`` 为蓝本原样复刻（五列网格：
列 0/1 外功、列 2/3 内功、列 4 坦/奶/未知顺排），布局常量与旧图一致。
某群组列高超过 5 行时会触发均衡（溢出补空，见 ``_layout_columns``），
使五列高度差尽量最小，避免单列过长拉高整图。

说明：
- 心法大类：spec_type 1=内功 2=外功 3=坦 4=奶（用户新定语义）。
- 心法图标目录 ``resource/icon/``，表中 ``icon_path`` 仅存文件名。
- 渲染字体唯一来源 ``resource/font/msyh.ttc``（用户自行提供），
  缺失时会抛出带中文指引的 ``FileNotFoundError``。
- 双修判定：``member.sub_spec`` 为真值（非 0/None）即画副修小圆；
  副修心法缺失/与主心法重复时跳过副修绘制并容错。
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from nonebot import logger

from sinbot.plugins.team_manager.dao import member_dao, spec_dao
from sinbot.plugins.team_manager.model.entity.member import Member
from sinbot.plugins.team_manager.model.entity.team import Team

# 心法大类（新语义）：1=内功 2=外功 3=坦(T) 4=奶
TYPE_INTERNAL = 1
TYPE_EXTERNAL = 2
TYPE_TANK = 3
TYPE_HEALER = 4

# 未识别/缺失心法统一归入未知桶，追加到列 4 尾部，避免丢人
TYPE_UNKNOWN = 0

MAX_NAME_LEN = 6  # 对齐旧图：昵称超过 6 字截断

FALLBACK_COLOR = 0xA6A6A6  # 心法缺失时的灰色兜底

RESOURCE_DIR = Path(__file__).resolve().parent.parent / "resource"
FONT_DIR = RESOURCE_DIR / "font"
FONT_NAME = "msyh.ttc"
FONT_PATH = FONT_DIR / FONT_NAME  # 渲染字体唯一来源
ICON_DIR = RESOURCE_DIR / "icon"

# ---- 旧图布局常量（原样保留，勿"顺手优化"）----
boxLength = 200
boxHeight = 50
startX = 100
startY = 116

WEEK_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 缓存：进程级懒加载字体与解码后的图标（图标负缓存为 None）
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}
_ICON_CACHE: dict[str, Image.Image | None] = {}


# ---------------------------------------------------------------------------
# 资源加载
# ---------------------------------------------------------------------------
def _ensure_font() -> Path:
    """校验字体文件存在；缺失时给出可操作的报错。"""
    if not FONT_PATH.is_file():
        raise FileNotFoundError(
            f"缺少渲染字体文件：{FONT_PATH}\n"
            f"请将 msyh.ttc（或其它合法中文字体）复制到 {FONT_DIR}/ 目录后重启。"
        )
    return FONT_PATH


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """按字号懒加载 msyh（index=1，与旧图一致）；字体缺失抛清晰异常。"""
    cached = _FONT_CACHE.get(size)
    if cached is not None:
        return cached
    font_path = _ensure_font()
    try:
        cached = ImageFont.truetype(str(font_path), size, index=1)
    except OSError as exc:
        raise FileNotFoundError(
            f"无法加载渲染字体：{font_path}\n"
            f"请确认文件未被占用/损坏，或替换为合法 ttf/ttc 字体后重启。"
        ) from exc
    _FONT_CACHE[size] = cached
    return cached


def _load_icon(filename: str | None) -> Image.Image | None:
    """按文件名读取心法图标为 RGBA 图；缺失/空名返回 None（负缓存）。"""
    if not filename:
        return None
    key = Path(filename).name  # 防御历史脏数据（如带目录分隔符）
    if key not in _ICON_CACHE:
        icon_path = ICON_DIR / key
        if not icon_path.is_file():
            logger.warning(f"心法图标缺失，跳过该图标渲染：{icon_path}")
            _ICON_CACHE[key] = None
        else:
            try:
                with Image.open(icon_path) as src:
                    _ICON_CACHE[key] = src.convert("RGBA")
            except OSError:
                logger.exception(f"心法图标解码失败，跳过该图标渲染：{icon_path}")
                _ICON_CACHE[key] = None
    return _ICON_CACHE[key]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _rgb(color: int) -> tuple[int, int, int]:
    """0xRRGGBB 整数 -> (r, g, b)。"""
    c = int(color or 0) & 0xFFFFFF
    return (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF


def _cut_name(name: str) -> str:
    """对齐旧图：昵称超过 6 字截断。"""
    if len(name) > MAX_NAME_LEN:
        return name[:MAX_NAME_LEN]
    return name


def _text_size(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int]:
    """替代已废弃的 ImageFont.getsize：返回 (宽, 高)。空串返回 (0, 0)。"""
    if not text:
        return 0, 0
    bbox = font.getbbox(text)
    return int(font.getlength(text)), int(bbox[3] - bbox[1])


def _format_start_time(start_time: datetime | None) -> str:
    """旧 GetDate 风格：'周三 09月09日 20:05'（不用新版 date_utils 文案）。"""
    if start_time is None:
        return ""
    date_str = WEEK_CN[start_time.weekday()] + " "
    date_str += start_time.strftime("%m月%d日 %H:%M")
    return date_str


def _build_title(team: Team) -> str:
    """顶部标题：team_name + dungeon；dungeon 为空或与 team_name 相同时只显示一次。"""
    name = (team.team_name or "").strip()
    dungeon = (team.dungeon or "").strip()
    if not dungeon or dungeon == name:
        return name or "未命名团队"
    return f"{name} {dungeon}"


def _team_label(team_id: int, team_no: int | None) -> str:
    """信息行前缀：优先显示该团在"当前在开团队"中的序号，缺省回退库内团队 ID。"""
    if team_no:
        return f"团队No：{team_no}"
    return f"团队ID:{team_id}"


# ---------------------------------------------------------------------------
# 旧图绘制逻辑移植（GetImg / DrawRectangal）
# ---------------------------------------------------------------------------
def _draw_cell(
    img: Image.Image,
    drawer: ImageDraw.ImageDraw,
    x: int,
    y: int,
    member: dict,
) -> None:
    """复刻旧 DrawRectangal：心法色块 + 黑边框 + 昵称截 6 字 + 主图标圆 + 双修副圆。"""
    # 心法色块
    drawer.rectangle(
        (
            startX + x * boxLength,
            startY + (boxHeight / 2) + y * boxHeight,
            startX + (x + 1) * boxLength,
            startY + (boxHeight / 2) + (y + 1) * boxHeight,
        ),
        fill=member["color"],
        outline=(0, 0, 0),
        width=1,
    )

    # 昵称（黑字，>6 字截断）
    name = _cut_name(member["name"])
    drawer.text(
        (
            startX + (0.3 + x) * boxLength,
            startY + (boxHeight / 2) + (y + 0.25) * boxHeight,
        ),
        name,
        font=_get_font(20),
        fill=0x000000,
    )

    r = boxLength / 10  # 20

    # 主心法黑底圆
    drawer.ellipse(
        (
            startX + x * boxLength + (boxLength * 0.05),
            startY + (boxHeight / 2) + y * boxHeight + (boxHeight / 2 - r),
            startX + x * boxLength + (boxLength * 0.05) + 2 * r,
            startY + (boxHeight / 2) + y * boxHeight + (boxHeight / 2 + r),
        ),
        fill=0x000000,
        outline=None,
    )
    # 主心法图标（36px）
    logo = _load_icon(member["main_icon"])
    if logo is not None:
        logo = logo.resize((int(r * 1.8), int(r * 1.8)), Image.Resampling.LANCZOS)
        alpha = logo.split()[3]
        img.paste(
            logo,
            (
                int(startX + x * boxLength + (boxLength * 0.25 - 1.9 * r)),
                int(startY + (boxHeight / 2) + y * boxHeight + (boxHeight / 2 - 0.9 * r)),
            ),
            mask=alpha,
        )

    # 双修：白描边小圆 + 副修图标（18px）
    if member.get("sub_icon"):
        drawer.ellipse(
            (
                startX + x * boxLength + (boxLength * 0.25) - r,
                startY + (boxHeight / 2) + y * boxHeight + (boxHeight / 2),
                startX + x * boxLength + (boxLength * 0.05) + 2 * r,
                startY + (boxHeight / 2) + y * boxHeight + (boxHeight / 2 + r),
            ),
            fill=0x000000,
            outline=0xFFFFFF,
            width=1,
        )
        sub_logo = _load_icon(member["sub_icon"])
        if sub_logo is not None:
            sub_logo = sub_logo.resize((int(r * 0.9), int(r * 0.9)), Image.Resampling.LANCZOS)
            sub_alpha = sub_logo.split()[3]
            img.paste(
                sub_logo,
                (
                    int(startX + x * boxLength + (boxLength * 0.25 - 0.9 * r)),
                    int(startY + (boxHeight / 2) + y * boxHeight + (boxHeight / 2 + 0.1 * r)),
                ),
                mask=sub_alpha,
            )


def _layout_columns(
    external: list[dict],
    internal: list[dict],
    col4: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """分列工具：把成员 cell 布局成五列，返回 (列0, 列1, ..., 列4) 五个列表。

    两阶段策略：
    1. 组内优先（对齐旧图）：外功 → 列 0/1 按报名序左右交替、内功 → 列 2/3
       同上、坦/奶/未知 → 列 4 顺排，保证同群组成员基本相邻。
    2. 溢出补空：仅当任一群组列高超过 5 行（默认一屏容量）时触发均衡——
       反复把当前最高列的末尾成员补到当前最矮列的末尾（始终"接列尾"，
       不改变列内既有先后次序），直到五列高度差 ≤ 1。
       此时五列最大行数 = ceil(总人数 / 5)，为该布局可达到的最小值；
       未超 5 行则维持阶段 1 的分组原样，不打扰常规版面。

    绘图层只消费返回的五个列表（逐列、每列按行号顺次绘制），
    与"谁归哪个桶"完全解耦，后续扩展新布局策略仅需替换本函数。
    """
    # 阶段 1：按群组映射到天然列（组内优先）
    cols = [
        external[0::2],  # 列 0：外功偶位成员
        external[1::2],  # 列 1：外功奇位成员
        internal[0::2],  # 列 2：内功偶位成员
        internal[1::2],  # 列 3：内功奇位成员
        list(col4),      # 列 4：坦/奶/未知 顺排
    ]
    if max(len(c) for c in cols) <= 5:
        return cols[0], cols[1], cols[2], cols[3], cols[4]

    # 阶段 2：溢出补空——最高列尾部成员逐人挪到最矮列尾，直到高度差 ≤ 1
    while True:
        high = max(range(len(cols)), key=lambda i: len(cols[i]))
        low = min(range(len(cols)), key=lambda i: len(cols[i]))
        if len(cols[high]) - len(cols[low]) <= 1:
            break
        cols[low].append(cols[high].pop())
    return cols[0], cols[1], cols[2], cols[3], cols[4]


def _render_panel_sync(
    title: str,
    team_label: str,
    start_time: datetime | None,
    comment: str,
    columns: tuple[list[dict], list[dict], list[dict], list[dict], list[dict]],
) -> bytes:
    """同步绘制五列网格阵容图（放入线程执行），返回 PNG bytes。

    :param team_label: 信息行团队标识文案，如 "当前开团序号:3" / "团队ID:xxx"。
    :param columns: ``_layout_columns`` 产出的五列成员列表，逐列逐行绘制。
    """
    canvas_length = 1200
    canvas_height = 480

    # 超过固定 5 行时动态加高（max_rows 取五列中最长列，对齐旧图触发条件）
    max_rows = max(len(col) for col in columns)
    if max_rows > 5:
        canvas_height += (max_rows - 5) * boxHeight

    img = Image.new("RGB", (canvas_length, canvas_height), (255, 255, 255))
    drawer = ImageDraw.Draw(img)

    # ---- 标题（40 号，超宽左对齐否则居中）----
    title_font = _get_font(40)
    title_w, _ = _text_size(title_font, title)
    if title_w > canvas_length:
        drawer.text((0, 10), title, fill=0x000000, font=title_font)
    else:
        drawer.text(
            ((canvas_length - title_w) // 2, 10),
            title,
            fill=0x000000,
            font=title_font,
        )

    # ---- 信息行：团队标识（开团序号/库内 ID）+ 开团时间 + 备注 ----
    font = _get_font(20)
    date_info = f"（{team_label}） " + _format_start_time(start_time)
    time_w, time_h = _text_size(font, date_info)
    team_w, team_h = _text_size(font, comment)

    if team_w + time_w < boxLength * 5:
        drawer.text((startX, startY - time_h - 5), date_info, fill=0x000000, font=font)
        drawer.text(
            (startX + boxLength * 5 - team_w, startY - time_h - 5),
            comment,
            fill=0x000000,
            font=font,
        )
    else:
        drawer.text((startX, startY - time_h - 5), date_info, fill=0x000000, font=font)
        drawer.text(
            (startX + time_w + 5, startY - team_h - 5),
            comment,
            fill=0x000000,
            font=font,
        )

    # ---- 表头：5 列白底黑框 + 列号 ----
    for i in range(5):
        drawer.rectangle(
            (
                startX + (boxLength * i),
                startY,
                startX + boxLength * (i + 1),
                startY + boxHeight / 2,
            ),
            fill=(255, 255, 255),
            outline=(0, 0, 0),
            width=1,
        )
        drawer.text(
            (startX + (boxLength * (i + 0.5)), startY),
            str(i + 1),
            fill=(0, 0, 0),
            font=font,
        )

    # ---- 按列绘制：外功列 0/1、内功列 2/3、坦/奶/未知列 4 顺排 ----
    for col_index, column in enumerate(columns):
        for row_index, cell in enumerate(column):
            _draw_cell(img, drawer, col_index, row_index, cell)

    # ---- 输出 PNG bytes（不落盘，无副作用）----
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 对外入口：数据查询 + 组装 + Pillow 渲染
# ---------------------------------------------------------------------------
def _fallback_spec(spec_id: int):
    """心法查询缺失时的兜底对象（不写库，仅用于版面占位）。"""
    return type(
        "FallbackSpec",
        (),
        {
            "spec_id": spec_id,
            "spec_name": "未知心法",
            "color": FALLBACK_COLOR,
            "icon_path": "",
            "spec_type": TYPE_UNKNOWN,
        },
    )()


def _build_cell_data(member: Member, spec, sub_spec) -> dict:
    """把单个成员组装成绘图 cell dict（对齐旧 GetImg 的 member dict 语义）。

    双修：``sub_spec`` 为真值、且副修心法存在且不同于主心法时才画副修；
    副修与主相同或查不到副修记录时仅保留主心法（容错不整图失败）。
    """
    color = int(getattr(spec, "color", 0) or 0) or FALLBACK_COLOR
    main_icon = getattr(spec, "icon_path", "") or ""
    sub_icon = ""

    if member.sub_spec and sub_spec is not None:
        sub_id = int(getattr(sub_spec, "spec_id", 0) or 0)
        main_id = int(getattr(spec, "spec_id", 0) or 0)
        if sub_id != main_id:
            sub_icon = getattr(sub_spec, "icon_path", "") or ""

    return {
        "name": member.member_name,
        "color": _rgb(color),
        "main_icon": main_icon,
        "sub_icon": sub_icon,
    }


async def _collect_members(
    team: Team,
) -> tuple[dict[int, list[dict]], str, datetime | None, str]:
    """查询成员与心法映射，完成分桶并返回绘图所需全部数据。

    返回 (buckets, title, start_time, comment)；
    buckets: {TYPE_EXTERNAL/TYPE_INTERNAL/TYPE_TANK/TYPE_HEALER/TYPE_UNKNOWN: [cell, ...]}
    """
    members = await member_dao.get_members_by_team_id(team.team_id)

    main_ids = {m.specialization for m in members if m.specialization}
    sub_ids = {m.sub_spec for m in members if m.sub_spec}
    spec_map = await spec_dao.get_specs_by_ids(main_ids | sub_ids)

    buckets: dict[int, list[dict]] = {
        TYPE_EXTERNAL: [],
        TYPE_INTERNAL: [],
        TYPE_TANK: [],
        TYPE_HEALER: [],
        TYPE_UNKNOWN: [],
    }
    for member in members:
        spec = spec_map.get(member.specialization)
        if spec is None:
            logger.warning(
                f"成员心法未匹配到记录，归入未知桶：member={member.member_name} "
                f"spec_id={member.specialization}"
            )
            spec = _fallback_spec(member.specialization)
        spec_type = int(getattr(spec, "spec_type", TYPE_UNKNOWN) or TYPE_UNKNOWN)
        if spec_type not in buckets:
            logger.warning(
                f"成员心法 spec_type 不在 1-4，归入未知桶：spec_id={member.specialization} "
                f"spec_type={spec_type}"
            )
            spec_type = TYPE_UNKNOWN
        sub_spec = spec_map.get(member.sub_spec) if member.sub_spec else None
        buckets[spec_type].append(_build_cell_data(member, spec, sub_spec))

    return buckets, _build_title(team), team.start_time, (team.comment or "").strip()


async def render_team_panel_for_team(team: Team, team_no: int | None = None) -> bytes:
    """按旧 bot 风格绘制五列网格阵容图，返回 PNG bytes。

    :param team: 团队实体（无需预取成员）。
    :param team_no: 该团在"当前在开团队"中的序号，信息行显示为
        "（当前开团序号:N）"；缺省时回退显示库内团队 ID。
    """
    buckets, title, start_time, comment = await _collect_members(team)
    # 列 4 = 坦 + 奶 + 未知 顺排；具体五列排布交给 _layout_columns
    col4 = buckets[TYPE_TANK] + buckets[TYPE_HEALER] + buckets[TYPE_UNKNOWN]
    columns = _layout_columns(
        buckets[TYPE_EXTERNAL],
        buckets[TYPE_INTERNAL],
        col4,
    )

    return await asyncio.to_thread(
        _render_panel_sync,
        title,
        _team_label(team.team_id, team_no),
        start_time,
        comment,
        columns,
    )
