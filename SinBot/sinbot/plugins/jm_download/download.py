from pathlib import Path
from jmcomic import Feature, DownloadResult, JmAlbumDetail
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.adapters import Event
from nonebot import logger
from nonebot.plugin.on import on_startswith
import jmcomic


download_path = Path(__file__).resolve().parent / "download_path"

downloader = on_startswith("/jm")

@downloader.handle()
async def jm_downloader(message:Event):
    jm_number = message.get_plaintext().strip().removeprefix("/jm").strip()
    logger.info(f"开始下载jm:{jm_number}")

    if not jm_number.isdecimal():
        await downloader.finish("请输入正确的jm号")
    await downloader.send("下载中，请稍后")
    result: DownloadResult = await jmcomic.download_album_async(jm_number,extra=Feature.export_pdf(
        pdf_dir = str(download_path),
        filename_rule='Atitle',
        delete_original_file=True,
    ))
    pdf_filepath_list = result.manifest.get_export_filepath_list('pdf')[0]

    msg_seg = MessageSegment(
        "file",
        {
            "file":"file:///" + pdf_filepath_list,
            "name":jm_number + ".zip"
        }
    )

    await downloader.finish(msg_seg)



