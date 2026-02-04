# 语音助手 Agent

通过**对话**与本地 LLM 交互，用自然语言说出需求（如「读一下」「翻译」「读音」「例句」），助手理解后回复并在需要时触发对应功能；**对话内容在「语音助手」窗口中以文字形式展示**，类似聊天框。

## 界面与操作

- **语音助手窗口**：单独窗口显示「我」与「助手」的对话历史，可滚动查看。
- **I 键**：弹出文字输入框，输入要说的话（如：读一下、翻译、读音、例句、你好）。
- **V 键**：语音输入（需安装 `SpeechRecognition` 和 `pyaudio`），默认使用 Google 在线识别，可改为本地引擎。

## 流程

1. 用户按 **I** 输入文字或按 **V** 说话 → 内容作为一条「用户」消息加入对话并提交给后台。
2. 后台用**本地 LLM**（与纠错同一模型）生成助手回复；若回复中包含 `[ACTION:read]` / `[ACTION:translate]` 等，则自动触发朗读/翻译/读音/例句（使用当前识别到的文字）。
3. 助手回复（去掉 ACTION 标签后）作为「助手」消息加入对话，并在语音助手窗口显示。

## 配置（config/__init__.py）

```python
ENABLE_VOICE_ASSISTANT = True
CHAT_WINDOW_WIDTH = 520
CHAT_WINDOW_HEIGHT = 420
CHAT_HISTORY_MAX = 32
KEY_CHAT_INPUT = ord("i")   # I = 文字输入
KEY_VOICE_INPUT = ord("v")  # V = 语音输入
VOICE_ASSISTANT_TIMEOUT_SEC = 30
VOICE_ASSISTANT_MAX_TOKENS = 400
VOICE_ASSISTANT_SYSTEM = "..."  # 系统提示，说明可触发的 ACTION
```

## 语音输入依赖（可选）

使用 **V 键**语音输入需安装：

```bash
pip install SpeechRecognition pyaudio
```

- 默认使用 `recognize_google`（需联网）。可改为离线引擎（如 `recognize_sphinx`）或本地 Whisper，需自行改 `main.py` 中 `_voice_input` 的调用。

## 实现位置

- **agents/voice_assistant_agent.py**：`chat_with_assistant(user_message, history)`，调用本地 LLM，解析 `[ACTION:xxx]`。
- **worker.py**：处理 `pending_chat`，追加用户/助手消息，根据 action 调用 `set_pending_user_command`。
- **main.py**：「语音助手」窗口绘制、I/V 键处理、文字框（tkinter）、语音录制线程。
- **shared_state.py**：`_chat_history`、`_pending_chat_message`，`append_chat` / `get_chat_history` / `set_pending_chat` / `get_and_clear_pending_chat`。
