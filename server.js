import express from 'express';
import multer from 'multer';
import { WebSocketServer } from 'ws';
import { createServer } from 'http';
import { execSync } from 'child_process';
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3456;
const SCREENSHOTS_DIR = join(__dirname, 'screenshots');
if (!existsSync(SCREENSHOTS_DIR)) mkdirSync(SCREENSHOTS_DIR, { recursive: true });

// ── Express + HTTP + WebSocket ───────────────────────────────
const app = express();
const httpServer = createServer(app);
const wss = new WebSocketServer({ server: httpServer });

app.use(express.json({ limit: '50mb' }));
app.use(express.static(join(__dirname, 'public')));

const upload = multer({ dest: SCREENSHOTS_DIR, limits: { fileSize: 20 * 1024 * 1024 } });

// Track connected WS clients
const clients = new Set();
wss.on('connection', (ws) => {
  clients.add(ws);
  ws.on('close', () => clients.delete(ws));
});

function broadcast(msg) {
  const data = JSON.stringify(msg);
  for (const ws of clients) ws.send(data);
}

// ── System prompt ────────────────────────────────────────────
const SYSTEM_PROMPT = `你是一个专业的考试答题助手。请仔细分析题目截图中的内容。

要求：
1. 识别题目类型（选择题、填空题、判断题、简答题等）
2. 给出正确答案
3. 提供简短清晰的解析
4. 如果是选择题，明确标注正确选项（如：答案：C）
5. 如果是计算题，展示关键步骤
6. 如果是判断题，明确回答"正确"或"错误"并说明理由
7. 回答使用中文，保持简洁准确`;

// ── AI API calls ─────────────────────────────────────────────
async function callAI(base64Image, provider, apiKey, model, apiBase) {
  if (provider === 'gemini') return callGemini(base64Image, apiKey, model);
  return callOpenAICompat(base64Image, apiKey, model, apiBase || 'https://api.deepseek.com/v1');
}

async function callOpenAICompat(base64Image, apiKey, model, apiBase) {
  const resp = await fetch(`${apiBase}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: model || 'deepseek-chat',
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: [
          { type: 'image_url', image_url: { url: `data:image/png;base64,${base64Image}` } },
          { type: 'text', text: '请分析这道题并给出答案' },
        ]},
      ],
      max_tokens: 4000,
      temperature: 0.1,
    }),
  });
  if (!resp.ok) { const e = await resp.text(); throw new Error(`API ${resp.status}: ${e}`); }
  const data = await resp.json();
  return data.choices[0].message.content;
}

async function callGemini(base64Image, apiKey, model) {
  const m = model || 'gemini-2.5-flash';
  const resp = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent?key=${apiKey}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
        contents: [{ parts: [
          { text: '请分析这道题并给出答案' },
          { inline_data: { mime_type: 'image/png', data: base64Image } },
        ]}],
      }),
    }
  );
  if (!resp.ok) { const e = await resp.text(); throw new Error(`Gemini ${resp.status}: ${e}`); }
  const data = await resp.json();
  return data.candidates[0].content.parts[0].text;
}

// ── Clipboard watcher ────────────────────────────────────────
let clipboardTimer = null;
let lastImageHash = '';
let watcherConfig = { apiKey: '', provider: 'openai', model: 'glm-4.6v', apiBase: 'https://open.bigmodel.cn/api/paas/v4' };

function getClipboardImageBase64() {
  try {
    // Write PS script to temp file to avoid bash eating $variables
    const tmpFile = join(SCREENSHOTS_DIR, '_clip.ps1');
    const psScript = `
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
\$img = [System.Windows.Forms.Clipboard]::GetImage()
if (\$img -ne \$null) {
  \$ms = New-Object System.IO.MemoryStream
  \$img.Save(\$ms, [System.Drawing.Imaging.ImageFormat]::Png)
  \$bytes = \$ms.ToArray()
  \$base64 = [Convert]::ToBase64String(\$bytes)
  Write-Output \$base64
  \$ms.Close()
  \$img.Dispose()
}
`.trim();
    writeFileSync(tmpFile, psScript);

    const result = execSync(
      `powershell -STA -NoProfile -ExecutionPolicy Bypass -File "${tmpFile}"`,
      { timeout: 5000, encoding: 'utf-8', windowsHide: true }
    ).trim();

    try { unlinkSync(tmpFile); } catch (_) {}

    return result || null;
  } catch {
    return null;
  }
}

async function pollClipboard() {
  if (!watcherConfig.apiKey) return;

  try {
    const b64 = getClipboardImageBase64();
    if (!b64) return; // no image in clipboard

    // Hash to detect change (sample front + total length)
    const hash = crypto.createHash('md5')
      .update(b64.slice(0, 2000) + b64.length.toString())
      .digest('hex');

    if (hash === lastImageHash) return; // same image, skip
    lastImageHash = hash;

    // Save to disk
    const filename = `auto_${Date.now()}.png`;
    const filePath = join(SCREENSHOTS_DIR, filename);
    writeFileSync(filePath, Buffer.from(b64, 'base64'));

    // Notify client: processing
    broadcast({ type: 'processing', filename });

    // Call AI
    const answer = await callAI(
      b64, watcherConfig.provider, watcherConfig.apiKey,
      watcherConfig.model, watcherConfig.apiBase
    );

    // Save answer alongside screenshot
    const answerPath = filePath.replace('.png', '.txt');
    writeFileSync(answerPath, answer);

    // Notify client: result
    broadcast({ type: 'answer', filename, answer, time: Date.now() });

    // Cleanup screenshot immediately
    try { if (existsSync(filePath)) unlinkSync(filePath); } catch (_) {}

  } catch (err) {
    broadcast({ type: 'error', error: err.message });
  }
}

function startClipboardWatcher(config) {
  watcherConfig = { ...watcherConfig, ...config };
  lastImageHash = ''; // reset hash
  if (clipboardTimer) clearInterval(clipboardTimer);
  clipboardTimer = setInterval(pollClipboard, 2000);
  broadcast({ type: 'status', status: 'monitoring' });
}

function stopClipboardWatcher() {
  if (clipboardTimer) { clearInterval(clipboardTimer); clipboardTimer = null; }
  lastImageHash = '';
  broadcast({ type: 'status', status: 'idle' });
}

// ── Routes ───────────────────────────────────────────────────
app.post('/api/analyze', upload.single('image'), async (req, res) => {
  try {
    const file = req.file;
    if (!file) return res.status(400).json({ error: '未上传截图' });

    const { provider, apiKey, model, apiBase } = req.body;
    if (!apiKey) return res.status(400).json({ error: '请先配置 API Key' });

    const imageBase64 = readFileSync(file.path).toString('base64');

    // Clean up uploaded file immediately
    try { unlinkSync(file.path); } catch (_) {}

    const answer = await callAI(imageBase64, provider, apiKey, model, apiBase);
    res.json({ success: true, answer });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Auto mode control
app.post('/api/auto/start', (req, res) => {
  startClipboardWatcher(req.body);
  res.json({ success: true, status: 'monitoring' });
});

app.post('/api/auto/stop', (_req, res) => {
  stopClipboardWatcher();
  res.json({ success: true, status: 'idle' });
});

app.get('/api/status', (_req, res) => {
  res.json({ status: clipboardTimer ? 'monitoring' : 'idle' });
});

// Cleanup
app.post('/api/cleanup', (_req, res) => {
  let deleted = 0;
  try {
    const files = readdirSync(SCREENSHOTS_DIR);
    for (const f of files) {
      try { unlinkSync(join(SCREENSHOTS_DIR, f)); deleted++; } catch (_) {}
    }
  } catch (_) {}
  res.json({ success: true, deleted });
});

// ── Start ────────────────────────────────────────────────────
httpServer.listen(PORT, () => {
  console.log(`🚀 考试助手已启动: http://localhost:${PORT}`);
  console.log(`   浮窗模式: npm run float`);
});
