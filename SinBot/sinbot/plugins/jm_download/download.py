from pathlib import Path
from jmcomic import Feature, DownloadResult, JmAlbumDetail
from nonebot.adapters.onebot.v11 import MessageSegment, Bot
from nonebot.adapters import Event
from nonebot import logger
from nonebot.plugin.on import on_startswith
import jmcomic
import base64
import hashlib
import uuid

download_path = Path(__file__).resolve().parent / "download_path"

downloader = on_startswith("/jm")

CHUNK_SIZE = 1024 * 1024  # 1MB/片（SnowLuma 上限 32MB/片）
FILE_RETENTION_MS = 30 * 60 * 1000  # 远端保留 30 分钟（默认只有 5 分钟，32MB 不够用）
MAX_CHUNK_RETRY = 3


async def push_file_to_remote(bot: Bot, file: Path) -> str:
    """用 upload_file_stream 把本地文件推到远端协议端，返回它在远端的本地路径。"""
    data = file.read_bytes()
    total_size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    stream_id = uuid.uuid4().hex  # 白名单只允许 [A-Za-z0-9_-]，纯 hex 最安全

    chunks = [data[i:i + CHUNK_SIZE] for i in range(0, total_size, CHUNK_SIZE)]
    if not chunks:  # 空文件兜底，否则 total_chunks=0 会被拒
        chunks = [b""]
    total_chunks = len(chunks)

    logger.info(f"jm 流式上传: {file.name}, {total_size} 字节, {total_chunks} 片")

    for index, chunk in enumerate(chunks):
        params = {
            "stream_id": stream_id,
            "chunk_data": base64.b64encode(chunk).decode(),
            "chunk_index": index,
            "total_chunks": total_chunks,
            "file_size": total_size,
            "expected_sha256": sha256,
            "filename": file.name,
            "file_retention": FILE_RETENTION_MS,
        }
        # 重复分片在服务端是幂等的（同 index 直接返回 chunk_received），可安全重试
        for attempt in range(MAX_CHUNK_RETRY):
            try:
                await bot.call_api("upload_file_stream", **params)
                break
            except Exception as e:
                if attempt == MAX_CHUNK_RETRY - 1:
                    raise
                logger.warning(f"jm 分片 {index} 第 {attempt + 1} 次失败，重试: {e!r}")
        if (index + 1) % 8 == 0 or index + 1 == total_chunks:
            logger.info(f"jm 分片进度 {index + 1}/{total_chunks}")

    result = await bot.call_api(
        "upload_file_stream",
        stream_id=stream_id,
        is_complete=True,
    )
    if not result or result.get("status") != "file_complete":
        raise RuntimeError(f"远端合并文件失败: {result}")

    remote_path = result["file_path"]
    logger.info(f"jm 远端就绪: {remote_path} ({result.get('file_size')} 字节)")
    return remote_path


@downloader.handle()
async def jm_downloader(bot: Bot, message: Event):
    jm_number = message.get_plaintext().strip().removeprefix("/jm").strip()
    logger.info(f"开始下载jm:{jm_number}")

    if not jm_number.isdecimal():
        await downloader.finish("请输入正确的jm号")
    await downloader.send("下载中，请稍后")
    result: DownloadResult = await jmcomic.download_album_async(jm_number, extra=Feature.export_pdf(
        pdf_dir=str(download_path),
        filename_rule='Aid',
        delete_original_file=True,
    ))
    pdf_filepath_list = result.manifest.get_export_filepath_list('pdf')
    if not pdf_filepath_list:
        await downloader.finish("下载失败")
    pdf = Path(pdf_filepath_list[0])
    if not pdf.exists():
        await downloader.finish("pdf保存失败")

    try:
        remote_path = await push_file_to_remote(bot, pdf)
    except Exception as e:
        logger.error(f"jm 流式上传失败: {e!r}")
        await downloader.finish(f"文件上传失败: {e}")

    last_error = None
    for candidate in (remote_path, f"file://{remote_path}"):
        try:
            await downloader.send(MessageSegment("file", {
                "file": candidate,
                "name": f"{jm_number}.pdf",
            }))
            last_error = None
            break
        except Exception as e:
            last_error = e
            logger.warning(f"jm 以 {candidate} 发送失败: {e!r}")

    if last_error is not None:
        await downloader.finish(f"文件已上传到远端，但发送失败: {last_error}")
