# 嘉立创订单进度（AstrBot 插件）

登录采用 Windows 本机浏览器 + Tailscale CDP：网页在 Windows Chrome/Edge 中运行，小主机只监听请求并保存 AccessToken，不再运行远程浏览器画面。

## Windows 浏览器准备

Windows 和 Debian 小主机登录同一个 Tailscale 网络。在 Windows PowerShell 运行仓库的 start_jlc_login.ps1：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start_jlc_login.ps1 -MiniPcTailscaleIp "小主机的Tailscale_IP"
```

脚本启动 Chrome/Edge 专用配置，将调试端口绑定到 Windows Tailscale 地址，并限制防火墙仅允许指定的小主机 Tailscale IP 访问 9222。

Windows 执行 tailscale ip -4，记下 Windows Tailscale IPv4 地址。在 AstrBot 插件配置 windows_cdp_url 中填写：

```
http://Windows的Tailscale_IP:9222
```

## 登录步骤

1. 确认 Windows 浏览器已由脚本启动，且两台设备的 Tailscale 均在线。
2. QQ 私聊机器人发送 /jlc登录。
3. 插件连接 Windows 浏览器并监听登录请求。
4. 在 Windows 浏览器中登录嘉立创，进入“我的订单”触发订单 API 请求。
5. QQ 私聊发送 /jlc登录状态，确认 Token 显示“已保存”。
6. 登录成功后可关闭 Windows 浏览器；订单查询由小主机使用已保存的 Token 完成。

## 依赖

在 AstrBot 环境执行：`cd /root/bot && uv pip install -r data/plugins/astrbot_plugin_jlc_order/requirements.txt`。插件端不再需要安装 Chromium。

## 指令

| 指令 | 作用 |
|---|---|
| /jlc登录 | 连接 Windows 浏览器并监听登录请求 |
| /jlc登录状态 | 查看浏览器连接和 Token 状态 |
| /jlc退出登录 | 清除本地凭证，不会关闭 Windows 浏览器 |
| /jlc订单 | 立即查询订单 |
| /jlc状态 | 查看轮询任务 |

## 安全说明

DevTools 接口拥有浏览器完整控制权限。脚本将端口绑定到 Windows Tailscale 地址，并创建仅允许指定小主机 Tailscale IP 访问的防火墙规则。不要将 9222 端口开放到公网。Token 保存在插件数据目录的 auth.json 中，目录权限为 700、文件权限为 600。

嘉立创可能调整 Token 传递方式；真实账号登录后仍需验证请求是否包含 x-jlc-accesstoken。
