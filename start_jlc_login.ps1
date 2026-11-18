param([Parameter(Mandatory=$true)][string]$MiniPcTailscaleIp)
$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "请使用管理员身份打开 PowerShell 后再运行此脚本，以便添加仅限 Tailscale 的防火墙规则。" }
if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) { throw "未找到 Tailscale，请先安装并登录。" }
$windowsTsIp = (& tailscale ip -4 | Select-Object -First 1).Trim()
if (-not $windowsTsIp) { throw "无法获取本机 Tailscale IPv4 地址。" }
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe","$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe","$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$edge = @("$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe","$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$browser = if ($chrome) { $chrome } else { $edge }
if (-not $browser) { throw "未找到 Chrome 或 Edge。" }
$rule = "JLC-CDP-Tailscale-9222"
Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9222 -LocalAddress $windowsTsIp -RemoteAddress $MiniPcTailscaleIp -Profile Any | Out-Null
$profile = Join-Path $env:LOCALAPPDATA "JLC-Login-Browser"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$browserArgs = "--remote-debugging-port=9222 --remote-debugging-address=$windowsTsIp --remote-allow-origins=* --user-data-dir=`"$profile`" --no-first-run --no-default-browser-check https://www.jlc.com/"
Start-Process -FilePath $browser -ArgumentList $browserArgs
Write-Host "嘉立创专用浏览器已启动。" -ForegroundColor Green
Write-Host "Windows Tailscale IP: $windowsTsIp"
Write-Host "调试地址: http://$windowsTsIp:9222"
Write-Host "防火墙仅允许小主机 Tailscale IP $MiniPcTailscaleIp 访问 9222。"
