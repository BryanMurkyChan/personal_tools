"""小红书API请求客户端。

使用 curl_cffi 绕过TLS指纹检测，通过Playwright浏览器获取签名参数。
"""

import json
import logging
import time
import urllib.parse

logger = logging.getLogger("xhs")


class XHSApiError(Exception):
    """API请求错误。"""
    def __init__(self, code: int, msg: str = "", url: str = ""):
        self.code = code
        self.msg = msg
        self.url = url
        super().__init__(f"API错误 [code={code}] {msg} (url={url})")


class CircuitBreakerOpenError(Exception):
    """熔断器打开，请求被拒绝。"""
    pass


class LoginExpiredError(Exception):
    """登录已过期。"""
    pass


class XHSClient:
    """小红书API客户端。

    每次API请求前：
    1. 通过Playwright页面调用 window._webmsxyw() 获取 x_s/x_t
    2. 通过 sign.py 组装 x-s-common 和 x-b3-traceid
    3. 使用 curl_cffi 发起请求（模拟Chrome 120 TLS指纹）
    """

    XHS_API_HOST = "https://edith.xiaohongshu.com"

    def __init__(
        self,
        login_manager,
        cookie_string: str = "",
        delay_min: float = 2.0,
        delay_max: float = 5.0,
    ):
        self._login = login_manager
        self._cookie_string = cookie_string
        from utils import CircuitBreaker, random_delay

        self._random_delay = random_delay
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._circuit_breaker = CircuitBreaker(threshold=3, cooldown_seconds=300.0)

        # 解析cookie dict供curl_cffi使用
        from utils import parse_cookie_string
        self._cookie_dict = parse_cookie_string(cookie_string) if cookie_string else {}

        # curl_cffi Session
        try:
            from curl_cffi import requests
            self._session = requests.Session()
            self._session.impersonate = "chrome120"
        except ImportError:
            logger.error("请安装 curl_cffi: pip install curl-cffi")
            raise

    async def close(self) -> None:
        """关闭HTTP会话。"""
        if self._session:
            self._session.close()

    # ---- 内部方法 ----

    async def _sign_request(self, url_path: str, data: dict | None = None, params: dict | None = None) -> dict:
        """获取完整的签名headers。

        使用 xhshow 纯Python签名（基于原始Cookie字符串，确保一致性）。

        Returns:
            {"x-s": ..., "x-t": ..., "x-s-common": ..., "x-b3-traceid": ...}
        """
        # 使用原始Cookie字符串
        cookie_str = self._cookie_string
        if not cookie_str and self._login:
            cookie_str = await self._login.get_cookie_string()

        from xhshow import Xhshow
        xh = Xhshow()
        if data is not None:
            result = xh.sign_headers_post(
                uri=url_path,
                cookies=cookie_str,
                xsec_appid="xhs-pc-web",
                payload=data,
            )
        else:
            result = xh.sign_headers_get(
                uri=url_path,
                cookies=cookie_str,
                xsec_appid="xhs-pc-web",
                params=params,
            )
        return {
            "x-s": result.get("x-s", ""),
            "x-t": result.get("x-t", ""),
            "x-s-common": result.get("x-s-common", ""),
            "x-b3-traceid": result.get("x-b3-traceid", ""),
        }

    def _get_base_headers(self) -> dict:
        """构建基础HTTP请求头。"""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def _request(
        self,
        method: str,
        url: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        # 检查熔断器
        if self._circuit_breaker.is_open():
            remaining = self._circuit_breaker.remaining_cooldown
            raise CircuitBreakerOpenError(
                f"熔断器打开，剩余冷却时间: {remaining:.0f}秒"
            )

        # 随机延迟
        await self._random_delay(self._delay_min, self._delay_max)

        # 构建签名用的URL路径（GET含查询参数，POST为纯路径）
        url_parsed = urllib.parse.urlparse(url)
        if method.upper() == "GET" and params:
            query_string = urllib.parse.urlencode(params)
            sign_path = f"{url_parsed.path}?{query_string}"
        else:
            sign_path = url_parsed.path

        try:
            # POST请求将body传给签名，GET请求传params
            if method.upper() == "POST":
                sign_headers = await self._sign_request(sign_path, data=json_data)
            else:
                sign_headers = await self._sign_request(sign_path, params=params)
        except RuntimeError:
            self._circuit_breaker.record_failure()
            raise

        # 使用原始Cookie（确保与签名一致）
        cookie_dict = self._cookie_dict
        if not cookie_dict and self._login:
            cookie_dict = await self._login._get_cookie_dict()

        # 组装完整headers（不含Cookie，用cookies参数传递）
        headers = self._get_base_headers()
        headers.update({
            "x-s": sign_headers["x-s"],
            "x-t": sign_headers["x-t"],
            "x-s-common": sign_headers["x-s-common"],
            "x-b3-traceid": sign_headers["x-b3-traceid"],
        })

        logger.debug("请求: %s %s", method, url[:90])

        try:
            if method.upper() == "GET":
                resp = self._session.get(
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookie_dict,
                    timeout=30,
                )
            else:
                resp = self._session.post(
                    url,
                    json=json_data,
                    headers=headers,
                    cookies=cookie_dict,
                    timeout=30,
                )

            logger.debug("%s %s -> %d", method, url[:80], resp.status_code)

            # 处理特殊状态码
            if resp.status_code in (403, 412):
                logger.warning("请求被拒绝 (status=%d)，Cookie可能已过期", resp.status_code)
                self._circuit_breaker.record_failure()
                raise LoginExpiredError(
                    f"Cookie可能已过期 (HTTP {resp.status_code})"
                )

            if resp.status_code == 461:
                logger.warning("签名验证失败 (HTTP 461)")
                self._circuit_breaker.record_failure()
                raise XHSApiError(
                    code=461,
                    msg="签名验证失败，可能是签名算法有误或Cookie不匹配",
                    url=url,
                )

            if resp.status_code == 418:
                logger.warning("IP可能被暂时限制 (HTTP 418)")
                self._circuit_breaker.record_failure()
                raise XHSApiError(code=418, msg="IP被暂时限制", url=url)

            result = resp.json()

            # 检查业务错误码
            code = result.get("code", 0)
            if code != 0:
                if code == -1:
                    # code=-1通常是子评论不可访问（已删除/受限），非致命
                    logger.debug("API返回code=-1 (非致命): %s", url[:80])
                else:
                    logger.warning("API返回错误码: %d, msg=%s, 完整响应: %s",
                                 code, result.get("msg", ""),
                                 json.dumps(result, ensure_ascii=False)[:500] if isinstance(result, dict) else str(result)[:500])
                if code == 300012:
                    self._circuit_breaker.record_failure()
                    raise LoginExpiredError("IP被封锁 (code=300012)")
                if code == -510001:
                    raise XHSApiError(code=code, msg="笔记异常", url=url)
                # 非致命错误，返回原始结果让调用方处理
                return result

            self._circuit_breaker.record_success()
            return result

        except (XHSApiError, LoginExpiredError, CircuitBreakerOpenError):
            raise
        except Exception as e:
            logger.error("请求异常: %s", e)
            self._circuit_breaker.record_failure()
            raise

    # ---- 公开API ----

    async def get_note_detail(self, note_id: str, xsec_token: str = "") -> dict:
        """获取帖子详情。

        POST /api/sns/web/v1/feed
        """
        url = f"{self.XHS_API_HOST}/api/sns/web/v1/feed"
        body = {
            "source_note_id": note_id,
            "extra": {"need_body_topic": "1"},
            "image_formats": ["jpg", "webp", "avif"],
            "xsec_source": "pc_search",
            "xsec_token": xsec_token,
        }
        logger.info("获取帖子详情: %s", note_id)
        return await self._request("POST", url, json_data=body)

    async def get_note_comments(
        self,
        note_id: str,
        xsec_token: str = "",
        cursor: str = "",
        top_comment_id: str = "",
    ) -> dict:
        """获取帖子一级评论。

        GET /api/sns/web/v2/comment/page
        """
        url = f"{self.XHS_API_HOST}/api/sns/web/v2/comment/page"
        params = {
            "note_id": note_id,
            "cursor": cursor,
            "top_comment_id": top_comment_id,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
        }
        logger.debug("获取评论: note_id=%s cursor=%s", note_id, cursor[:10] if cursor else "(首页)")
        return await self._request("GET", url, params=params)

    async def get_sub_comments(
        self,
        note_id: str,
        root_comment_id: str,
        xsec_token: str = "",
        cursor: str = "",
        num: int = 30,
    ) -> dict:
        """获取子评论（楼中楼）。

        GET /api/sns/web/v2/comment/sub/page
        """
        url = f"{self.XHS_API_HOST}/api/sns/web/v2/comment/sub/page"
        params = {
            "note_id": note_id,
            "root_comment_id": root_comment_id,
            "num": str(num),
            "cursor": cursor,
            "xsec_token": xsec_token,
        }
        logger.debug("获取子评论: root_id=%s cursor=%s", root_comment_id, cursor[:10] if cursor else "(首页)")
        return await self._request("GET", url, params=params)

    async def search_notes(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        sort: str = "general",
    ) -> dict:
        """搜索笔记。

        POST /api/sns/web/v1/search/notes
        """
        url = f"{self.XHS_API_HOST}/api/sns/web/v1/search/notes"
        body = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "sort": sort,
            "note_type": 0,
            "ext_flags": [],
            "image_formats": ["jpg", "webp", "avif"],
        }
        logger.info("搜索笔记: %s (page=%d)", keyword, page)
        return await self._request("POST", url, json_data=body)
