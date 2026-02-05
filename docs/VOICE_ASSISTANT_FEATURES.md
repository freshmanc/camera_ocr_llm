# 语音助手功能核对清单

以下功能均已对接，可直接使用。

---

## 一、界面按钮与入口（chat_window.py）

| 功能 | 入口 | 状态 |
|------|------|------|
| **发送** | 输入框回车或点击「发送」 | ✅ `_on_send` → `set_pending_chat(msg)` |
| **语音** | 按住「语音」说话、松开结束 | ✅ `_on_mic_press` / `_on_mic_release` → 录音 → 识别 → `set_pending_chat(text)` |
| **上传** | 点击「上传」选择 .txt/.pdf/.docx | ✅ `_on_upload` → `set_uploaded_file`，下次发消息时附带内容给 LLM |
| **打开/关闭摄像头** | 点击「打开摄像头」/「关闭摄像头」 | ✅ `_on_toggle_camera` → `toggle_camera_wanted()` |
| **截图识别** | 点击「截图识别」（有画面用当前帧，无则选图） | ✅ `_on_screenshot_recognize` → `set_pending_screenshot(frame)` |
| **当前识别** | 顶部「当前识别」区域 | ✅ 由 `update_from_state` 从 `get_latest_result()` 的 corrected/debounced_ocr 更新 |
| **对话区 + 播放** | 助手回复带音频时显示「🔊 播放」 | ✅ 历史渲染时插入按钮，`_play_audio_in_app` 播放 |
| **关闭窗口退出** | 点击窗口关闭按钮 | ✅ `_on_window_close` → `set_quit_requested(True)`，主循环检测后退出 |

---

## 二、键盘快捷键（main.py，摄像头窗口焦点时）

| 按键 | 功能 | 状态 |
|------|------|------|
| **R** | 朗读当前识别文字 | ✅ `set_pending_user_command("read", content)` |
| **T** | 翻译当前画面文字 | ✅ `set_pending_user_command("translate", content)` |
| **P** | 读音/音标 | ✅ `set_pending_user_command("pronounce", content)` |
| **E** | 例句 | ✅ `set_pending_user_command("examples", content)` |
| **C** | 打开/关闭摄像头与识别 | ✅ `set_camera_wanted` + 创建/销毁窗口 |
| **Q** | 退出程序 | ✅ break 主循环 |

---

## 三、对话/语音触发的逻辑（worker.py）

| 用户说/输入 | 处理逻辑 | 状态 |
|-------------|----------|------|
| **读一下 / 读出来 / 朗读**（且有画面文字） | 直接 TTS，不经过 LLM，结果带「🔊 播放」 | ✅ `VOICE_READ_COMMAND_KEYWORDS` + `get_content_and_confidence_for_command` |
| **记录学情 / 记下来 / 记录**（法语教学模式） | 将当前/上一句写入学情文件 | ✅ `append_learning_record` |
| **出卷子 / 生成试卷** | 用上传内容或当前画面生成试卷 | ✅ `generate_exam_paper` |
| **批改 / 批改试卷** | 用上传的答案文件 + 上次试卷答案批改 | ✅ `grade_exam` |
| **其他对话**（直接 LLM 模式） | 流式/非流式调用 `chat_direct_llm_stream` 或 `chat_direct_llm`，可带上传文件 | ✅ `VOICE_ASSISTANT_DIRECT_LLM` |
| **其他对话**（意图解析模式） | `chat_with_assistant` → 根据 `[ACTION:xxx]` 执行 read/translate/pronounce/examples/translate_previous/send_ocr_result | ✅ 非 DIRECT 时走此分支 |

---

## 四、后台管道（worker.py）

| 来源 | 处理 | 状态 |
|------|------|------|
| **pending_command**（R/T/P/E 或助手下发的 action） | read → TTS 写对话；translate/pronounce/examples → user_command_agents | ✅ `get_and_clear_pending_command` |
| **pending_chat**（发送/语音消息） | 读一下短路 / 记录学情 / 出卷 / 批改 / 直接 LLM / 意图解析 | ✅ `get_and_clear_pending_chat` |
| **pending_screenshot**（截图识别） | 单帧 OCR + LLM，结果写回 `set_latest_result` | ✅ `get_and_clear_pending_screenshot` |

---

## 五、配置与数据（config / shared_state）

- **当前识别内容**：worker 与助手通过 `get_content_for_command()` 读取，来源为 `latest_result.corrected` / `debounced_ocr`（主循环每帧由 worker 更新），无需额外回调。
- **法语教学**：`FRENCH_TEACHING_MODE = True` 时启用学情文件与专家人设；`VOICE_ASSISTANT_SYSTEM_DIRECT` 可覆盖系统提示。
- **流式回复**：`VOICE_ASSISTANT_USE_STREAM = True` 时边收边显示；`start_streaming` / `append_streaming_delta` / `finish_streaming` 在 shared_state 与 chat_window 中已接好。

---

## 六、结论

语音助手上**发送、语音、上传、打开/关闭摄像头、截图识别、当前识别、播放、关闭退出**，以及**键盘 R/T/P/E/C/Q** 和**对话内的读一下、记录学情、出卷、批改、直接 LLM/意图解析**均具备且已对接；无需新增接线即可使用。
