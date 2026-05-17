#!/usr/bin/env python3
"""小红书帖子图文+评论获取工具 CLI入口。

用法:
  python main.py --url "https://www.xiaohongshu.com/explore/xxx"
  python main.py --note-id "67890abcdef" --xsec-token "xxx"
  python main.py --search "关键词" --count 20
  python main.py --cookie "your_cookie_string"
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from utils import (
    ensure_dir,
    extract_note_info_from_url,
    setup_logger,
)
from models import (
    PostData,
    NoteDetail,
    parse_note_from_api,
    parse_comments_from_api,
    parse_sub_comments_from_api,
)

logger: logging.Logger | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="小红书帖子图文+评论获取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --url "https://www.xiaohongshu.com/explore/xxx"
  python main.py --note-id "xxx" --xsec-token "xxx"
  python main.py --search "穿搭" --count 20
  python main.py --cookie "a1=xxx; web_session=yyy"
        """,
    )

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--url", help="小红书帖子完整URL")
    source_group.add_argument("--note-id", help="帖子ID")
    source_group.add_argument("--search", help="搜索关键词")

    parser.add_argument("--xsec-token", default="", help="xsec_token（与 --note-id 配合使用）")
    parser.add_argument("--cookie", default=None, help="Cookie字符串（a1=xxx; web_session=yyy; ...）")
    parser.add_argument("--count", type=int, default=20, help="搜索结果数量或最大评论数")
    parser.add_argument("--max-comments", type=int, default=0, help="最大评论获取数（0=不限）")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口（用于扫码登录）")
    parser.add_argument("--no-download", action="store_true", help="跳过图片下载")
    parser.add_argument("--output-dir", default="output", help="输出目录（默认: output）")

    return parser.parse_args()


async def fetch_all_comments(
    client,
    note_id: str,
    xsec_token: str,
    max_comments: int = 0,
    fetch_sub: bool = True,
) -> list:
    """获取帖子的全部评论（含子评论翻页）。

    Args:
        client: XHSClient实例
        note_id: 帖子ID
        xsec_token: 安全令牌
        max_comments: 最大评论数（0=不限）
        fetch_sub: 是否获取子评论

    Returns:
        评论列表（Comment模型）
    """
    from models import Comment

    all_comments: list[Comment] = []
    cursor = ""

    while True:
        if max_comments > 0 and len(all_comments) >= max_comments:
            break

        try:
            resp = await client.get_note_comments(note_id, xsec_token, cursor=cursor)
        except Exception as e:
            logger.error("获取评论失败: %s", e)
            break

        if resp.get("code") != 0:
            logger.warning("评论API返回错误: code=%d", resp.get("code", -1))
            break

        comments, next_cursor, has_more = parse_comments_from_api(resp)
        logger.info("获取到 %d 条评论 (cursor=%s, has_more=%s)", len(comments), cursor[:10] if cursor else "首页", has_more)

        for c in comments:
            # 获取子评论
            if fetch_sub and c.sub_comment_count > 0 and c.sub_comment_cursor:
                sub_comments = await fetch_sub_comments(
                    client, note_id, c.comment_id, xsec_token, c.sub_comment_cursor
                )
                c.sub_comments = sub_comments
            all_comments.append(c)

        if not has_more or not next_cursor:
            break
        cursor = next_cursor

    logger.info("共获取 %d 条评论", len(all_comments))
    return all_comments


async def fetch_sub_comments(
    client,
    note_id: str,
    root_comment_id: str,
    xsec_token: str,
    cursor: str,
) -> list:
    """获取某条评论的全部子评论。"""
    from models import Comment

    all_subs: list[Comment] = []

    while cursor:
        try:
            resp = await client.get_sub_comments(
                note_id, root_comment_id, xsec_token, cursor=cursor
            )
        except Exception as e:
            logger.error("获取子评论失败: %s", e)
            break

        if resp.get("code") != 0:
            break

        subs, next_cursor, has_more = parse_sub_comments_from_api(resp)
        all_subs.extend(subs)

        if not has_more or not next_cursor:
            break
        cursor = next_cursor

    return all_subs


async def handle_note(client, note_id: str, xsec_token: str, args) -> None:
    """处理单个帖子：获取详情 + 评论 + 下载图片。"""
    # 1. 获取帖子详情
    logger.info("=" * 60)
    logger.info("获取帖子详情: %s", note_id)

    try:
        resp = await client.get_note_detail(note_id, xsec_token)
    except Exception as e:
        logger.error("获取帖子详情失败: %s", e)
        return

    if resp.get("code") != 0:
        logger.error("API返回错误: code=%d msg=%s", resp.get("code", -1), resp.get("msg", ""))
        return

    note = parse_note_from_api(resp)
    if not note:
        logger.error("无法解析帖子数据")
        return
    note.xsec_token = xsec_token

    logger.info("标题: %s", note.title)
    logger.info("作者: %s", note.author.nickname)
    logger.info("图片: %d 张", len(note.images))
    logger.info("点赞: %d  收藏: %d  评论: %d", note.like_count, note.collect_count, note.comment_count)

    # 2. 获取评论
    comments = []
    if note.comment_count > 0:
        logger.info("-" * 40)
        max_c = args.max_comments or int(os.getenv("MAX_COMMENTS", "0"))
        comments = await fetch_all_comments(client, note_id, xsec_token, max_comments=max_c)

    # 3. 下载图片
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)
    image_dir = None
    if not args.no_download and note.images:
        logger.info("-" * 40)
        image_dir = output_dir / f"{note_id}_images"
        urls = [img.url for img in note.images if img.url]
        if urls:
            from downloader import download_images
            await download_images(urls, image_dir)

    # 4. 保存JSON
    logger.info("-" * 40)
    json_path = output_dir / f"{note_id}.json"
    post = PostData(
        note=note,
        comments=comments,
        fetch_time=datetime.now(timezone.utc).isoformat(),
        url=f"https://www.xiaohongshu.com/explore/{note_id}",
    )
    json_path.write_text(
        post.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("JSON已保存: %s", json_path)

    # 5. 摘要
    logger.info("=" * 60)
    logger.info("完成！")
    logger.info("  帖子: %s", note.title)
    logger.info("  评论: %d 条", len(comments))
    logger.info("  图片: %s", f"{image_dir}/" if image_dir else "未下载")
    logger.info("  JSON: %s", json_path)


async def handle_search(client, keyword: str, count: int, output_dir: str) -> None:
    """搜索笔记并展示结果。"""
    logger.info("搜索: %s (count=%d)", keyword, count)

    try:
        resp = await client.search_notes(keyword, page=1, page_size=count)
    except Exception as e:
        logger.error("搜索失败: %s", e)
        return

    if resp.get("code") != 0:
        logger.error("搜索API返回错误: code=%d", resp.get("code", -1))
        return

    items = resp.get("data", {}).get("items", [])
    if not items:
        logger.info("没有找到相关笔记")
        return

    logger.info("找到 %d 条结果:", len(items))
    for i, item in enumerate(items):
        note_card = item.get("note_card", {})
        note_id = item.get("note_id", "")
        title = note_card.get("display_title", "")
        author = item.get("user", {}).get("nickname", "")
        likes = item.get("interact_info", {}).get("liked_count", 0)
        logger.info("  [%d] %s", i + 1, title)
        logger.info("      ID: %s  作者: %s  点赞: %d", note_id, author, likes)

    # 保存搜索结果
    out_path = Path(output_dir) / f"search_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    ensure_dir(output_dir)
    out_path.write_text(
        json.dumps(resp, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("搜索结果已保存: %s", out_path)


async def main_async() -> None:
    global logger
    args = parse_args()
    logger = setup_logger("xhs")

    # 确保输出目录存在
    ensure_dir(args.output_dir)

    # 确定 headless 模式
    headless = not args.no_headless

    # Cookie优先从命令行获取，其次从环境变量
    cookie_string = args.cookie or os.getenv("COOKIE_STRING", "")

    # 解析URL
    note_id = args.note_id
    xsec_token = args.xsec_token
    if args.url:
        result = extract_note_info_from_url(args.url)
        if not result:
            logger.error("无法从URL解析帖子信息: %s", args.url)
            return
        note_id, xsec_token = result
        logger.info("解析URL: note_id=%s xsec_token=%s...", note_id, xsec_token[:20] if xsec_token else "(无)")

    # 初始化
    login_manager = None
    if cookie_string:
        # 有直接Cookie: 跳过Playwright浏览器，直接用xhshow签名
        logger.info("使用直接Cookie模式（跳过浏览器）")
        from client import XHSClient
        client = XHSClient(
            login_manager=None,
            cookie_string=cookie_string,
            delay_min=float(os.getenv("REQUEST_DELAY_MIN", "2")),
            delay_max=float(os.getenv("REQUEST_DELAY_MAX", "5")),
        )
    else:
        # 无Cookie: 启动Playwright浏览器进行扫码登录
        from login import XHSLoginManager
        login_manager = XHSLoginManager(
            storage_state_file=os.getenv("STORAGE_STATE_FILE", ".storage_state.json"),
            headless=headless,
            proxy=os.getenv("PROXY"),
            cookie_string=cookie_string,
        )
        logger.info("启动浏览器...")
        await login_manager.start_browser()
        if not await login_manager.ensure_logged_in():
            logger.error("登录失败，无法继续")
            return
        from client import XHSClient
        client = XHSClient(
            login_manager=login_manager,
            cookie_string=cookie_string,
            delay_min=float(os.getenv("REQUEST_DELAY_MIN", "2")),
            delay_max=float(os.getenv("REQUEST_DELAY_MAX", "5")),
        )

    try:
        if args.search:
            await handle_search(client, args.search, args.count, args.output_dir)
        elif note_id:
            await handle_note(client, note_id, xsec_token, args)
        else:
            logger.info("没有指定操作。请使用 --url, --note-id, 或 --search")
            logger.info("示例: python main.py --url \"https://www.xiaohongshu.com/explore/xxx\"")

    except Exception as e:
        logger.exception("运行出错: %s", e)
    finally:
        await client.close()
        if login_manager:
            await login_manager.close()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
