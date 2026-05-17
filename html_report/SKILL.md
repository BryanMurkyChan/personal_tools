---
name: html_report
description: Generate beautiful Apple-style HTML reports. Use when the user wants to create a visual report, present data/information as a styled HTML page, or generate a report document.
user-invocable: true
---

# /html_report — Apple 美学 HTML 报告生成

按照 Apple 官网设计语言生成清晰、详尽、普通人能读懂的 HTML 报告。

## 用法

```
/html_report <主题描述>
/html_report <主题描述> --output <路径>
```

| 参数 | 说明 |
|------|------|
| `$ARGUMENTS` | 报告主题或内容描述，越详细越好 |
| `--output` / `-o` | 输出路径，默认 `e:\code\personal_tools\html_report\output\<title>.html` |

### 示例

```
/html_report 2026年5月项目进度总结
/html_report 漆小喵 Agent 架构说明 --output e:/code/miao_v2/docs/architecture.html
/html_report 今天完成了记忆系统优化：1.向量检索改用Faiss 2.记忆衰减曲线调整为余弦 3.新增记忆去重
```

## 执行步骤

### 第零步：理解需求

从 `$ARGUMENTS` 中提取报告主题。如果内容过于简短（<20字），追问用户补充：
- 报告面向谁？
- 需要包含哪些数据/信息？
- 有没有需要强调的结论？

### 第一步：组织内容结构

将信息组织为清晰的逻辑层次：
- **Hero 区** — 报告标题 + 一句话副标题 + 日期/作者
- **核心摘要** — 3-5 个关键点，放在最前面让读者快速把握
- **主体内容** — 按逻辑分段，每段一个主题，用小标题引导
- **数据/图表区** — 如有数据，用简洁的表格或数字卡片展示
- **补充说明** — 脚注、来源、下一步计划等
- **Footer** — 生成信息

### 第二步：选择视觉节奏

根据内容量选择页面结构：

| 内容量 | 结构 |
|--------|------|
| 简短（1-3段） | 单页：Hero → 内容 → Footer |
| 中等（4-8段） | 分节：Hero → 摘要卡片 → 各段交替 tile → Footer |
| 长篇（8+段） | 完整：Hero → 摘要卡片 → 交替 tile（白/羊皮纸/黑）→ 数据区 → Footer |

### 第三步：生成 HTML

参考 `report_template.html` 中的 CSS 设计令牌，生成完整的独立 HTML 文件。

**必须遵守的设计约束：**
- 唯一强调色是 `#0066cc`（Action Blue），不使用其他颜色作为交互信号
- 正文用 17px / 400 字重 / 1.47 行高
- 标题用 600 字重（不是 700），大标题加负 letter-spacing
- 不使用渐变背景
- 不使用卡片阴影（除了产品图片可以有一个 `rgba(0,0,0,0.22) 3px 5px 30px`）
- section 之间用颜色交替区分（白→羊皮纸→深色），不加边框分割线
- CTA 按钮用 `rounded.pill`（9999px）胶囊形
- 全局只用一种圆角体系：卡片 18px，按钮 pill，图片 8px

### 第四步：保存并报告

- 保存 HTML 到指定路径
- 告知用户文件路径，建议在浏览器中打开查看

## Apple 设计令牌速查

### 色彩

| 令牌 | 值 | 用途 |
|------|-----|------|
| `--color-primary` | #0066cc | 唯一品牌强调色，所有链接、CTA |
| `--color-primary-on-dark` | #2997ff | 深色背景上的链接 |
| `--color-canvas` | #ffffff | 主画布、卡片背景 |
| `--color-canvas-parchment` | #f5f5f7 | 交替浅色块、页脚 |
| `--color-surface-tile-1` | #272729 | 深色瓷砖 1 |
| `--color-surface-tile-2` | #2a2a2c | 深色瓷砖 2（微亮） |
| `--color-surface-black` | #000000 | 全局导航栏 |
| `--color-ink` | #1d1d1f | 所有正文标题文字 |
| `--color-ink-muted-80` | #333333 | 次级文字 |
| `--color-ink-muted-48` | #7a7a7a | 禁用态/法律文字 |
| `--color-body-on-dark` | #ffffff | 深色底上的文字 |
| `--color-body-muted` | #cccccc | 深色底上次级文字 |
| `--color-divider-soft` | rgba(0,0,0,0.04) | 弱分割 |
| `--color-hairline` | #e0e0e0 | 卡片 1px 边框 |

### 排版

| 令牌 | 字号 | 字重 | 行高 | 字间距 | 用途 |
|------|------|------|------|--------|------|
| hero-display | 56px | 600 | 1.07 | -0.28px | Hero 大标题 |
| display-lg | 40px | 600 | 1.10 | 0 | Tile 标题 |
| display-md | 34px | 600 | 1.47 | -0.374px | 段落标题 |
| lead | 28px | 400 | 1.14 | 0.196px | 副标题/导语 |
| tagline | 21px | 600 | 1.19 | 0.231px | 标签 |
| body-strong | 17px | 600 | 1.24 | -0.374px | 粗体强调 |
| body | 17px | 400 | 1.47 | -0.374px | 正文（不是 16px） |
| caption | 14px | 400 | 1.43 | -0.224px | 说明文字 |
| caption-strong | 14px | 600 | 1.29 | -0.224px | 强调说明 |
| fine-print | 12px | 400 | 1.0 | -0.12px | 法律文字、脚注 |
| micro-legal | 10px | 400 | 1.3 | -0.08px | 极小文字 |
| dense-link | 17px | 400 | 2.41 | 0 | 页脚链接 |

**原则：**
- 标题永远用 600 字重，不用 700
- 正文永远 17px，不用 16px
- 大标题（≥17px）用负 letter-spacing 营造紧致感
- 字重阶梯：300 / 400 / 600 / 700（没有 500）
- 字重 300 极少用，仅用于营造轻松氛围的大号文字

### 间距

- 基准单位 8px；结构布局对齐 8/12/16/20/24
- Section 内边距：80px（mobile 48px）
- 卡片内边距：24px
- 标题上方至少 64px 空气，下方 48–64px

### 圆角

| 令牌 | 值 | 用途 |
|------|-----|------|
| none | 0px | 全宽 tile |
| xs | 5px | 罕见的内联 chip |
| sm | 8px | 深色工具按钮、卡片内图片 |
| md | 11px | Pearl Button |
| lg | 18px | 工具卡片 |
| pill | 9999px | CTA 按钮、搜索框 |

### 阴影

**整个系统只有一个阴影：** `box-shadow: rgba(0,0,0,0.22) 3px 5px 30px`
- 只用在产品图片上
- 绝不用在卡片、按钮、文字上
- 层次感靠颜色交替产生，不靠阴影

### 响应式断点

| 断点 | 宽度 | 变化 |
|------|------|------|
| 小手机 | ≤ 419px | 单栏，标题 28px |
| 手机 | 420–640px | 单栏，标题 34px |
| 大手机 | 641–735px | 减内边距 |
| 平板竖 | 736–833px | 汉堡菜单 |
| 平板横 | 834–1023px | 导航展开 |
| 小桌面 | 1024–1068px | 2/3 宽 |
| 桌面 | 1069–1440px | 完整布局 |
| 宽桌面 | ≥ 1441px | 内容锁 1440px |

## 注意事项

- 所有 CSS 必须内联在 `<style>` 标签中，HTML 文件自包含
- 字体栈：`system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`
- 为中文优化：正文 `font-weight: 400` 对中文可读性很重要
- 深色 tile 上用 `--color-primary-on-dark` (#2997ff) 作为链接色
- 报告面向普通读者，避免技术黑话，用通俗语言解释复杂概念
- 数据优先用可视化表达（表格、数字卡片），避免大段文字墙
- 图片使用占位或 emoji/unicode 装饰，不依赖外部资源
