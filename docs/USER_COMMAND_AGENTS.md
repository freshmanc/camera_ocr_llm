# 用户指令 Agent：解释窗口与读/翻译/读音/例句

根据用户按键，对**当前识别到的内容**（纠错后或去抖 OCR）执行朗读、翻译、读音、例句，并在**解释窗口**中显示结果。

## 功能概览

| 按键 | 功能 | 说明 |
|------|------|------|
| **R** | 朗读 | 用 TTS 朗读当前识别内容（中/英/法自动选发音人） |
| **T** | 翻译 | 调用 LLM 翻译成目标语言，结果显示在解释窗口 |
| **P** | 读音 | 中文→拼音，英文/法文→音标或发音说明，显示在解释窗口 |
| **E** | 例句 | 调用 LLM 生成 1～2 个例句，显示在解释窗口 |
| **Q** | 退出 | 关闭程序 |

- 按键时以**当前画面上的纠错后文字**为准；若无识别内容，T/P/E 不发起请求，R 会空读（无声音）。
- 翻译/读音/例句使用与纠错相同的 LLM（LM Studio 或 OpenAI），超时与长度见 `config`。

## 配置（config/__init__.py）

```python
ENABLE_EXPLANATION_WINDOW = True   # 是否打开解释窗口
EXPLANATION_WINDOW_WIDTH = 480
EXPLANATION_WINDOW_HEIGHT = 360
KEY_READ = ord("r")
KEY_TRANSLATE = ord("t")
KEY_PRONOUNCE = ord("p")
KEY_EXAMPLES = ord("e")
USER_CMD_LLM_TIMEOUT_SEC = 20
USER_CMD_INPUT_MAX_CHARS = 400
USER_CMD_TRANSLATE_TARGET = "zh"   # 翻译目标：zh=中文 en=英文
```

## 实现位置

- **主线程**（main.py）：捕获 R/T/P/E，将命令与当前内容写入 `SharedState.set_pending_user_command(cmd, content)`；每帧绘制解释窗口。
- **后台管道**（worker.py）：轮询 `get_and_clear_pending_command()`，执行读（TTS）/翻译/读音/例句，结果写入 `set_explanation(title, content)`。
- **Agent**（agents/user_command_agents.py）：`translate_with_llm`、`pronunciation_with_llm`、`examples_with_llm`，复用纠错用的 LLM 客户端与模型。

## 扩展建议

- 语音指令：接入语音识别，将“读一下”“翻译”等转为上述命令。
- 多目标语言：在配置中增加目标语言列表，或通过按键切换（如 T1/T2）。
- 读音后自动朗读：在读音 Agent 返回后可选调用 TTS 朗读原文。
