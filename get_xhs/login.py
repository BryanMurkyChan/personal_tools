"""小红书Playwright登录管理器。

负责：
- 启动Chromium浏览器（stealth模式）
- Cookie注入登录 / 扫码登录
- 从浏览器提取签名参数（a1, b1, x_s, x_t）
- 浏览器状态持久化
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("xhs")


# 反检测脚本（内联stealth）
_STEALTH_SCRIPT = """
// 隐藏 webdriver 属性
Object.defineProperty(navigator, 'webdriver', { get: () => false });

// 填充 plugins 数组
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        arr.item = (i) => arr[i];
        arr.namedItem = (n) => arr.find(p => p.name === n);
        arr.refresh = () => {};
        Object.setPrototypeOf(arr, PluginArray.prototype);
        return arr;
    }
});

// 隐藏 chrome.runtime
Object.defineProperty(window, 'chrome', { get: () => ({ runtime: {} }) });

// 修复 permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);

// 修复 headless 检测
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// 覆盖 webgl vendor
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Google Inc. (Intel)';
    if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return getParameter.call(this, parameter);
};
"""


class XHSLoginManager:
    """管理Playwright浏览器会话，处理登录和签名参数提取。"""

    XHS_BASE_URL = "https://www.xiaohongshu.com"
    XHS_LOGIN_URL = "https://www.xiaohongshu.com/login"

    def __init__(
        self,
        storage_state_file: str = ".storage_state.json",
        headless: bool = True,
        proxy: str | None = None,
        cookie_string: str | None = None,
    ):
        self._storage_state_file = Path(storage_state_file)
        self._headless = headless
        self._proxy = proxy
        self._cookie_string = cookie_string
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._a1: str = ""
        self._b1: str = ""

    # ---- 浏览器生命周期 ----

    async def start_browser(self) -> None:
        """启动Chromium浏览器，配置stealth和中文环境。"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "请安装 playwright: pip install playwright && playwright install chromium"
            )
            raise

        self._playwright = await async_playwright().start()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self._proxy:
            launch_args.append(f"--proxy-server={self._proxy}")

        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=launch_args,
        )

        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        # 尝试加载已有的浏览器状态
        if self._storage_state_file.exists():
            try:
                context_options["storage_state"] = str(self._storage_state_file)
                logger.info("加载已保存的浏览器状态: %s", self._storage_state_file)
            except Exception:
                logger.warning("无法加载存储状态，使用全新浏览器上下文")

        self._context = await self._browser.new_context(**context_options)
        await self._context.add_init_script(_STEALTH_SCRIPT)
        self._page = await self._context.new_page()

        logger.info("浏览器已启动 (headless=%s)", self._headless)

    async def close(self) -> None:
        """保存状态并关闭浏览器。"""
        if self._context:
            await self.save_storage_state()
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("浏览器已关闭")

    async def save_storage_state(self) -> None:
        """持久化浏览器状态（Cookie + localStorage）。"""
        if self._context:
            await self._context.storage_state(path=str(self._storage_state_file))
            logger.debug("浏览器状态已保存到: %s", self._storage_state_file)

    # ---- 登录 ----

    async def inject_cookies(self, cookie_string: str) -> bool:
        """注入Cookie到浏览器上下文。

        Args:
            cookie_string: "a1=xxx; web_session=yyy; ..."

        Returns:
            True表示Cookie注入成功且已验证
        """
        from utils import parse_cookie_string

        cookies = parse_cookie_string(cookie_string)
        if not cookies:
            logger.error("Cookie字符串为空或无法解析")
            return False

        cookie_list = []
        for name, value in cookies.items():
            cookie_list.append({
                "name": name,
                "value": value,
                "domain": ".xiaohongshu.com",
                "path": "/",
            })

        await self._context.add_cookies(cookie_list)
        logger.info("已注入 %d 个Cookie", len(cookie_list))

        # 验证
        await self._navigate_to_home()
        await asyncio.sleep(2)
        return await self.check_login()

    async def qr_login(self, timeout: int = 120) -> bool:
        """扫码登录：打开登录页，等待用户扫描二维码。

        Args:
            timeout: 超时秒数

        Returns:
            True表示登录成功
        """
        logger.info("正在打开登录页...")
        await self._page.goto(self.XHS_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 获取登录前的web_session用于对比
        current_cookies = await self._context.cookies()
        old_web_session = ""
        for c in current_cookies:
            if c["name"] == "web_session":
                old_web_session = c["value"]
                break

        logger.info("请使用小红书App扫描终端中显示的二维码（或打开的浏览器窗口中的二维码）")
        logger.info("等待扫码登录... (超时: %d秒)", timeout)

        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(2)
            elapsed += 2

            # 检测是否登录成功（web_session变化或页面跳转）
            current_cookies = await self._context.cookies()
            for c in current_cookies:
                if c["name"] == "web_session" and c["value"] != old_web_session:
                    logger.info("检测到web_session变化，登录成功！")
                    # 等待一会确保localStorage就绪
                    await asyncio.sleep(2)
                    await self._navigate_to_home()
                    await asyncio.sleep(2)
                    await self._extract_signing_params()
                    await self.save_storage_state()
                    return True

            # 检查是否需要在页面手动处理验证码
            try:
                content = await self._page.content()
                if "请通过验证" in content:
                    logger.warning("检测到验证码，请在浏览器窗口中手动完成验证...")
            except Exception:
                pass

        logger.error("扫码登录超时")
        return False

    async def check_login(self) -> bool:
        """检查当前登录状态是否有效。"""
        try:
            from curl_cffi import requests

            cookies = await self._get_cookie_dict()
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

            resp = requests.get(
                "https://edith.xiaohongshu.com/api/sns/web/v2/user/me",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.xiaohongshu.com/",
                },
                cookies=cookies,
                timeout=15,
                impersonate="chrome120",
            )
            data = resp.json()
            if data.get("success") and data.get("data", {}).get("user_id"):
                logger.info("登录状态有效")
                return True
            logger.warning("登录状态无效: %s", data.get("msg", "未知错误"))
            return False
        except Exception as e:
            logger.warning("检查登录状态失败: %s", e)
            return False

    async def ensure_logged_in(self) -> bool:
        """确保已登录：先尝试已有状态，失败则重新登录。

        Returns:
            True表示登录就绪
        """
        # 检查存储状态中是否已有cookie
        existing = await self._get_cookie_dict()
        has_cookies = bool(existing.get("a1") or existing.get("web_session"))
        self._a1 = existing.get("a1", "")

        if has_cookies:
            logger.info("检测到已保存的Cookie，导航到首页验证...")
            await self._navigate_to_home()
            await self._extract_signing_params()
            if self._a1:
                logger.info("已有有效登录态 (a1=%s...)", self._a1[:12])
                return True
        else:
            logger.info("无已保存Cookie，需要登录")

        # 尝试Cookie注入登录
        if self._cookie_string:
            logger.info("尝试Cookie注入登录...")
            if await self.inject_cookies(self._cookie_string):
                # inject_cookies内部已导航 + 验证，但需补充提取签名参数
                await self._extract_signing_params()
                if self._a1:
                    return True

            logger.warning("Cookie登录验证失败，尝试直接使用注入的Cookie...")
            # Cookie注入后 a1 应该存在，即使check_login失败也可尝试
            await self._extract_signing_params()
            if self._a1:
                logger.info("Cookie已注入，尝试继续...")
                return True

            logger.warning("Cookie登录失败，尝试扫码登录...")

        # 回退到扫码登录
        if self._headless:
            logger.error(
                "无头模式下无法扫码登录。请提供 --cookie 参数，或使用 --no-headless 启用窗口模式。"
            )
            return False

        return await self.qr_login()

    # ---- 签名参数提取 ----

    async def _navigate_to_home(self) -> None:
        """导航到小红书首页，等待完整加载（含JS初始化）。"""
        try:
            await self._page.goto(
                self.XHS_BASE_URL,
                wait_until="networkidle",
                timeout=60000,
            )
            # 等待JS完全初始化（window._webmsxyw 可用）
            await self._wait_for_sign_function()
        except Exception as e:
            logger.warning("导航到首页失败: %s", e)

    async def _wait_for_sign_function(self, max_wait: int = 15) -> None:
        """等待 window._webmsxyw 函数可用。"""
        for i in range(max_wait):
            try:
                ready = await self._page.evaluate(
                    "() => typeof window._webmsxyw === 'function'"
                )
                if ready:
                    logger.debug("window._webmsxyw 已就绪")
                    return
            except Exception:
                pass
            await asyncio.sleep(1)
        logger.warning("等待 window._webmsxyw 超时 (%d秒)，将尝试在请求时调用", max_wait)

    async def _extract_signing_params(self) -> None:
        """从浏览器提取 a1 和 b1。"""
        # 提取 a1 (来自 Cookie)
        try:
            cookies = await self._context.cookies()
            for c in cookies:
                if c["name"] == "a1":
                    self._a1 = c["value"]
                    break
            if self._a1:
                logger.info("a1: %s...", self._a1[:12])
            else:
                logger.warning("未找到 a1 Cookie，Cookie可能未正确注入")
        except Exception as e:
            logger.error("提取 a1 失败: %s", e)

        # 提取 b1 (来自 localStorage) — 需要页面JS已初始化
        try:
            self._b1 = await self._page.evaluate(
                "() => window.localStorage.getItem('b1') || ''"
            )
            if self._b1:
                logger.info("b1: %s...", self._b1[:12])
            else:
                logger.warning("未找到 b1 localStorage 值，页面JS可能未初始化")
                # 尝试等待JS初始化后再试
                for _ in range(10):
                    await asyncio.sleep(1)
                    self._b1 = await self._page.evaluate(
                        "() => window.localStorage.getItem('b1') || ''"
                    )
                    if self._b1:
                        logger.info("延迟后获取到 b1: %s...", self._b1[:12])
                        break
        except Exception as e:
            logger.error("提取 b1 失败: %s", e)

    async def get_a1(self) -> str:
        """获取 a1 Cookie 值。"""
        if not self._a1:
            await self._extract_signing_params()
        return self._a1

    async def get_b1(self) -> str:
        """获取 b1 localStorage 值。"""
        if not self._b1:
            await self._extract_signing_params()
        return self._b1

    async def _get_cookie_dict(self) -> dict[str, str]:
        """获取当前浏览器上下文中的所有Cookie字典。"""
        cookies = await self._context.cookies()
        result = {}
        for c in cookies:
            if ".xiaohongshu.com" in c.get("domain", "") or "xiaohongshu.com" == c.get("domain", ""):
                result[c["name"]] = c["value"]
        return result

    async def get_cookie_string(self) -> str:
        """获取Cookie字符串，用于HTTP请求头。"""
        d = await self._get_cookie_dict()
        return "; ".join(f"{k}={v}" for k, v in d.items())

    async def get_xs_xt(self, url: str, data: dict | None = None) -> tuple[str, str]:
        """通过浏览器JS获取 x_s 和 x_t 签名参数。

        调用 window._webmsxyw(url, data) 获取签名。

        Args:
            url: API路径+查询参数（如 /api/sns/web/v1/feed）
            data: 请求数据（POST为body dict，GET为None）

        Returns:
            (x_s, x_t)
        """
        logger.debug("请求签名: url=%s, data=%s", url, str(data)[:80] if data else "None")
        try:
            result = await self._page.evaluate(
                """([url, data]) => {
                    if (typeof window._webmsxyw === 'function') {
                        return window._webmsxyw(url, data);
                    }
                    return null;
                }""",
                [url, data],
            )
        except Exception as e:
            logger.error("调用 window._webmsxyw 失败: %s", e)
            result = None

        if result is None:
            logger.error(
                "window._webmsxyw 不可用。请确认:\n"
                "  1. 浏览器页面已加载 www.xiaohongshu.com\n"
                "  2. 页面已完全渲染（非空白页）\n"
                "  3. Cookie已正确注入且未过期"
            )
            raise RuntimeError(
                "无法获取签名参数。window._webmsxyw 函数未找到。"
            )

        x_s = result.get("X-s", "") or result.get("x-s", "")
        x_t = result.get("X-t", 0) or result.get("x-t", 0)

        if not x_s:
            logger.error("浏览器签名返回空x_s: %s", result)
            raise RuntimeError("签名结果中缺少 x_s")

        logger.debug("签名成功: x_s=%s... x_t=%s", str(x_s)[:30], str(x_t)[:15])
        return x_s, x_t
