#!/usr/bin/env python3
"""考试答题助手 - 浮窗 + 自动检测截图 + AI 作答"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import hashlib
import base64
import io
import json
import os
import sys
import requests
from PIL import ImageGrab, Image

# Config stored in AppData (won't fail if exe is in read-only location)
APPDATA_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'ExamHelper')
os.makedirs(APPDATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APPDATA_DIR, 'config.json')

DEFAULTS = {
    'api_key': '',
    'model': 'glm-4.6v',
    'api_base': 'https://open.bigmodel.cn/api/paas/v4',
}

SYSTEM_PROMPT = '''你是一个专业的考试答题助手。请仔细分析题目截图中的内容。

要求：
1. 识别题目类型（选择题、填空题、判断题、简答题等）
2. 给出正确答案
3. 提供简短清晰的解析
4. 如果是选择题，明确标注正确选项（如：答案：C）
5. 如果是计算题，展示关键步骤
6. 如果是判断题，明确回答"正确"或"错误"并说明理由
7. 回答使用中文，保持简洁准确'''

# ── Colours ───────────────────────────────────────────────────
BG      = '#0f0f16'
SURFACE = '#191927'
SURFACE2 = '#222236'
BORDER  = '#2e2e48'
TEXT    = '#dddde8'
TEXT2   = '#8888a8'
ACCENT  = '#7c6ff7'
GREEN   = '#2ecc71'
RED     = '#e74c3c'
YELLOW  = '#f1c40f'

class ExamHelper:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('答题助手')
        self.root.geometry('400x680+%d+40' % (self.root.winfo_screenwidth() - 420))
        self.root.configure(bg=BG)
        self.root.minsize(320, 400)
        self.root.attributes('-topmost', True)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.monitoring = False
        self.last_hash = ''
        self.answers = []
        self.config = self._load_config()

        self._setup_ui()
        self.root.mainloop()

    # ── Config ─────────────────────────────────────────────────
    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return {**DEFAULTS, **json.load(f)}
        except Exception:
            pass
        return DEFAULTS.copy()

    def _save_config(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── UI setup ───────────────────────────────────────────────
    def _setup_ui(self):
        # Titlebar
        titlebar = tk.Frame(self.root, bg=SURFACE, height=42)
        titlebar.pack(fill='x')
        titlebar.pack_propagate(False)

        self.dot_canvas = tk.Canvas(titlebar, width=10, height=10, bg=SURFACE,
                                     highlightthickness=0)
        self.dot_canvas.place(x=12, y=16)
        self.dot = self.dot_canvas.create_oval(0, 0, 10, 10, fill=TEXT2, outline='')

        self.status_lbl = tk.Label(titlebar, text='就绪', bg=SURFACE, fg=TEXT,
                                    font=('Microsoft YaHei', 9))
        self.status_lbl.place(x=28, y=10)

        btn_style = {'bg': SURFACE2, 'fg': TEXT, 'bd': 0, 'padx': 8, 'pady': 2,
                     'font': ('', 9), 'cursor': 'hand2', 'activebackground': BORDER,
                     'activeforeground': TEXT, 'relief': 'flat'}

        self.settings_btn = tk.Button(titlebar, text='⚙', command=self._toggle_settings, **btn_style)
        self.settings_btn.place(x=300, y=6)

        self.toggle_btn = tk.Button(titlebar, text='▶', command=self._toggle_monitor, **btn_style)
        self.toggle_btn.place(x=340, y=6)

        self.clear_btn = tk.Button(titlebar, text='✕', command=self._clear, **{**btn_style, 'fg': RED})
        self.clear_btn.place(x=375, y=6)

        # Settings panel
        self.settings_frame = tk.Frame(self.root, bg=SURFACE)

        self._make_field('API Key', 'api_key', show='●')
        self._make_field('模型', 'model', show='')
        self._make_field('API Base URL', 'api_base', show='')

        tk.Button(self.settings_frame, text='保存设置', bg=ACCENT, fg='#fff', bd=0,
                  font=('Microsoft YaHei', 9), padx=20, pady=6, cursor='hand2',
                  activebackground=ACCENT, activeforeground='#fff', relief='flat',
                  command=self._save_settings).pack(pady=(10, 14))

        # Answer area
        answer_area = tk.Frame(self.root, bg=BG)
        answer_area.pack(fill='both', expand=True, padx=8, pady=4)

        self.canvas = tk.Canvas(answer_area, bg=BG, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(answer_area, orient='vertical', command=self.canvas.yview)

        self.content_frame = tk.Frame(self.canvas, bg=BG)
        self.content_frame.bind('<Configure>',
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.create_window((0, 0), window=self.content_frame, anchor='nw', tags='inner')

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

        # Mouse wheel
        self.canvas.bind('<Enter>', lambda _: self.canvas.bind_all('<MouseWheel>', self._on_scroll))
        self.canvas.bind('<Leave>', lambda _: self.canvas.unbind_all('<MouseWheel>'))

        # Empty state
        self._show_empty('🎯\n配置 API Key 后点击 ▶ 开始')
        self._render_tip()

    def _make_field(self, label, key, show=''):
        tk.Label(self.settings_frame, text=label, bg=SURFACE, fg=TEXT2,
                 font=('', 7, 'bold'), anchor='w').pack(fill='x', padx=14, pady=(8, 0))
        var = tk.StringVar(value=self.config.get(key, ''))
        entry = tk.Entry(self.settings_frame, textvariable=var, bg=SURFACE2, fg=TEXT,
                         insertbackground=TEXT, font=('Microsoft YaHei', 9),
                         bd=0, relief='flat', show=show)
        entry.pack(fill='x', padx=14, pady=2, ipady=6)
        setattr(self, f'{key}_var', var)

    def _render_tip(self):
        tip = tk.Frame(self.root, bg=SURFACE, height=30)
        tip.pack(fill='x', side='bottom')
        tip.pack_propagate(False)
        tk.Label(tip, text='💡 Win+Shift+S 截图 → 自动识别 → 答案弹出',
                 bg=SURFACE, fg=TEXT2, font=('Microsoft YaHei', 7)).pack(expand=True)

    # ── Actions ────────────────────────────────────────────────
    def _toggle_settings(self):
        if self.settings_frame.winfo_ismapped():
            self.settings_frame.pack_forget()
        else:
            self.settings_frame.pack(fill='x', pady=(0, 4))

    def _save_settings(self):
        self.config['api_key'] = self.api_key_var.get()
        self.config['model'] = self.model_var.get()
        self.config['api_base'] = self.api_base_var.get()
        self._save_config()
        self._toggle_settings()
        self._set_status('idle', '已保存')

    def _toggle_monitor(self):
        if self.monitoring:
            self.monitoring = False
            self.toggle_btn.config(text='▶', fg=TEXT)
            self._set_status('idle', '就绪')
        else:
            if not self.config.get('api_key'):
                messagebox.showwarning('提示', '请先在设置中填入 API Key\n\n推荐用智谱 GLM-4.6V：\nhttps://open.bigmodel.cn', parent=self.root)
                self._toggle_settings()
                return
            self.monitoring = True
            self.toggle_btn.config(text='⏸', fg=ACCENT)
            self._set_status('monitoring', '监听中')
            threading.Thread(target=self._clipboard_loop, daemon=True).start()

    def _clear(self):
        self.answers.clear()
        self.last_hash = ''
        self._show_empty('🎯\n等待截图...')

    # ── Clipboard loop ─────────────────────────────────────────
    def _clipboard_loop(self):
        while self.monitoring:
            try:
                img = ImageGrab.grabclipboard()
                if isinstance(img, list):
                    # Some systems return list of file paths
                    if img and os.path.exists(img[0]):
                        img = Image.open(img[0])
                    else:
                        img = None
                if isinstance(img, Image.Image):
                    buf = io.BytesIO()
                    img.save(buf, 'PNG')
                    data = buf.getvalue()

                    h = hashlib.md5(data[:2000] + str(len(data)).encode()).hexdigest()
                    if h != self.last_hash:
                        self.last_hash = h
                        b64 = base64.b64encode(data).decode()
                        self.root.after(0, lambda: self._set_status('processing', 'AI 分析中...'))
                        try:
                            answer = self._call_api(b64)
                            self.root.after(0, lambda a=answer: self._add_answer(a))
                        except Exception as e:
                            self.root.after(0, lambda e=e: self._add_answer(f'❌ {e}'))
                        self.root.after(0, lambda: self._set_status('monitoring', '监听中'))
            except Exception:
                pass
            time.sleep(2)

    # ── API call ───────────────────────────────────────────────
    def _call_api(self, image_b64):
        url = f"{self.config['api_base']}/chat/completions"
        resp = requests.post(url, headers={
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {self.config['api_key']}"
        }, json={
            'model': self.config['model'],
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{image_b64}'}},
                    {'type': 'text', 'text': '请分析这道题并给出答案'},
                ]},
            ],
            'max_tokens': 4000,
            'temperature': 0.1,
        }, timeout=60)

        if resp.status_code != 200:
            detail = resp.text[:300]
            raise Exception(f'API {resp.status_code}: {detail}')

        return resp.json()['choices'][0]['message']['content']

    # ── Answers UI ─────────────────────────────────────────────
    def _add_answer(self, text):
        self.answers.insert(0, {'text': text, 'time': time.strftime('%H:%M:%S')})
        if len(self.answers) > 40:
            self.answers.pop()
        self._render_answers()

    def _render_answers(self):
        for w in self.content_frame.winfo_children():
            w.destroy()

        if not self.answers:
            self._show_empty('🎯\n等待截图...')
            return

        for i, a in enumerate(self.answers):
            idx = len(self.answers) - i

            card = tk.Frame(self.content_frame, bg=SURFACE, highlightthickness=1,
                            highlightbackground=BORDER)
            card.pack(fill='x', pady=3)

            # Header
            hdr = tk.Frame(card, bg=SURFACE)
            hdr.pack(fill='x', padx=10, pady=(8, 2))
            tk.Label(hdr, text=f'#{idx}', bg=SURFACE, fg=ACCENT,
                     font=('', 9, 'bold')).pack(side='left')
            tk.Label(hdr, text=a['time'], bg=SURFACE, fg=TEXT2,
                     font=('', 7)).pack(side='right')

            # Content text
            txt = tk.Text(card, bg=SURFACE2, fg=TEXT, font=('Microsoft YaHei', 9),
                          wrap='word', bd=0, padx=10, pady=8, height=6,
                          relief='flat', state='normal')
            txt.insert('1.0', a['text'])
            txt.config(state='disabled')
            txt.pack(fill='x', padx=10, pady=(2, 8))

            # Copy button
            bf = tk.Frame(card, bg=SURFACE)
            bf.pack(fill='x', padx=10, pady=(0, 8))
            tk.Button(bf, text='📋 复制答案', bg=SURFACE2, fg=TEXT, bd=0,
                      font=('', 7), padx=10, pady=2, cursor='hand2',
                      activebackground=BORDER, activeforeground=TEXT, relief='flat',
                      command=lambda t=a['text']: self._copy(t)).pack(side='left')

        self.canvas.yview_moveto(0)

    def _show_empty(self, text):
        for w in self.content_frame.winfo_children():
            w.destroy()
        tk.Label(self.content_frame, text=text, bg=BG, fg=TEXT2,
                 font=('Microsoft YaHei', 10), pady=50).pack()

    def _copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status('monitoring' if self.monitoring else 'idle', '✓ 已复制到剪贴板')

    # ── Helpers ────────────────────────────────────────────────
    def _set_status(self, state, text):
        colors = {'idle': TEXT2, 'monitoring': GREEN, 'processing': YELLOW, 'error': RED}
        self.dot_canvas.itemconfig(self.dot, fill=colors.get(state, TEXT2))
        self.status_lbl.config(text=text)

    def _on_scroll(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        return 'break'

    def on_close(self):
        self.monitoring = False
        self.root.destroy()


if __name__ == '__main__':
    ExamHelper()
