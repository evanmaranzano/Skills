---
name: open-sunflower
description: 在本机启动或唤起向日葵远程控制（AweSun / Sunlogin）客户端。当用户说"打开向日葵""开一下向日葵""向日葵远程控制""AweSun""远程桌面客户端"或直接输入 /open-sunflower 时使用。只做本地启动与前台唤起，不发起任何远程连接、不登录、不改设置。
user-invocable: true
---

# 打开向日葵

本机安装的是 AweSun 版向日葵：`C:\Program Files\Oray\AweSun\AweSun.exe`（开始菜单里叫"向日葵远程控制"）。

## 执行步骤

直接执行，不要反问用户。

首选：终端里跑 `sunflower`（`C:\Users\26566\bin\sunflower.cmd`，已在 PATH，cmd / PowerShell / Orca 终端都能用）。它等价于下面这段 PowerShell；命令不存在时才用下面这段兜底：

```powershell
$exe = 'C:\Program Files\Oray\AweSun\AweSun.exe'
$ui = Get-Process -Name 'AweSun' -ErrorAction SilentlyContinue |
      Where-Object { $_.MainWindowTitle -eq '向日葵远程控制' } |
      Select-Object -First 1
if ($ui) {
    $ws = New-Object -ComObject WScript.Shell
    if (-not $ws.AppActivate($ui.Id)) { Start-Process $exe }
    "已唤起：PID $($ui.Id)"
} else {
    Start-Process $exe
    Start-Sleep -Seconds 3
    Get-Process -Name 'AweSun' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -eq '向日葵远程控制' } |
        Select-Object Name, Id, MainWindowTitle
}
```

注意：`AweSun` 进程里还有一个标题为 `OrayPrivacyWnd` 的隐私遮罩窗口，别按"有窗口标题"去选，会唤起到遮罩窗口上。只认标题等于「向日葵远程控制」的那个。

## 判据

- 成功 = 存在 `AweSun` 进程且其中至少一个有主窗口标题「向日葵远程控制」。
- 只报结果（已启动 / 已唤起 / 失败及原因），不要展开客户端界面细节。

## 边界

- 不代替用户登录、不输入识别码/密码、不发起远控会话。
- 不修改向日葵的任何设置、不开机自启项。
