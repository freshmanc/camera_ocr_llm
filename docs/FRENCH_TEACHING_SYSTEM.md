# 法语教学系统

在现有「摄像头 OCR + 语音助手 + TTS + 翻译/读音/例句」基础上，通过配置与人设、学情文件，组成**法语教学系统**：助手以「法语教学专家」身份，结合当前画面与学情做讲解、问答、考核与评价。

---

## 目标与对应实现

| 目标 | 实现方式 |
|-----|----------|
| **看见并讲解** | 摄像头 OCR（PaddleOCR，可设 `PADDLE_OCR_LANG = "fr"`）→ 纠错 → 对话时把「当前画面文字」发给 LLM；用户说「精讲」「翻译」「读音」「例句」即得到讲解/翻译/读音/例句。 |
| **语音 + 文字问答** | 语音输入（Whisper/谷歌）+ 文字输入；助手流式回复；「读一下」走 TTS 朗读。 |
| **了解学情** | 【长期记忆】= `VOICE_ASSISTANT_MEMORY` + **学情文件**（`logs/learning_context.txt`）内容；助手每次对话都能看到学情摘要。 |
| **考核与评价** | 用户说「考考我」「给我评价」等，由 LLM 根据当前画面 + 对话历史 + 学情摘要口头出题或给评价与建议。 |
| **记录学情** | 用户说「记录学情」「记下来」「记录」→ 系统将「上一句朗读内容」或「当前画面文字」追加入学情文件，不调用 LLM。 |

---

## 已复用的现有功能

- **OCR**：`tools/ocr_engine`、去抖、LLM 纠错（`agents/llm_correct`）
- **语音助手**：`agents/voice_assistant_agent`（直接对接 LLM、流式）、`worker` 中的 pending_chat 处理
- **对话窗口**：`tools/chat_window`（打字、语音、播放、流式刷新）
- **TTS**：`agents/tts_agent`（朗读、「读一下」短路）
- **翻译/读音/例句**：`agents/user_command_agents`（translate_with_llm、pronunciation_with_llm、examples_with_llm），由对话意图或快捷键触发
- **共享状态**：`shared_state`（对话历史、当前内容、上一句朗读内容）

---

## 配置说明（config/__init__.py）

- **`FRENCH_TEACHING_MODE = True`**：启用法语教学系统；助手使用法语教学专家人设，并注入学情文件内容到长期记忆。
- **`FRENCH_TEACHING_LEARNING_FILE`**：学情文件路径（默认 `logs/learning_context.txt`），内容会作为【学情摘要】拼入系统提示。
- **`FRENCH_EXPERT_SYSTEM_PROMPT`**：法语教学专家系统提示；当 `FRENCH_TEACHING_MODE=True` 且 `VOICE_ASSISTANT_SYSTEM_DIRECT` 为空时使用。
- **`VOICE_ASSISTANT_MEMORY`**：固定长期记忆（如「学生 A1、常练过去时」），与学情文件内容一起组成【长期记忆】。
- **`VOICE_ASSISTANT_SYSTEM_DIRECT`**：若不为空，优先于 `FRENCH_EXPERT_SYSTEM_PROMPT`，可完全自定义人设。

法语教学模式下，对话框会多出一段说明（`DIALOG_FRENCH_TEACHING_PROMPT`），提示「精讲」「考考我」「给我评价」「记录学情」等用法。

---

## 学情模块（agents/learning_context.py）

- **`get_learning_summary_for_prompt(max_chars=1200)`**：读取学情文件，截断到指定字数，供拼入【长期记忆】。
- **`append_learning_record(content, prefix="已学/已讲: ")`**：将一条记录追加到学情文件；文件超过约 200 行时保留最近部分。

学情文件为 UTF-8 文本，每行一条记录；可手动编辑。说「记录学情」时，优先记录「上一句朗读内容」，若无则记录「当前画面文字」。

---

## 使用流程建议

1. **开启**：`FRENCH_TEACHING_MODE = True`，运行主程序，打开语音助手窗口。
2. **看见并讲解**：摄像头对准法语材料，说「精讲」「翻译」「读音」「例句」或直接提问。
3. **记录学情**：读一下或翻译某句后，说「记录学情」或「记下来」，该内容会写入学情文件，后续对话中老师会参考。
4. **考核与评价**：说「考考我」「给我评价」，助手根据当前画面与学情做口头考核或学习建议。
5. **长期记忆**：在 `VOICE_ASSISTANT_MEMORY` 中写一两句固定学情（如水平、薄弱点），或定期整理学情文件内容。

---

## 关闭法语教学系统

- 设 **`FRENCH_TEACHING_MODE = False`**，助手恢复为通用摄像头 OCR 对话助手，不再注入学情文件，也不处理「记录学情」快捷语。
