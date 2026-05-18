"""CLI wrapper — describe an image via Zhipu GLM-4.6V-FlashX. Usage: python describe_image.py <image_path> [mode|prompt]"""
import sys, os, base64
from io import BytesIO
from openai import OpenAI
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_KEY = os.environ.get("ZHIPU_API_KEY", "")
BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
MODEL = "glm-4.6v-flashx"
MAX_PX = 2048

# ── Prompts ──────────────────────────────────────────────────────────

DEFAULT_PROMPT = (
    "你是一台智能视觉分析工具。请严格按以下两步处理这张图片，"
    "不要输出任何额外开场白或结尾语。\n\n"
    "### 第一步：判断图片类型（只选一个最匹配的）\n"
    "- UI：应用/网页/软件界面截图\n"
    "- Code：代码编辑器、终端、IDE、配置文件\n"
    "- Document：文档、文章、表格、幻灯片、PDF 页面\n"
    "- Photo：自然场景、人物、物体、动物\n"
    "- Error：错误弹窗、崩溃界面、堆栈跟踪、报错日志\n"
    "- Other：以上都不是\n\n"
    "### 第二步：根据类型输出\n\n"
    "**如果是 UI：**\n"
    "## 概览\n"
    "一句话描述这是什么页面/功能\n\n"
    "## 空间\n"
    "客观描述页面空间的分配情况：\n"
    "- 内容区域与留白/装饰区域各占页面面积的大致比例\n"
    "- 主要区域的尺寸占比（如左侧栏占X%，右侧图占Y%）\n"
    "- 信息密度：疏朗 / 适中 / 紧凑\n"
    "- 大块空白或纯装饰区域的位置和面积\n\n"
    "## 布局\n"
    "页面结构简述（3-5句），各模块的空间关系和嵌套层级\n\n"
    "## 文字\n"
    "按从上到下顺序列出所有可见文字内容\n\n"
    "## 细节\n"
    "配色、组件状态、对齐方式等值得注意的细节（简要）\n\n"
    "**如果是 Code：**\n"
    "## 概览\n"
    "语言、文件类型、大致代码行数\n\n"
    "## 问题\n"
    "可见的错误/警告（红色波浪线、诊断信息、终端报错等），无则省略\n\n"
    "## 内容\n"
    "代码/日志的关键内容摘要\n\n"
    "**如果是 Document：**\n"
    "## 概览\n"
    "文档类型、主题\n\n"
    "## 结构\n"
    "标题层级、段落/章节组织\n\n"
    "## 关键信息\n"
    "核心数据、结论、待办项等\n\n"
    "**如果是 Photo：**\n"
    "用一段自然语言简洁描述场景、主体、氛围\n\n"
    "**如果是 Error：**\n"
    "## 错误信息\n"
    "完整错误文字（最重要的部分，务必逐字完整抄录）\n\n"
    "## 上下文\n"
    "错误出现的环境、相关文件/模块名\n\n"
    "**如果是 Other：**\n"
    "简洁描述图片内容"
)

UI_PROMPT = (
    "请对这张界面截图进行客观、全面的描述。你不是评审专家，你是一台高精度视觉记录仪。\n\n"
    "## 概览\n"
    "一句话：这是什么页面/什么功能\n\n"
    "## 空间\n"
    "客观描述页面空间的分配情况：\n"
    "- 内容区域与留白/装饰区域各占页面面积的大致比例\n"
    "- 各主要区域（导航栏、内容区、侧边栏、底栏等）的尺寸占比\n"
    "- 信息密度：疏朗 / 适中 / 紧凑\n"
    "- 大块空白或纯装饰区域的位置和面积（如有）\n\n"
    "## 布局\n"
    "页面结构描述（3-5句），包括各模块的空间关系、对齐方式、分割方式\n\n"
    "## 文字\n"
    "按从上到下顺序列出所有可见文字内容\n\n"
    "## 细节\n"
    "配色、组件状态、交互元素等值得注意的细节"
)

TEXT_PROMPT = (
    "列出这张图片中所有可见的文字内容。按从上到下、从左到右的顺序。"
    "只输出文字本身，不要任何标题、说明、格式标记。"
)

FULL_PROMPT = (
    "你是一台高精度视觉分析仪。请对这张图片进行全方位、无死角的描述，"
    "要求做到：仅凭你的文字，就能在脑海中1:1还原这张图片。\n\n"
    "## 一、整体印象与美学风格\n"
    "- 第一眼的整体感受：专业/活泼/极简/华丽/科技感/复古等\n"
    "- 设计语言：扁平化/新拟态/毛玻璃/ Material Design / 自定义风格\n"
    "- 视觉重心在哪里，视线自然流动顺序\n"
    "- 明暗模式（深色/浅色主题）、对比度水平、留白策略\n\n"
    "## 二、页面布局与空间结构\n"
    "- 整体是几栏布局，每栏占比和相对位置\n"
    "- 是否有顶部导航/侧边栏/底部栏/浮动元素\n"
    "- 每个区域的分割方式：分割线/阴影/色块/卡片/间距\n"
    "- 卡片/面板的圆角大小（估计像素）、是否有阴影及阴影参数\n"
    "- 元素之间的对齐方式（左对齐/居中/两端对齐）\n"
    "- 各模块的上下左右空间关系和嵌套层级\n\n"
    "## 三、所有文字内容（逐字逐句，严禁遗漏）\n"
    "- 按从上到下、从左到右的顺序，列出每一处可见文字\n"
    "- 包括：标题、副标题、正文、标签、按钮文字、占位符、提示文字\n"
    "- 包括：导航菜单项、面包屑、页码、表格表头、表格内容\n"
    "- 包括：图标旁的小字、悬浮提示、角标、徽章数字\n"
    "- 包括：页脚链接、版权信息、联系方式\n"
    "- 每段文字标注其字号大致层级（特大/大/中/小/极小）\n"
    "- 英文注意大小写，数字和符号原样保留\n\n"
    "## 四、交互组件与形状描述\n"
    "- 按钮：形状（圆角矩形/圆形/胶囊形）、边框粗细、填充/描边风格\n"
    "- 输入框：边框样式、是否有聚焦状态可见、placeholder 内容\n"
    "- 开关/切换器：当前状态（开/关）、轨道和滑块的颜色形状\n"
    "- 下拉菜单/选择器：展开方向和选中项\n"
    "- 表格：列数和每列表头，是否有排序箭头，斑马纹与否\n"
    "- 标签/徽章：形状（圆角矩形/圆形），是否带颜色填充\n"
    "- 进度条/滑块：当前进度百分比，轨道和已完成部分的颜色\n"
    "- 头像/缩略图：形状（圆形/方形）、尺寸\n\n"
    "## 五、色彩体系（尽量精确）\n"
    "- 主色调及大致色值（如 #1a73e8 蓝）\n"
    "- 背景色层次：页面底色、卡片底色、悬浮底色各是什么\n"
    "- 文字颜色层级：主要文字、次要文字、禁用文字各自颜色\n"
    "- 强调色/警告色/成功色/错误色分别为什么颜色\n"
    "- 渐变色的起止色和方向（如有）\n"
    "- 所有出现的不属于主色系的特殊颜色\n\n"
    "## 六、图标与图形元素\n"
    "- 每个图标的形状描述（不是猜含义，是描述图形本身）\n"
    "- 图标的线条风格：线性/面性/双色\n"
    "- 是否有自定义插画或品牌图形\n"
    "- logo 的形状、颜色、构成元素\n"
    "- 任何装饰性图形、分隔符、水印\n\n"
    "## 七、状态指示与动效线索\n"
    "- 状态指示灯/圆点：颜色、是否带脉冲动画\n"
    "- 选中/激活态的视觉表现（高亮条/背景色变化/加粗）\n"
    "- 悬停态线索（下划线、颜色变化——如有可见）\n"
    "- 禁用/不可用元素的灰色处理\n"
    "- 加载骨架屏或空状态占位（如有）\n\n"
    "## 八、数据可视化与图表（如有）\n"
    "- 图表类型（折线图/柱状图/饼图/面积图等）\n"
    "- 坐标轴标签和数据点数值\n"
    "- 图例位置和各项颜色\n\n"
    "## 九、错误与异常信息（如有）\n"
    "- 错误弹窗/ Toast / 内联错误提示的完整文字\n"
    "- 堆栈跟踪或日志输出的完整内容\n"
    "- 红色/橙色警告标识的形态\n"
    "- HTTP 状态码、错误码\n\n"
    "## 十、补充细节\n"
    "- 光标/指针位置（如有）\n"
    "- 选中文本的高亮范围（如有）\n"
    "- 浏览器地址栏/标签页标题（如在截图内）\n"
    "- 任何你认为值得一提但上述分类未覆盖的细节"
)

# ── Mode dispatch ────────────────────────────────────────────────────

def build_prompt(mode):
    """Return (prompt, mode_name) for the given mode string."""
    if not mode:
        return DEFAULT_PROMPT, "default"
    if mode == "ui":
        return UI_PROMPT, "ui"
    if mode == "text":
        return TEXT_PROMPT, "text"
    if mode == "full":
        return FULL_PROMPT, "full"
    return mode, "raw"

# ── Main ─────────────────────────────────────────────────────────────

path = sys.argv[1]
raw_mode = sys.argv[2] if len(sys.argv) > 2 else ""

if not os.path.isfile(path):
    print(f"[ERROR] File not found: {path}", file=sys.stderr)
    sys.exit(1)

prompt, mode = build_prompt(raw_mode)

with Image.open(path) as img:
    w, h = img.size
    if max(w, h) > MAX_PX:
        scale = MAX_PX / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120)

response = client.chat.completions.create(
    model=MODEL,
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }],
    max_tokens=8192,
)
print(response.choices[0].message.content or "(no response)")
