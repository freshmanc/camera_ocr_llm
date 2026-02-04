# -*- coding: utf-8 -*-
"""全局配置：摄像头、OCR、LLM、超时与降级"""
import os

# 项目根目录（config 包所在目录的上一级）
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 摄像头（高分辨率利于 OCR 清晰度，建议 1280x720 及以上）
CAMERA_INDEX = 0
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
FRAME_SKIP = 2  # 每 N 帧做一次 OCR；2=隔帧识别，减少抖动、提高稳定；1=每帧（更灵敏但易晃）

# 多帧融合 + 稳定后才 OCR（开太猛会几乎不识别，先关掉或放宽）
OCR_FUSION_FRAMES = 0       # 0=关闭；5 帧平均会糊字，先关掉保证能出字
OCR_MOTION_STABLE_ENABLED = False  # True=仅稳定时才 OCR，易导致“啥都不识别”；先关掉
OCR_MOTION_STABLE_THRESHOLD = 18.0  # 与上一帧平均像素差低于此认为稳定

# OCR：使用 PaddleOCR。推荐环境（Windows 最稳）：Python 3.10 + paddlepaddle==2.6.2 + paddleocr==2.7.0.3（经典版，不走 paddlex/PDX）
USE_EASYOCR = False   # False=先用 PaddleOCR，失败再用 EasyOCR；True=反之
USE_PADDLE_OCR = True
OCR_LANGS = ["en", "fr"]  # EasyOCR 用；Paddle 用 PADDLE_OCR_LANG
OCR_GPU = True  # RTX4060 建议 True；Paddle 用 PADDLE_OCR_FORCE_CPU 控制是否强制 CPU
# PaddleOCR 语言：ch=中英, en=英文, fr=法语等
PADDLE_OCR_LANG = "en"
PADDLE_OCR_FORCE_CPU = True
# 置信度：单框低于此丢弃；整体平均低于此视为无有效文本（提高可减少乱码、提升观感）
OCR_MIN_BOX_CONFIDENCE = 0.40
OCR_MIN_AVG_CONFIDENCE = 0.35
# 预处理（Agent B）：过猛会识别不到，先保守再逐步打开
OCR_USE_ROI = True
OCR_ROI_CENTER_RATIO = 0.7  # 中心区域宽高占比 0~1
OCR_ROI_UPSCALE = 1.0       # 1.0=不放大；1.5 在部分场景会劣化，先关
OCR_USE_PREPROCESS = False  # 先关二值化，保证能出字；再试 True+自适应
OCR_PREPROCESS_BLUR_KSIZE = (3, 3)
OCR_PREPROCESS_USE_ADAPTIVE_THRESH = True
OCR_USE_SHARPEN = False     # 锐化先关，出字后再试
OCR_SHARPEN_STRENGTH = 1.4
OCR_USE_SKEW_CORRECTION = False  # 倾斜校正（稍慢）
OCR_RESIZE_SHORT_EDGE = 0   # 短边缩放到此（0=不缩放），建议 320~640
# 光流防抖（可选，高端方案，当前未实现）
OCR_USE_OPTICAL_FLOW_STAB = False
# 去抖动：最近 N 次结果中至少 K 次相同/相似才视为稳定（加大 N、K 可减少“稍动就重识”）
OCR_DEBOUNCE_HISTORY_LEN = 6
OCR_DEBOUNCE_MIN_VOTES = 4
# 投票时视为“同一段”的相似度（0=仅完全一致；0.88=允许少量 OCR 误差仍算同一段）
OCR_DEBOUNCE_SIMILARITY_VOTE = 0.88
# 软稳定：当前帧与“稳定文本”相似度 >= 此阈值才认为仍在同一段（提高可减少误判）
OCR_SOFT_STABLE_ENABLED = True
OCR_SOFT_STABLE_SIMILARITY = 0.92
# 按行/段落输出：同一行用空格、行间用换行、段间用双换行，避免整段空格拼接不连贯
OCR_KEEP_LINE_STRUCTURE = True
OCR_LINE_Y_TOLERANCE_RATIO = 0.025   # 中心 y 相差小于此比例*图高视为同一行（约 2.5%）
OCR_PARAGRAPH_GAP_RATIO = 1.8        # 行间距大于 平均行高*此比例 视为新段落（双换行）

# Agent E：LLM 性能与体验（去抖 + 缓存 + 节流）
LLM_MIN_INTERVAL_MS = 1000       # 相邻两次真实 LLM 调用最小间隔（毫秒）
LLM_CACHE_MAX_SIZE = 200         # LLM 结果缓存最大条数
LLM_CACHE_TTL_SEC = 600          # 缓存有效期（秒）

# LLM 纠错：二选一 → 本地 LM Studio 或 OpenAI（ChatGPT 会员）
# 使用 ChatGPT：设为 True，并设置 OPENAI_API_KEY（建议用环境变量，勿提交到仓库）
LLM_USE_OPENAI = False
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # 或直接写 "sk-..."（不推荐）
# 本地 LM Studio（LLM_USE_OPENAI=False 时生效）
LLM_BASE_URL = "http://127.0.0.1:1234/v1"
# 模型：用 OpenAI 时填 "gpt-4o" / "gpt-4o-mini" 等；用 LM Studio 时填 LM Studio 里的 id 如 "qwen/qwen3-8b"
LLM_MODEL = "qwen3-VL-8b-thinking"  # 本地视觉语言模型，LM Studio 中显示的 id 为准
# thinking 模型（如 qwen3-vl-8b-thinking）推理慢，过短会触发 Client disconnected
LLM_TIMEOUT_SEC = 60
LLM_MAX_TOKENS = 280  # 只给 JSON 用，避免模型长篇推理浪费算力
LLM_TEMPERATURE = 0.2  # 严格纠错宜低，减少随意改写
LLM_RETRY_COUNT = 2    # 解析失败或网络错误时最多再试 2 次（共 3 次）
LLM_INPUT_MAX_CHARS = 800  # 输入超长时截断到此字符数，避免超时或截断 JSON
# 熔断：连续失败次数超过此后，在 cooldown 秒内不再请求 LLM，直接返回原文
LLM_CIRCUIT_BREAKER_FAILURES = 3
LLM_CIRCUIT_BREAKER_COOLDOWN_SEC = 30
# OCR 超时（秒），防止单次 OCR 卡死管道
OCR_FUTURE_TIMEOUT_SEC = 15

# 用户指令 Agent：解释窗口 + 读/翻译/读音/例句（快捷键）
ENABLE_EXPLANATION_WINDOW = False  # 解释窗口已移除
EXPLANATION_WINDOW_WIDTH = 480
EXPLANATION_WINDOW_HEIGHT = 360
# 快捷键：R=朗读当前识别内容  T=翻译  P=读音/拼音  E=例句
KEY_READ = ord("r")   # 小写 r
KEY_TRANSLATE = ord("t")
KEY_PRONOUNCE = ord("p")
KEY_EXAMPLES = ord("e")
# 用户指令 LLM 超时与长度
USER_CMD_LLM_TIMEOUT_SEC = 20
USER_CMD_INPUT_MAX_CHARS = 400
USER_CMD_MAX_TOKENS = 350
# 翻译目标语言：zh=中文 en=英文
USER_CMD_TRANSLATE_TARGET = "zh"

# 语音助手 Agent：对话式助手，识别意图（朗读/翻译/读音/例句等），对话在「语音助手」窗口显示
ENABLE_VOICE_ASSISTANT = True
CHAT_WINDOW_WIDTH = 520
CHAT_WINDOW_HEIGHT = 420
CHAT_HISTORY_MAX = 32          # 保留最近 N 条对话（用户+助手各算一条）
KEY_CHAT_INPUT = ord("i")      # I = 弹出文字输入框，与助手对话
KEY_VOICE_INPUT = ord("v")     # V = 语音输入（需安装 SpeechRecognition + pyaudio）
# 语音识别引擎：google=谷歌网页 API（需联网）；whisper=本地 Whisper（更准、可离线，需 pip install openai-whisper）
# Windows 上 Whisper 可能报 WinError 127（DLL/依赖缺失），此时会自动回退到谷歌识别
VOICE_RECOGNITION_ENGINE = "whisper"
# 录音后是否先降噪再识别（需 pip install noisereduce，可选）
VOICE_REDUCE_NOISE = True
# 「读一下」短路：当用户说读一下且当前画面文字置信度 >= 此值时，不走 LLM，直接朗读
VOICE_READ_DIRECT_CONFIDENCE = 0.90   # 0.9 = 90%
VOICE_READ_COMMAND_KEYWORDS = ("读一下", "读出来", "朗读", "读一下视频")
# 语音助手 LLM 超时：thinking 模型（如 qwen3-vl-8b-thinking）需更长时间，否则会 Client disconnected
VOICE_ASSISTANT_TIMEOUT_SEC = 90
# thinking 模型先输出推理再给结论，需留足空间避免在 [ACTION:xxx] 前被截断（length）；翻译等内容由后续单独请求返回，不占此限额
VOICE_ASSISTANT_MAX_TOKENS = 700
# 界面只展示「结论」的最大字数，超过则从回复末尾提取短句（过滤 thinking 冗长推理）
VOICE_ASSISTANT_DISPLAY_MAX_CHARS = 80
# 助手系统提示：极简回复避免超时断连，禁止长篇推理；thinking 模型也请把结论放在最后一行
VOICE_ASSISTANT_SYSTEM = """你是摄像头 OCR 应用的语音助手。用户说中文或英文。

硬性规则：你的回复必须极短，总长度不超过 80 字。禁止输出推理、分析、首先、Let's、We are given、Okay 等。只输出一句简短结论，需要时加一行 [ACTION:xxx]。

根据用户意图在回复中加对应标签（单独一行）。标签触发后，系统会用「当前摄像头已识别的文字」执行，并把结果显示在对话框里；你只需输出结论+标签，不要自己翻译/写读音/写例句：
- 朗读/读一下/读出来/读一下视频 → [ACTION:read]（朗读当前识别文字）
- 翻译 → [ACTION:translate]（系统将当前识别文字翻译后显示在对话框）
- 读音/拼音/怎么读 → [ACTION:pronounce]（系统给出读音后显示在对话框）
- 例句/举例 → [ACTION:examples]（系统给出例句后显示在对话框）
- 把识别到的文字发到对话/发到这里 → [ACTION:send_ocr_result]
其他（打招呼、问功能）只回复一句，不加 ACTION。

若你习惯先推理再结论：请务必在最后单独一行输出结论和 [ACTION:xxx]，例如最后一行：好的，正在朗读。\n[ACTION:read]
（界面只会展示最后这句短结论，前面的推理不会显示。）

示例：用户说「翻译」→ 你只回复：好的，正在翻译。\n[ACTION:translate]"""

# 对话框内展示给用户的功能说明（无对话时显示）
DIALOG_FEATURE_PROMPT = """【可用功能】摄像头会实时识别画面中的文字，您可以说或输入：

· 读一下 / 读出来 / 读一下视频 —— 朗读摄像头窗口上当前识别并显示的那段文字
· 翻译 —— 把当前文字翻译成目标语言
· 读音 / 拼音 / 怎么读 —— 显示当前文字的读音或音标
· 例句 —— 给出当前词句的例句
· 把识别到的文字发到这里 / 发到对话框 —— 将当前识别结果显示在对话中

操作方式：下方输入框打字后点「发送」或回车；或按住「语音」说话，松开结束。"""

# 视觉 LLM：用本地/云端视觉模型从截图提取文字，与 OCR 交叉验证
ENABLE_VISION_LLM = False   # 需视觉模型（如 gpt-4o / Qwen-VL / LLaVA），LM Studio 需加载视觉模型
VISION_LLM_MODEL = ""      # 空则用 LLM_MODEL（当前 qwen3-VL-8b-thinking 支持识图）
VISION_LLM_TIMEOUT_SEC = 20
VISION_LLM_MAX_TOKENS = 500
VISION_LLM_MAX_LONG_EDGE = 1024   # 图长边上限，超则缩放以省显存/流量
# 交叉验证模式：show_both=同时显示OCR与Vision  prefer_ocr=以OCR为准  prefer_vision=以Vision为准  merge_llm=LLM合并两者
CROSS_VALIDATE_MODE = "show_both"

# Agent C：严格纠错系统提示（要求只输出 JSON，禁止推理与解释）
STRICT_CORRECTION_SYSTEM = """You are a proofreader. Output ONLY a single JSON object. No reasoning, no "Okay", no explanation. The first character of your reply MUST be { and the last must be }.

Rules: Fix only spelling, punctuation, case, spaces, French contractions. Do not change meaning or rephrase.

Format (output nothing else):
{"original":"<exact input>","corrected":"<corrected text>","changes":[{"from":"...","to":"..."}],"confidence":0.0,"language_hint":"en|fr|zh|mixed"}
If no change: corrected equals original, changes is [].

Example. Input: "helo world". Output: {"original":"helo world","corrected":"hello world","changes":[{"from":"helo","to":"hello"}],"confidence":0.9,"language_hint":"en"}"""
# Agent C：用户 prompt 模板，占位符 {text} 会被待纠错文本替换
STRICT_CORRECTION_USER_TEMPLATE = """Correct the text below (spelling/punctuation/case/spaces only). Output ONLY the JSON object, no other words:

{text}"""

# 中文显示字体（Windows 常见）
FONT_PATHS = [
    "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",  # 黑体
    "C:/Windows/Fonts/simsun.ttc",  # 宋体
]
DEFAULT_FONT = FONT_PATHS[0]

# 语音朗读（朗读 Agent：先识别英/法再选发音人）
ENABLE_TTS = True
# 按语言选择发音人（朗读 Agent 自动检测语言后选用）
TTS_VOICE_EN = "en-US-JennyNeural"
TTS_VOICE_FR = "fr-FR-DeniseNeural"
# 无法检测或非英法时使用的默认语言（用于选发音人）
TTS_DEFAULT_LANG = "en"
TTS_RATE = "+0%"   # 语速，如 "+5%" 略快、"-10%" 略慢
# 纠错结果稳定后再朗读：最近 N 次中至少 K 次相同/相似才触发朗读
TTS_DEBOUNCE_HISTORY_LEN = 3
TTS_DEBOUNCE_MIN_VOTES = 2
TTS_DEBOUNCE_SIMILARITY = 0.92       # 相似度 >= 此视为同一段（用于稳定判断）
# 仅当未装 edge-tts 时用 pyttsx3 兜底
TTS_PYTTSX_RATE = 150
TTS_PYTTSX_VOICE_ID = None  # 留空用系统默认；可填部分 id 匹配

# 日志（Agent D：滚动 + 可选 debug 存帧）
LOG_DIR = os.path.join(_ROOT_DIR, "logs")
LOG_TO_FILE = True
LOG_ROTATING_MAX_BYTES = 5 * 1024 * 1024  # 5MB 滚动
LOG_BACKUP_COUNT = 3
LOG_DEBUG_SAVE_FRAMES = 0   # 非 0 时在异常或周期保存最近 N 帧到 logs/frames/
METRICS_LOG_INTERVAL_SEC = 30  # 每 N 秒打一条指标（fps/ocr_ms/llm_ms/pending）
# 摄像头断线重试
CAMERA_REOPEN_RETRIES = 3
CAMERA_REOPEN_DELAY_SEC = 2
