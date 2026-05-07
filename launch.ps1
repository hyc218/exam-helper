# ── 考试答题助手 · 浮窗启动器 ────────────────────────────────
# 启动 Node 服务 + 打开浮窗 + 置顶

param(
    [int]$Port = 3456,
    [int]$Width = 400,
    [int]$Height = 700
)

$ErrorActionPreference = "Stop"
$url = "http://localhost:$Port"

# ── 1. 启动服务器 ─────────────────────────────────────────────
Write-Host "正在启动服务..." -ForegroundColor Cyan

$existing = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "server\.js" -and $_.CommandLine -match "exam-helper"
}
if (-not $existing) {
    $serverDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    Start-Process -FilePath "node" -ArgumentList "server.js" -WorkingDirectory $serverDir -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "  服务已启动: $url" -ForegroundColor Green
} else {
    Write-Host "  服务已在运行: $url" -ForegroundColor Green
}

# ── 2. 等待服务就绪 ───────────────────────────────────────────
$maxWait = 10
for ($i = 0; $i -lt $maxWait; $i++) {
    try {
        $null = Invoke-WebRequest -Uri $url -TimeoutSec 1 -UseBasicParsing
        break
    } catch {
        if ($i -eq $maxWait - 1) {
            Write-Host "  服务启动超时" -ForegroundColor Red
            exit 1
        }
        Start-Sleep -Seconds 1
    }
}

# ── 3. 打开浮窗 ───────────────────────────────────────────────
Write-Host "正在打开浮窗..." -ForegroundColor Cyan

# 使用 Edge 应用模式（无浏览器边框）
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edgePath)) {
    $edgePath = "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
}

if (Test-Path $edgePath) {
    Start-Process -FilePath $edgePath -ArgumentList "--app=$url", "--new-window", "--window-size=$Width,$Height"
} else {
    # 回退到默认浏览器
    Start-Process $url
}

Start-Sleep -Seconds 1.5

# ── 4. 置顶窗口 ───────────────────────────────────────────────
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Diagnostics;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_SHOWWINDOW = 0x0040;
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

Add-Type -AssemblyName System.Windows.Forms

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$found = $false
while ($sw.Elapsed.TotalSeconds -lt 6 -and -not $found) {
    Start-Sleep -Milliseconds 300
    $procs = Get-Process -Name "msedge" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.MainWindowTitle -match "答题助手") {
            $hWnd = $p.MainWindowHandle
            if ($hWnd -ne [IntPtr]::Zero) {
                $workingArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
                $x = $workingArea.Right - $Width - 20
                $y = $workingArea.Top + 40

                [Win32]::SetWindowPos($hWnd, [Win32]::HWND_TOPMOST, $x, $y, $Width, $Height,
                    [Win32]::SWP_SHOWWINDOW)
                $found = $true
                break
            }
        }
    }
}

if ($found) {
    Write-Host "  浮窗已置顶 (${Width}x${Height}) 于右上角" -ForegroundColor Green
} else {
    Write-Host "  浮窗已打开（如未置顶请用 PowerToys Win+Ctrl+T）" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host "  使用方式：" -ForegroundColor White
Write-Host "  1. 在浮窗中点 ▶ 开始监听" -ForegroundColor Gray
Write-Host "  2. 用 Win+Shift+S 截题目" -ForegroundColor Gray
Write-Host "  3. AI 自动分析 → 答案弹出" -ForegroundColor Gray
Write-Host "  4. 做完点 ⏸ 停止" -ForegroundColor Gray
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
