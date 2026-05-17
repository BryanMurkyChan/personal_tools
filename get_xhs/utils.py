"""小红书工具通用函数。"""

import asyncio
import logging
import os
import random
import re
import time
import urllib.parse
from pathlib import Path


def parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """解析Cookie字符串为字典。

    Args:
        cookie_str: "a1=xxx; web_session=yyy; webId=zzz"

    Returns:
        {"a1": "xxx", "web_session": "yyy", "webId": "zzz"}
    """
    if not cookie_str or not cookie_str.strip():
        return {}
    result = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            key, _, value = item.partition("=")
            result[key.strip()] = value.strip()
        else:
            logging.getLogger("xhs").warning(f"Ignoring malformed cookie entry: {item}")
    return result


def extract_note_info_from_url(url: str) -> tuple[str, str] | None:
    """从小红书帖子URL中提取 note_id 和 xsec_token。

    支持格式:
        https://www.xiaohongshu.com/explore/{note_id}?xsec_token=...
        https://www.xiaohongshu.com/discovery/item/{note_id}?xsec_token=...

    Returns:
        (note_id, xsec_token) 或 None（无法解析时）
    """
    url = url.strip()
    # 分离路径和查询参数
    match = re.match(r"^https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/([a-zA-Z0-9]+)", url)
    if not match:
        return None
    note_id = match.group(1)
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    xsec_token = params.get("xsec_token", [""])[0]
    return note_id, xsec_token


async def random_delay(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    """随机异步延迟，避免被检测为爬虫。"""
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在，返回Path对象。"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup_logger(name: str = "xhs", level: int = logging.INFO) -> logging.Logger:
    """配置日志：控制台INFO级别，文件DEBUG级别。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    # 控制台 handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(console)

    # 文件 handler
    try:
        log_dir = ensure_dir("output/logs")
        file_handler = logging.FileHandler(
            log_dir / f"xhs_{time.strftime('%Y%m%d')}.log", encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(funcName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(file_handler)
    except OSError:
        pass

    return logger


class CircuitBreaker:
    """简单的熔断器：连续失败N次后暂停冷却M秒。"""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 300.0):
        self._threshold = threshold
        self._cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._open_since: float | None = None

    def record_failure(self) -> bool:
        """记录一次失败。返回True表示熔断器打开。"""
        self._failure_count += 1
        if self._failure_count >= self._threshold:
            self._open_since = time.time()
            return True
        return False

    def record_success(self) -> None:
        """记录一次成功，重置计数。"""
        self._failure_count = 0
        self._open_since = None

    def is_open(self) -> bool:
        """检查熔断器是否打开（需冷却）。"""
        if self._open_since is None:
            return False
        if time.time() - self._open_since >= self._cooldown_seconds:
            self._failure_count = 0
            self._open_since = None
            return False
        return True

    @property
    def remaining_cooldown(self) -> float:
        """剩余冷却时间（秒）。"""
        if self._open_since is None:
            return 0.0
        elapsed = time.time() - self._open_since
        return max(0.0, self._cooldown_seconds - elapsed)


def mask_sensitive(text: str, visible_chars: int = 4) -> str:
    """遮盖敏感信息，仅显示前几个字符。"""
    if not text:
        return ""
    if len(text) <= visible_chars:
        return text
    return text[:visible_chars] + "***"
