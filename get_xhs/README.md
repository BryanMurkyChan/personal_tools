# 小红书帖子图文+评论获取方案

## Context

需要在 `e:\code\personal_tools\get_xhs\` 下构建一个小红书数据获取工具，能够获取指定帖子的：
- 图文内容（标题、正文、图片）
- 全部评论（含二级评论）

小红书的反爬机制在2025-2026年已非常强大，需要综合多种技术手段应对。

---

## 反爬机制总览

| 机制 | 说明 | 难度 |
|------|------|------|
| **x-s / x-t 签名** | 每个API请求都需要加密签名，核心逻辑用JSVMP虚拟机保护 | ★★★★★ |
| **TLS指纹检测(JA3/JA4)** | Python `requests` 库的TLS指纹会被直接识别拦截 | ★★★ |
| **IP频率限制** | 数据中心IP几分钟内被封，412/418错误 → IP被ban | ★★★★ |
| **设备指纹 + 行为分析** | 鼠标轨迹、滑动速度、设备一致性检测 | ★★★ |

---

## 主流开源方案对比

| 方案 | 原理 | 优点 | 缺点 |
|------|------|------|------|
| **[MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)** (35k★) | Playwright浏览器自动化 + JS签名 | 最稳定，无需逆向JS，支持多平台 | 需要浏览器，速度较慢 |
| **[ReaJason/xhs](https://github.com/ReaJason/xhs)** | pip安装，纯Python封装 | API简洁，轻量 | 签名依赖外部函数，需Node.js |
| **[Spider_XHS](https://github.com/cv-cat/Spider_XHS)** | Python + Node.js混合 | 功能全面，覆盖PC+创作者+蒲公英平台 | 需要Node.js 20+ |
| **[JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)** | GUI+CLI下载工具 | 开箱即用，有Windows exe | 侧重于下载，不支持评论 |

---

## 推荐方案：MediaCrawler 思路（Playwright + curl_cffi + Python签名）

### 核心原理

绕过签名难题的关键思路：**不逆向JS，而是调用浏览器中已加载的JS函数**。

1. Playwright启动Chromium浏览器 → 加载小红书页面
2. 通过Cookie注入或扫码完成登录
3. 每次API请求前，通过 `page.evaluate()` 直接调用浏览器运行时中的 `window._webmsxyw(url, data)` 获取X-s和X-t
4. 用Python组装最终签名字符串（`x-s-common`, `x-b3-traceid`）
5. 使用 `curl_cffi` 发起API请求（绕过TLS指纹检测）

### 关键技术栈

```
curl_cffi (TLS指纹伪装，模拟Chrome 120)
    +
Playwright (维持浏览器会话，执行签名JS)
    +
Python签名函数 (组装x-s-common等header)
    +
隧道代理IP (可选，大规模采集时需要)
```

### 目标API端点

| 功能 | API路径 |
|------|---------|
| 帖子详情 | `/api/sns/web/v1/feed` |
| 评论列表 | `/api/sns/web/v2/note/page/comments` |
| 子评论 | `/api/sns/web/v2/note/sub/page/comments` |
| 搜索笔记 | `/api/sns/web/v1/search/notes` |

---

## 实施计划

### 文件结构

```
e:\code\personal_tools\get_xhs\
├── main.py              # CLI入口，接收帖子URL/ID，调度各模块
├── client.py            # 核心请求客户端：签名+API调用
├── login.py             # Playwright登录管理（扫码/Cookie注入）
├── sign.py              # Python端签名算法（组装x-s-common等）
├── downloader.py        # 图片下载器
├── models.py            # 数据模型（Post, Comment等）
├── utils.py             # 工具函数（Cookie解析、随机延迟等）
├── requirements.txt     # 依赖
├── .env.example         # Cookie配置模板
└── output/              # 输出目录（图片+JSON）
```

### 实现步骤

#### Step 1: 登录态获取 (`login.py`)
- 使用Playwright启动Chromium（启用stealth模式）
- 支持两种方式：
  - **Cookie注入**: 用户从浏览器F12复制Cookie字符串，注入到Playwright context
  - **扫码登录**: 打开小红书登录页，用户用App扫码
- 登录成功后缓存Cookie到本地文件（避免每次重新登录）
- 提取localStorage中的 `b1` 值（签名必需）

#### Step 2: 签名计算 (`sign.py`)
- 参考MediaCrawler的 `help.py` 中的 `sign()` 函数
- 输入：`a1`(cookie), `b1`(localStorage), `x_s`(浏览器生成), `x_t`(浏览器生成)
- 输出：`x-s`, `x-t`, `x-s-common`, `x-b3-traceid` 四个header
- 关键：`x_s` 和 `x_t` 必须由浏览器中的 `window._webmsxyw()` 生成

#### Step 3: API请求客户端 (`client.py`)
- 使用 `curl_cffi` 替代 `requests`（绕过TLS指纹）
- 每次请求前通过Playwright页面调用JS获取签名参数
- 自动处理Cookie过期检测
- 内置随机延迟（2-5秒）和重试机制
- 实现三个核心方法：
  - `get_note_detail(note_id, xsec_token)` → 帖子详情
  - `get_note_comments(note_id, cursor)` → 评论（支持翻页）
  - `get_sub_comments(note_id, root_comment_id, cursor)` → 子评论

#### Step 4: 图片下载 (`downloader.py`)
- 从帖子详情中提取图片URL列表
- 并发下载（控制并发数避免触发限流）
- 自动命名：`{note_id}_{index}.jpg`
- 显示下载进度

#### Step 5: CLI入口 (`main.py`)
```
用法:
  python main.py --url "https://www.xiaohongshu.com/explore/xxx"
  python main.py --note-id "67890abcdef" --xsec-token "xxx"
  python main.py --search "关键词" --count 20
  python main.py --cookie "your_cookie_string"
```
- 解析帖子URL提取 note_id 和 xsec_token
- 统一调用client获取数据
- 保存为JSON（包含完整帖子信息+所有评论）
- 同时下载图片到本地

### 反反爬措施

1. **TLS伪装**: 使用 `curl_cffi` 模拟Chrome 120的TLS指纹
2. **签名实时生成**: 不预计算，每次请求通过浏览器生成最新签名
3. **随机延迟**: 请求间隔 2-5 秒随机
4. **Cookie保鲜**: 检测到403/412自动重新登录
5. **请求头完整**: 携带完整的浏览器headers（User-Agent, Accept-Language等）
6. **熔断机制**: 连续失败3次暂停5分钟

### 已知限制

1. **需要浏览器环境**: Playwright依赖Chromium（~300MB首次下载）
2. **Cookie有效期**: 通常2-3天过期，需要重新获取
3. **频率限制**: 建议每分钟不超过10次API请求（个人使用足够）
4. **签名JS可能更新**: 小红书不定期更新前端代码，`window._webmsxyw` 函数可能变化。如果失效需要更新Playwright获取的签名逻辑

---

## 验证方法

1. 手动从浏览器获取Cookie，填入 `.env` 文件
2. 准备一个已知的小红书帖子URL
3. 运行 `python main.py --url "帖子链接"`
4. 验证输出：
   - `output/{note_id}.json` 包含标题、正文、发布时间、点赞数等
   - `output/{note_id}_images/` 目录下的图片完整可打开
   - JSON中 `comments` 数组包含评论内容和子评论
5. 测试翻页：指定 `--max-comments 200` 验证评论翻页逻辑