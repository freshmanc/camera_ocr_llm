# -*- coding: utf-8 -*-
"""全局配置：摄像头、OCR、LLM、超时与降级"""
import os

# 项目根目录（config 包所在目录的上一级）
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 摄像头（高分辨率利于 OCR 清晰度，建议 1280x720 及以上）
CAMERA_INDEX = 0
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
# 启动时是否显示摄像头实时画面；False 则只显示占位，可在对话窗口点「打开摄像头」调出
CAMERA_WINDOW_START_VISIBLE = True
# 按需启停：按此键或点对话窗口「打开/关闭摄像头」切换，默认不打开摄像头（避免报错）
KEY_TOGGLE_CAMERA = ord("c")   # C 键
CAMERA_START_OFF = True       # True=启动时不打开摄像头，按 C 或点按钮再开
# 识别文字在摄像头画面上的显示方式：full=全文叠加 minimal=仅角落一两行不挡视线 none=不叠加（全文在对话窗口「当前识别」看）
OCR_DISPLAY_ON_CAMERA = "minimal"
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
LLM_MODEL = "qwen3-vl-8b"  # 本地视觉语言模型，LM Studio 中显示的 id 为准（非 thinking 版更快）
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

# 语音助手 Agent：对话式助手，对话在「语音助手」窗口显示
ENABLE_VOICE_ASSISTANT = True
# True=对话窗口只做中转：用户消息+历史直接发给 LLM，回复原样显示（除「读一下」走 TTS 短路）；False=沿用 [ACTION:xxx] 意图解析
VOICE_ASSISTANT_DIRECT_LLM = True
# 语音助手专用模型/地址：thinking 模型慢 1～2 分钟，可改为更快模型或另开 LM Studio
# 空则用上面的 LLM_MODEL / LLM_BASE_URL；若 LM Studio 另开一个实例跑快模型（如 qwen3-8b），填下面
VOICE_ASSISTANT_BASE_URL = ""   # 例：http://127.0.0.1:1235/v1（第二台 LM Studio）
VOICE_ASSISTANT_MODEL = ""      # 例：qwen3-8b（非 thinking），空则用 LLM_MODEL
CHAT_WINDOW_WIDTH = 520
CHAT_WINDOW_HEIGHT = 420
CHAT_HISTORY_MAX = 64          # 保留最近 N 条对话（短期记忆，用户+助手各算一条）
VOICE_ASSISTANT_CONTEXT_MESSAGES = 24   # 传给 LLM 的最近对话条数，便于理解上下文
VOICE_ASSISTANT_MEMORY = ""    # 长期记忆：写在这里的内容会追加到系统提示，LLM 始终可见（如学情摘要、学生水平）
# 直接对话模式下的系统人设（VOICE_ASSISTANT_DIRECT_LLM=True 时用）。空则用默认通用助手。
# 法语教学专家示例见 docs/PRODUCT_VISION_FRENCH_EXPERT.md，复制到下面并去掉三引号即可启用。
# VOICE_ASSISTANT_SYSTEM_DIRECT = """你是一位耐心的法语教学专家..."""
VOICE_ASSISTANT_SYSTEM_DIRECT = ""
KEY_CHAT_INPUT = ord("i")      # I = 弹出文字输入框，与助手对话
KEY_VOICE_INPUT = ord("v")     # V = 语音输入（需安装 SpeechRecognition + pyaudio）
# 语音识别引擎：google=谷歌网页 API（需联网）；whisper=本地 Whisper（更准、可离线，需 pip install openai-whisper）
# Windows 上 Whisper 可能报 WinError 127（DLL/依赖缺失），此时会自动回退到谷歌识别
VOICE_RECOGNITION_ENGINE = "whisper"
# 录音后是否先降噪再识别（需 pip install noisereduce，可选）
VOICE_REDUCE_NOISE = True
# 「读一下」：只要有画面文字就优先直接朗读，不走 LLM，避免顺序错乱和延迟；仅当无文字时才走 LLM
VOICE_READ_DIRECT_CONFIDENCE = 0.0    # 有内容即直接读，0 表示不要求置信度
VOICE_READ_COMMAND_KEYWORDS = ("读一下", "读出来", "朗读", "读一下视频")
# 语音助手 LLM 超时（非 thinking 模型一般十几秒内可回复）
VOICE_ASSISTANT_TIMEOUT_SEC = 90
# 是否使用流式请求（stream=True）：LM Studio 0.3.x 支持，可边收边显示、减少断连；若仍断连或模型不支持可改为 False
VOICE_ASSISTANT_USE_STREAM = True
# thinking 模型先输出推理再给结论，需留足空间避免在 [ACTION:xxx] 前被截断（length）；日志见 completion_tokens 达 686+ 仍截断则再调大
VOICE_ASSISTANT_MAX_TOKENS = 950
# 界面只展示「结论」的最大字数，超过则从回复末尾提取短句（过滤 thinking 冗长推理）
VOICE_ASSISTANT_DISPLAY_MAX_CHARS = 80
# 助手系统提示：极简回复避免超时断连，禁止长篇推理；thinking 模型也请把结论放在最后一行
VOICE_ASSISTANT_SYSTEM = """你是摄像头 OCR 应用的语音助手。用户说中文或英文。

硬性规则：你的回复必须极短，总长度不超过 80 字。禁止输出推理、分析、首先、Let's、We are given、Okay 等。只输出一句简短结论，需要时加一行 [ACTION:xxx]。

根据用户意图在回复中加对应标签（单独一行）。标签触发后由系统执行并显示结果；你只输出一句结论+标签，不要自己写翻译/读音/例句正文：
- 朗读/读一下/读出来/读一下视频 → [ACTION:read]（朗读当前画面文字）
- 翻译（当前画面）→ [ACTION:translate]（系统翻译当前画面文字并显示）
- 翻译之前的/上一句/刚才的/刚才那句 → [ACTION:translate_previous]（系统翻译对话里上一次朗读的【内容】并显示）
- 读音/拼音/怎么读 → [ACTION:pronounce]
- 例句/举例 → [ACTION:examples]
- 把识别到的文字发到对话/发到这里 → [ACTION:send_ocr_result]
其他（打招呼、问功能）只回复一句，不加 ACTION。

若你习惯先推理再结论：请务必在最后单独一行输出结论和 [ACTION:xxx]，例如最后一行：好的，正在朗读。\n[ACTION:read]
（界面只会展示最后这句短结论，前面的推理不会显示。）

示例：用户说「翻译」→ 你只回复：好的，正在翻译。\n[ACTION:translate]。用户说「翻译之前的句子」→ 你只回复：好的，正在翻译上一句。\n[ACTION:translate_previous]"""

# ========== 法语教学系统（复用上述 OCR / 语音助手 / TTS / 翻译 等）==========
# True=启用法语教学专家人设 + 学情文件；助手会结合「当前画面」与学情做讲解、问答、考核与评价
FRENCH_TEACHING_MODE = True
# 学情记录文件路径（相对项目根）：内容会作为【学情摘要】注入助手长期记忆；可说「记录学情」把当前/上一句写入
FRENCH_TEACHING_LEARNING_FILE = "logs/learning_context.txt"
# 法语教学专家系统提示（FRENCH_TEACHING_MODE=True 且 VOICE_ASSISTANT_SYSTEM_DIRECT 为空时使用）
FRENCH_EXPERT_SYSTEM_PROMPT = """你是一位耐心的法语教学专家，面向中文母语学生。你能「看见」学生摄像头拍到的法语材料（系统会提供「当前画面文字」）。

你的能力：
- 对看见的法语进行讲解：语法、词汇、发音要点、常见错误。学生说「精讲」「翻译」「读音」「例句」时请结合画面作答。
- 用中文或中法混合回答学生问题（语音或打字均可）。
- 根据对话和「长期记忆」中的学情摘要，简要了解学生进度与薄弱点。
- 可应学生要求做简单考核或学习建议（如「考考我」「给我评价」：根据当前画面或最近内容提问、或给一句评价与下一步建议）。

回复请自然、简洁、有针对性；若当前画面有法语内容，可结合画面作答。"""

# 对话框内展示给用户的功能说明（无对话时显示）；法语教学模式下会追加学情与考核说明
DIALOG_FEATURE_PROMPT = """【可用功能】摄像头会实时识别画面中的文字，您可以说或输入：

· 读一下 / 读出来 / 读一下视频 —— 朗读当前识别文字，对话中会显示【内容】和「播放」按钮
· 翻译 —— 把当前画面文字翻译；「翻译之前的句子」—— 翻译对话里上一次朗读的【内容】
· 读音 / 拼音 / 怎么读 —— 显示当前文字的读音或音标
· 例句 —— 给出当前词句的例句
· 把识别到的文字发到这里 / 发到对话框 —— 将当前识别结果显示在对话中

操作方式：下方输入框打字后点「发送」或回车；或按住「语音」说话，松开结束。"""
# 法语教学模式下追加的说明（与上面拼接后显示）
DIALOG_FRENCH_TEACHING_PROMPT = """

【法语教学】老师会结合当前画面与你的学情作答。你还可以说：
· 精讲 / 精讲刚识别的 —— 对当前画面法语做语法、词汇、用法讲解
· 考考我 / 给我评价 —— 根据当前或最近内容做简单考核或学习评价
· 记录学情 / 记下来 —— 把当前或上一句内容记入学情，方便老师后续参考
· 出卷子 / 生成试卷 —— 根据当前画面或上传材料生成 TXT/PDF/Word 试卷（答案另存）
· 批改试卷 —— 上传你的答案文件后说「批改试卷」，系统会批改并讲解
· 点击「上传」可上传 TXT/PDF/Word，老师会结合文件内容回答或出题"""

# 考试功能：生成试卷（TXT/PDF/Word）、批改、讲解
EXAM_OUTPUT_DIR = "logs/exams"
EXAM_DEFAULT_FORMAT = "txt"   # txt | pdf | docx
EXAM_NUM_QUESTIONS = 5
EXAM_LLM_TIMEOUT_SEC = 60
EXAM_LLM_MAX_TOKENS = 1500

# 视觉 LLM：用本地/云端视觉模型从截图提取文字，与 OCR 交叉验证
ENABLE_VISION_LLM = False   # 需视觉模型（如 gpt-4o / Qwen-VL / LLaVA），LM Studio 需加载视觉模型
VISION_LLM_MODEL = ""      # 空则用 LLM_MODEL（qwen3-vl-8b 支持识图）
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
# 强制朗读语言：设为 "fr" 或 "en" 时不再自动检测，直接用法语/英语读（OCR 无重音时用法语可设 TTS_FORCE_LANG = "fr"）
TTS_FORCE_LANG = ""
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
