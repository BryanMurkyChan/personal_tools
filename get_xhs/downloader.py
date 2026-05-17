"""小红书图片下载器。"""

import asyncio
import logging
from pathlib import Path

import httpx

from utils import ensure_dir

logger = logging.getLogger("xhs")


async def _download_single(
    client: httpx.AsyncClient,
    url: str,
    save_path: Path,
    index: int,
    total: int,
    max_retries: int = 2,
) -> bool:
    """下载单张图片（含重试）。"""
    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url, timeout=30.0)
            resp.raise_for_status()

            save_path.write_bytes(resp.content)

            # 验证是否为有效图片
            try:
                from PIL import Image
                from io import BytesIO
                img = Image.open(BytesIO(resp.content))
                img.verify()
            except Exception:
                logger.warning("[%d/%d] 文件不是有效图片: %s", index + 1, total, url[:60])
                return False

            logger.info("[%d/%d] 已下载: %s", index + 1, total, save_path.name)
            return True

        except Exception as e:
            if attempt < max_retries:
                logger.debug("[%d/%d] 下载失败，重试(%d/%d): %s", index + 1, total, attempt + 1, max_retries, e)
                await asyncio.sleep(3)
            else:
                logger.error("[%d/%d] 下载最终失败: %s", index + 1, total, url[:60])
    return False


async def download_images(
    image_urls: list[str],
    output_dir: Path,
    max_concurrent: int = 3,
) -> list[Path]:
    """并发下载多张图片。

    Args:
        image_urls: 图片URL列表
        output_dir: 输出目录
        max_concurrent: 最大并发数

    Returns:
        成功下载的文件路径列表
    """
    if not image_urls:
        logger.info("没有图片需要下载")
        return []

    ensure_dir(output_dir)
    semaphore = asyncio.Semaphore(max_concurrent)
    downloaded: list[Path] = []

    async def _download_with_semaphore(url: str, idx: int) -> None:
        async with semaphore:
            ext = ".jpg"
            if ".png" in url:
                ext = ".png"
            elif ".webp" in url:
                ext = ".webp"
            save_path = output_dir / f"{idx:03d}{ext}"
            success = await _download_single(
                client, url, save_path, idx, len(image_urls)
            )
            if success:
                downloaded.append(save_path)

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.xiaohongshu.com/",
        },
        follow_redirects=True,
    ) as client:
        tasks = [
            _download_with_semaphore(url, i)
            for i, url in enumerate(image_urls)
        ]
        await asyncio.gather(*tasks)

    logger.info("图片下载完成: %d/%d 张成功", len(downloaded), len(image_urls))
    return downloaded


def download_images_sync(
    image_urls: list[str],
    output_dir: Path,
    max_concurrent: int = 3,
) -> list[Path]:
    """同步包装器，方便在同步上下文调用。"""
    return asyncio.run(download_images(image_urls, output_dir, max_concurrent))
