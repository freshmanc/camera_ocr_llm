# Agent A：架构与并发（防冻结核心）

## 1. 推荐的并发结构（文字说明）

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 主线程（唯一允许阻塞的只有 waitKey(1)，绝不等待 OCR/LLM）                    │
│   cap.read() → 写入 [最新帧槽] → 读 [最新显示结果] → 叠加 → imshow() → waitKey(1) │
└─────────────────────────────────────────────────────────────────────────┘
        │                              ▲
        │ 只写“当前帧”覆盖               │ 只读，非阻塞
        ▼                              │
┌───────────────────┐         ┌───────────────────────────────────────────┐
│  最新帧槽（单槽）   │         │  最新显示结果（单槽）                         │
│  仅保留最新一帧     │         │  仅保留最近一次 OCR+LLM 的完整结果            │
│  旧帧直接丢弃       │         │  主线程只读副本，不阻塞                       │
└───────────────────┘         └───────────────────────────────────────────┘
        │                                              ▲
        │ 后台“管道”线程取帧（按 skip 间隔取副本）              │ 管道线程写回
        ▼                                              │
┌─────────────────────────────────────────────────────────────────────────┐
│ 管道线程（单线程循环，或由线程池驱动）                                        │
│   取最新帧(非阻塞) → ThreadPoolExecutor.submit(OCR) → .result(timeout)       │
│                → submit(LLM) → .result(timeout=LLM_TIMEOUT) 或 熔断降级    │
│                → 写回 [最新显示结果]                                        │
└─────────────────────────────────────────────────────────────────────────┘
        │                    │
        ▼                    ▼
┌──────────────┐    ┌──────────────┐
│ OCR 任务     │    │ LLM 任务     │  超时则 Future.result(timeout) 抛异常，
│ 在池中执行   │    │ 在池中执行   │  捕获后降级返回原文，并计入熔断
└──────────────┘    └──────────────┘
```

- **主线程**：只做采集 + 写最新帧槽 + 读最新显示结果 + 绘制 + 显示。不调用任何 OCR/LLM 接口，不调用 `.result()` 等待后台。
- **队列只保留最新**：不用 `Queue.get()` 积压任务；用“单槽 + 覆盖”。最新帧槽 = 主线程每次覆盖同一变量；最新显示结果 = 管道线程完成后覆盖。这样不会因积压导致处理“旧帧”，也不会让主线程等队列。
- **OCR 与 LLM 分离到线程池**：管道线程每次循环 `submit(ocr_fn, frame)` 得到 Future，再 `submit(llm_fn, raw_text)` 得到 Future；对 LLM 的 Future 调用 `.result(timeout=LLM_TIMEOUT_SEC)`，超时则捕获 `TimeoutError`，降级返回原文并触发熔断逻辑。
- **LLM 超时与熔断**：每次 LLM 调用设 `timeout`；连续失败 N 次后进入熔断，在 cooldown 秒内不再请求 LLM，直接返回原文并标记 llm_ok=False。

---

## 2. 关键陷阱与修复点

| 陷阱 | 现象 | 修复 |
|------|------|------|
| 主线程里调用了 LLM 或 OCR | 画面卡住数秒 | 主循环中禁止任何 `requests`/`openai`/`run_ocr`；只允许 `set_frame`、`get_latest_result`、`imshow`、`waitKey`。 |
| 用 Queue 积压多帧 | 延迟越来越大，显示的是很久以前的识别结果 | 改为“单槽覆盖”：只保留“当前要处理的一帧”和“当前显示结果”，新帧覆盖旧帧，不 put 多份。 |
| LLM 无超时 | 断网或 LM Studio 无响应时管道线程一直阻塞 | 用 `future.result(timeout=LLM_TIMEOUT_SEC)` 包住 LLM 调用，捕获 `TimeoutError` 和 `concurrent.futures.TimeoutError`，降级为原文。 |
| 熔断未做 | 服务不可用时仍不断重试，占满线程池或拖慢循环 | 维护连续失败次数与上次失败时间；超过阈值则在一段时间内不再发起 LLM，直接返回原文并写 error_msg。 |
| 管道线程里长时间持锁 | 主线程读 `get_latest_result()` 被阻塞 | 锁只用于读写“最新帧”“最新结果”的几步，不在锁内做 OCR/LLM；复制帧后立刻释放锁再计算。 |
| 写回结果时覆盖了“更新”的结果 | 先完成的旧请求覆盖了后完成的新请求 | 可选：带 generation/frame_id，只有“当前帧 id 与结果 id 一致”才写回；或接受“总是显示最近完成的一次”的语义（通常足够）。 |

---

## 3. Python 代码骨架（Queue / Future / ThreadPoolExecutor）

```python
# ---------- 主线程（main.py）：只做采集 + 显示，禁止任何 .result() 或 OCR/LLM 调用 ----------
while True:
    ret, frame = cap.read()
    if not ret:
        break
    state.set_frame(frame)                    # 覆盖“最新帧”单槽
    res = state.get_latest_result()           # 非阻塞读“最新显示结果”
    frame = draw_text_block(frame, build_display_lines(res)...)
    cv2.imshow(win, frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# ---------- 共享状态（shared_state.py）：单槽覆盖，无 Queue 积压 ----------
class SharedState:
    def set_frame(self, frame):               # 主线程写：覆盖 _current_frame
        with self._lock:
            self._current_frame = frame
            self._frame_count += 1

    def get_frame_for_ocr(self, skip):        # 管道线程读：仅当间隔≥skip 时取副本，不积压
        with self._lock:
            if self._frame_count - self._last_ocr_frame_count < skip:
                return None
            self._last_ocr_frame_count = self._frame_count
            return self._current_frame.copy()

    def get_latest_result(self):              # 主线程读：快照，不阻塞
        with self._lock:
            return copy of self.latest_result

    def set_latest_result(self, ...):         # 管道线程写：覆盖最新结果
        with self._lock:
            self.latest_result = DisplayResult(...)

# ---------- 管道 + 线程池（worker.py）：OCR/LLM 分离，超时与熔断 ----------
executor = ThreadPoolExecutor(max_workers=2)
circuit_breaker = _CircuitBreaker(threshold=3, cooldown_sec=30)

def _pipeline_loop(state, executor, circuit_breaker):
    while True:
        frame = state.get_frame_for_ocr(FRAME_SKIP)   # 只取“当前最新”一帧
        if frame is None:
            time.sleep(0.05)
            continue
        # OCR：池中执行，带超时
        future_ocr = executor.submit(run_ocr, frame)
        raw_text, conf, ocr_ms, ocr_ok, err = future_ocr.result(timeout=OCR_FUTURE_TIMEOUT_SEC)
        if not ocr_ok:
            state.set_latest_result(..., corrected=raw_text, llm_ok=True)
            continue
        # 熔断：连续失败后一段时间内不再请求 LLM
        if circuit_breaker.is_open():
            state.set_latest_result(..., corrected=raw_text, llm_ok=False, error_msg="熔断中")
            continue
        # LLM：池中执行，必须超时，失败则降级原文并 record_failure
        future_llm = executor.submit(correct_with_llm, raw_text)
        try:
            corrected, llm_ms, llm_ok, llm_err = future_llm.result(timeout=LLM_TIMEOUT_SEC)
        except (FuturesTimeoutError, Exception):
            corrected, llm_ok = raw_text, False
            circuit_breaker.record_failure()
        if llm_ok:
            circuit_breaker.record_success()
        state.set_latest_result(raw_ocr=raw_text, corrected=corrected, ...)
        time.sleep(0.05)
```

---

## 4. 与代码的对应关系

- **最新帧槽 / 最新显示结果**：`shared_state.SharedState` 的 `_current_frame` + `latest_result`，锁保护。
- **管道线程**：`worker._pipeline_loop` 循环取帧、提交 OCR/LLM、写回结果。
- **线程池**：`worker` 内 `ThreadPoolExecutor(max_workers=2)`，OCR 与 LLM 分别 `submit`，LLM 用 `future.result(timeout=...)`。
- **熔断**：`worker` 内 `_CircuitBreaker`，连续失败 N 次后 cooldown 秒内跳过 LLM，直接返回原文。
