(function () {
  'use strict';

  // 后端 API 根地址（与页面同源则留空或写 ''，否则写完整地址如 http://localhost:8000）
  var API_BASE = '';

  var fileInput = document.getElementById('file');
  var preview = document.getElementById('preview');
  var recognizeBtn = document.getElementById('recognize');
  var statusEl = document.getElementById('status');
  var resultSection = document.getElementById('result');
  var rawOcrEl = document.getElementById('raw-ocr');
  var correctedEl = document.getElementById('corrected');
  var confidenceEl = document.getElementById('confidence');
  var timingEl = document.getElementById('timing');
  var errorMsgEl = document.getElementById('error-msg');

  function setStatus(text, isError) {
    statusEl.textContent = text || '';
    statusEl.className = 'status' + (isError ? ' error' : '');
  }

  function showResult(visible) {
    resultSection.setAttribute('aria-hidden', !visible);
  }

  function displayResult(data) {
    rawOcrEl.textContent = (data.raw_ocr || '(无)').trim();
    correctedEl.textContent = (data.corrected || '(无)').trim();
    confidenceEl.textContent = '置信度: ' + (data.confidence != null ? (data.confidence * 100).toFixed(1) + '%' : '-');
    timingEl.textContent = 'OCR: ' + (data.ocr_time_ms != null ? data.ocr_time_ms.toFixed(0) : '-') + ' ms，LLM: ' + (data.llm_time_ms != null ? data.llm_time_ms.toFixed(0) : '-') + ' ms';
    errorMsgEl.textContent = data.error_msg || '';
    showResult(true);
  }

  fileInput.addEventListener('change', function () {
    var file = fileInput.files && fileInput.files[0];
    preview.innerHTML = '';
    preview.setAttribute('aria-hidden', 'true');
    recognizeBtn.disabled = !file;
    showResult(false);
    setStatus('');
    if (!file || !file.type.startsWith('image/')) return;
    var img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    img.alt = '预览';
    img.className = 'preview-img';
    img.onload = function () { URL.revokeObjectURL(img.src); };
    preview.appendChild(img);
    preview.setAttribute('aria-hidden', 'false');
  });

  recognizeBtn.addEventListener('click', function () {
    var file = fileInput.files && fileInput.files[0];
    if (!file) {
      setStatus('请先选择一张图片', true);
      return;
    }
    recognizeBtn.disabled = true;
    setStatus('识别中…');
    showResult(false);

    var form = new FormData();
    form.append('file', file);
    var url = (API_BASE || '').replace(/\/$/, '') + '/api/recognize';

    fetch(url, {
      method: 'POST',
      body: form
    })
      .then(function (res) {
        if (!res.ok) {
          return res.json().then(function (j) { throw new Error(j.detail || res.statusText); }).catch(function () {
            throw new Error(res.statusText || '请求失败');
          });
        }
        return res.json();
      })
      .then(function (data) {
        setStatus('识别完成');
        displayResult(data);
      })
      .catch(function (err) {
        setStatus('失败: ' + (err.message || err), true);
        showResult(false);
      })
      .finally(function () {
        recognizeBtn.disabled = false;
      });
  });
})();
