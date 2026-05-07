# 🎯 AI 考试答题助手

浮窗截图 + AI 自动作答的考试辅助工具。截图后自动识别题目类型并给出答案与解析。

## 版本

### Python 浮窗版 (`助手.py`)

- **桌面浮窗** — tkinter 编写的置顶悬浮窗口
- **监听剪贴板** — 自动检测截图（Win+Shift+S / 微信截图等）
- **AI 实时作答** — 调用视觉模型分析题目
- **答案管理** — 卡片式展示，支持一键复制
- 可打包为独立 exe（`dist/答题助手.exe`，34MB）

### Node.js 网页版 (`server.js` + `public/`)

- **浏览器运行** — Express + WebSocket 全双工通信
- **支持两种模式**：
  - 手动上传截图分析
  - 自动监听剪贴板（需 PowerShell 支持）
- 支持 OpenAI 兼容 API 和 Gemini API
- 前端 Markdown 渲染答案

## 快速开始

### Python 版

```bash
pip install pillow requests
python 助手.py
```

点击浮窗右上角 ⚙ 按钮填入 API Key，点击 ▶ 开始监听。

### Node.js 版

```bash
npm install
npm start        # 启动服务 → http://localhost:3456
npm run float    # 打开独立浮窗
```

## API 配置

推荐使用**智谱 GLM-4.6V**（视觉模型，性价比高）：

| 配置项 | 值 |
|---|---|
| API Base | `https://open.bigmodel.cn/api/paas/v4` |
| Model | `glm-4.6v` |
| API Key | 在 [open.bigmodel.cn](https://open.bigmodel.cn) 注册获取 |

也支持其他 OpenAI 兼容接口（DeepSeek 等）和 Google Gemini。

## 工作原理

```
截图 → 剪贴板检测（每2秒轮询）→ MD5 去重 → 调用视觉模型 API → 显示答案
```

## 技术栈

| 层 | Python 版 | Node.js 版 |
|---|---|---|
| UI | tkinter | HTML/CSS + WebSocket |
| 剪贴板 | Pillow ImageGrab | PowerShell STA |
| API | requests | fetch |
| 打包 | PyInstaller | — |

## 注意事项

- **仅供学习辅助**，请遵守考试规则
- 首次使用需填入有效的 API Key
- API Key 保存在 `%APPDATA%/ExamHelper/config.json`（Python 版）
- 截图临时文件自动清理
