# 阶段 1：Web API + 单页识别

## 已包含内容

- **后端** `server/main.py`：FastAPI，提供
  - `GET /api/health`：健康检查
  - `POST /api/recognize`：上传图片，返回 OCR + LLM 纠错结果（与桌面「截图识别」逻辑一致）
  - `GET /`、`/app.js`、`/style.css`：前端静态资源（与 API 同源）
- **前端** `web/`：单页
  - 选择图片或拍照 → 点击「识别」→ 显示「初始 OCR」「校验后」、置信度与耗时

## 运行方式

1. **安装依赖**（若尚未安装）  
   ```bash
   pip install fastapi "uvicorn[standard]"
   ```
   或从项目根目录：  
   ```bash
   pip install -r requirements.txt
   ```

2. **启动服务**（必须在项目根目录）  
   - Windows：双击 `run_server.bat`  
   - 或命令行：  
     ```bash
     cd camera_ocr_llm
     python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
     ```

3. **访问**
   - 本机浏览器：<http://127.0.0.1:8000/>
   - 手机（同一局域网）：<http://本机IP:8000/>（如 `http://192.168.1.100:8000/`）

## 与现有桌面端的关系

- **桌面端**：`main.py`、`worker.py`、Tk + OpenCV 不变，照常运行。
- **Web 阶段 1**：仅复用 `tools/ocr_engine.run_ocr`、`agents/llm_correct.correct_with_llm` 与 `config`，不依赖 `shared_state`、`worker` 或 GUI。
- 两套入口可并存：需要本地摄像头与对话窗口时用桌面端；需要网页/手机访问时用 `run_server.bat`。

## 后续阶段（见 ARCHITECTURE_WEB_MOBILE.md）

- 阶段 2：对话接口 `/api/chat`、流式 `/api/chat/stream`，前端对话区。
- 阶段 3：TTS 接口与朗读按钮。
- 阶段 4：响应式与手机优化、可选 PWA。
