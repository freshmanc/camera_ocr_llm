# Agent D：工程鲁棒性（崩溃/异常/日志）

## 1. 异常处理清单

| 异常类型 | 发生位置 | 处理方式 | 是否导致退出 |
|----------|----------|----------|--------------|
| **摄像头断开/读帧失败** | main：`cap.read()` 返回 False | 记录 ERROR 日志；可选重试重新打开摄像头（有限次数）；仍失败则退出主循环 | 重试耗尽后退出 |
| **摄像头打开失败** | main：`cap.isOpened()` 为 False | 打日志并 return 1 | 是 |
| **OCR 异常/超时** | worker：`future_ocr.result(timeout)` 或 `run_ocr()` 内部 | 捕获后设 ocr_ok=False，写 error_msg，显示“OCR异常”；不抛到主线程 | 否 |
| **LLM 超时/断网** | worker：`future_llm.result(timeout)` 或 `correct_with_llm` | 熔断 + 降级返回原文，写 error_msg；不抛到主线程 | 否 |
| **Unicode/字体问题** | overlay：`draw_text_block` 中 PIL/字体渲染 | try/except 单行；失败则该行用 ASCII 占位或跳过，不崩整个绘制 | 否 |
| **set_frame/get_latest_result 异常** | shared_state 锁内 | 锁内只做读写，避免长时间持锁；若出现异常由调用方捕获 | 否 |
| **预处理异常** | preprocess / ocr_engine | 已有 try 返回原图或上一步；不向上抛 | 否 |
| **主循环单帧异常** | main：任一步（set_frame、build_display_lines、draw、imshow） | 整帧 try/except，打日志并 continue，避免一帧错误导致退出 | 否 |
| **管道线程未捕获异常** | worker：_pipeline_loop | 最外层 while True 包 try/except，记录后 continue，保证管道线程不退出 | 否 |

---

## 2. 代码结构建议

- **主线程**：只做「读帧 → set_frame → get_latest_result → 绘制 → imshow → waitKey」；所有步骤包在一帧级 try/except 内；读帧失败时走摄像头重连逻辑（可选）。
- **管道线程**：`_pipeline_loop` 最外层 `while True` 内包 `try/except Exception`，单次循环异常只打日志并 `continue`，不退出线程。
- **overlay**：`draw_text_block` 内对每一行绘制包 try/except，单行失败则跳过该行或替换为安全字符串（如 `?`），避免 Unicode/字体导致整块绘制失败。
- **日志**：统一通过 `logger_util` 写；使用滚动日志（按大小或按天），避免单文件无限增大；可选 debug 时保存最近 N 帧到 `logs/frames/`（仅在异常或按间隔写入）。

---

## 3. 简洁日志方案

- **目标**：跑一天不崩、问题可追溯、磁盘不爆。
- **滚动日志**：单文件最大 `LOG_ROTATING_MAX_BYTES`（如 5MB），保留 `LOG_BACKUP_COUNT` 个备份（如 3），文件名 `camera_ocr_llm.log`、`camera_ocr_llm.log.1` …
- **级别**：INFO 正常启动/周期指标；ERROR 摄像头/OCR/LLM/字体异常；RESULT 可选，单次 OCR+LLM 结果摘要。
- **周期指标**（每 METRICS_LOG_INTERVAL_SEC 秒一条）：帧率(fps)、最近 OCR 耗时(ms)、最近 LLM 耗时(ms)、待处理帧数(pending，单槽下为「自上次 OCR 以来的帧数」)。
- **可选 debug**：`LOG_DEBUG_SAVE_FRAMES > 0` 时，在 OCR 异常或 LLM 异常时将当前帧写入 `logs/frames/`（文件名带时间戳），并只保留最近 N 张（如 10），便于事后复现。

---

## 4. 指标说明

| 指标 | 含义 | 来源 |
|------|------|------|
| 帧率 (fps) | 主循环每秒渲染帧数 | main：按时间窗口计 frame_count |
| OCR 耗时 (ms) | 最近一次 OCR 用时 | DisplayResult.ocr_time_ms |
| LLM 耗时 (ms) | 最近一次 LLM 用时 | DisplayResult.llm_time_ms |
| 队列长度 / pending | 单槽设计下无传统队列；用「自上次 OCR 以来主线程写入的帧数」表示积压 | SharedState：frame_count - last_ocr_frame_count（只读快照） |
