# 验证清单与最小可验证步骤

## 环境

- Windows + Anaconda
- 摄像头可用
- RTX4060 驱动与 CUDA（可选，EasyOCR 可用 GPU）
- LM Studio 已安装，并已启动本地服务器（端口 1234）

## 最小可验证步骤

### 1. 环境与依赖

```bash
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"
conda create -n ocr_llm python=3.10 -y
conda activate ocr_llm
pip install -r requirements.txt
```

### 2. 启动 LM Studio

- 打开 LM Studio，加载任意中文友好模型（如 Qwen、GLM 等）
- 在 “Local Server” 中启动服务器，端口 **1234**
- 确认 “Server running” 显示为绿色

### 3. 运行主程序（画面必须持续刷新、不卡顿）

```bash
python main.py
```

- 应出现摄像头窗口，画面实时刷新
- 将带中文的文字（纸张/屏幕）对准摄像头，界面应出现：
  - **[原始OCR]** 识别出的原始文本
  - **[纠错后]** LLM 纠错后的文本
  - **[置信度]** 百分比、OCR 耗时、LLM 耗时
- 按 **Q** 退出

### 4. 降级与异常验证

| 场景           | 预期行为 |
|----------------|----------|
| 关闭 LM Studio | 界面不卡死，显示“原始OCR”，状态出现 LLM 超时/断网，纠错后显示与原始一致 |
| 拔掉摄像头     | 程序报错退出或提示“无法打开摄像头” |
| 遮挡镜头/无文字 | 原始OCR 为空或很少，纠错后为空或一致，无崩溃 |

### 5. 可选：日志

- 在 `config.py` 中设置 `LOG_TO_FILE = True`
- 运行后查看 `camera_ocr_llm/logs/camera_ocr_llm.log`，应有 RESULT 行（原始/纠错/置信度/耗时）

## 输出结构说明

- **原始 OCR**：EasyOCR 直接输出，未改
- **纠错后**：仅做错别字/标点/大小写修正，不改语义
- **置信度**：OCR 各检测框置信度平均值
- **耗时**：单次 OCR 毫秒数、单次 LLM 请求毫秒数
- **状态**：OCR 异常或 LLM 超时/断网时在此显示，便于排查

## 常见问题

- **LM Studio 连接失败**：检查 1234 端口、防火墙，或配置中 `LLM_BASE_URL`
- **中文乱码**：安装 Pillow 并确保 `config.FONT_PATHS` 下存在微软雅黑等字体
- **帧率低**：增大 `config.FRAME_SKIP`（如 5 或 10），减少 OCR 频率
