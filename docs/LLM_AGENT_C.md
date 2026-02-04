# Agent C：LLM 严格纠错协议（不润色）

## 1. 规则

**只允许修改：**
- 拼写 / 错别字
- 标点符号
- 大小写（英文等）
- 空格（多余或缺失）
- 法语缩合（如 s'ouvriront、l'homme、d'accord）

**禁止：**
- 改写语义
- 扩写、删减信息
- 翻译（原文语种不变）
- 润色、改写风格

---

## 2. 输出协议：仅接受 JSON

**必须**返回且仅返回一个合法 JSON 对象，无前后说明文字。

### JSON Schema

```json
{
  "original": "string   // 与输入完全一致的原文（用于校验）",
  "corrected": "string  // 仅做允许类型修改后的全文",
  "changes": [
    { "from": "原文片段", "to": "修改后片段" }
  ],
  "confidence": 0.0,   // 0~1，纠错置信度",
  "language_hint": "zh|en|fr|mixed"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| original | string | 是 | 与用户输入逐字一致，便于服务端校验 |
| corrected | string | 是 | 仅经允许修改后的整段文本 |
| changes | array | 是 | 本次修改列表，无修改则为 [] |
| confidence | number | 是 | 0~1，对本次纠错的置信度 |
| language_hint | string | 是 | zh / en / fr / mixed |

---

## 3. 可直接用于 LM Studio 的 Prompt 模板

### System（固定）

```
你是一个严格纠错助手。只做以下修改，其他一律禁止：
允许：拼写/错别字、标点、大小写、空格、法语缩合（如 s'ouvriront）。
禁止：改写语义、扩写、删减、翻译、润色。

你必须且只输出一个 JSON 对象，不要输出任何其他文字。格式如下：
{"original":"<与输入完全一致的原文>","corrected":"<仅允许类型修改后的全文>","changes":[{"from":"...","to":"..."}],"confidence":0.0,"language_hint":"zh|en|fr|mixed"}
若无修改，corrected 与 original 相同，changes 为 []。confidence 为 0~1。
```

### User（每次请求）

```
请对以下文本做严格纠错（仅拼写/错别字/标点/大小写/空格/法语缩合），并只输出上述 JSON，不要解释：

<此处替换为待纠错文本>
```

---

## 4. 示例

**输入：**  
`今天天汽很好，我们一起去公圆吧。`

**输出（仅此 JSON）：**
```json
{
  "original": "今天天汽很好，我们一起去公圆吧。",
  "corrected": "今天天气很好，我们一起去公园吧。",
  "changes": [
    { "from": "天汽", "to": "天气" },
    { "from": "公圆", "to": "公园" }
  ],
  "confidence": 0.95,
  "language_hint": "zh"
}
```

**输入：**  
`il s ouvriront demain`

**输出：**
```json
{
  "original": "il s ouvriront demain",
  "corrected": "ils s'ouvriront demain",
  "changes": [
    { "from": "il s ouvriront", "to": "ils s'ouvriront" }
  ],
  "confidence": 0.9,
  "language_hint": "fr"
}
```

**无修改时：**
```json
{
  "original": "Hello world.",
  "corrected": "Hello world.",
  "changes": [],
  "confidence": 1.0,
  "language_hint": "en"
}
```

---

## 5. 重试 / 温度 / 最大 tokens / 截断策略

| 策略 | 建议 | 说明 |
|------|------|------|
| **重试** | 最多 2 次（共 3 次调用） | 仅对网络/超时/5xx 或 JSON 解析失败重试；解析成功或 4xx 不重试 |
| **温度** | 0.1 ~ 0.3 | 严格纠错宜低温度，减少随意改写 |
| **最大 tokens** | 256 ~ 512 | 足够一段 OCR 文本 + JSON 结构；过小易截断 |
| **输入截断** | 按字符数截断（如 600~800 字符） | 超长时截断后加省略号再送模型，避免超长导致超时或截断 JSON |

**截断规则：** 若 `len(raw_text) > LLM_INPUT_MAX_CHARS`，取前 `LLM_INPUT_MAX_CHARS` 字符并追加 `...`，再送入 prompt；响应仍按 JSON 解析，若 `corrected` 被截断则由服务端用原文补全或仅使用已解析部分。

**温度与重试在 config 中：** `LLM_TEMPERATURE`、`LLM_RETRY_COUNT`、`LLM_INPUT_MAX_CHARS`。
