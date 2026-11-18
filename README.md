# 嘉立创订单进度（AstrBot 插件）

定时查询嘉立创 PCB/FPC 订单状态，并向指定 QQ 群或私聊推送。登录改为 **安卓手机本机登录助手**，不再使用小主机 Chromium 远程画面。

## 安装依赖

```bash
cd /root/bot/data/plugins
git clone https://github.com/shimokin1208/astrbot_plugin_jlc_order.git
cd /root/bot
uv pip install -r data/plugins/astrbot_plugin_jlc_order/requirements.txt
```

## 配置

- `admin_user_id`：自己的 QQ 号，唯一登录管理员。
- `notify_group_id`：订单推送群号（可选）。
- `notify_user_id`：订单推送私聊 QQ 号（可选）。
- `interval_minutes`：轮询间隔，默认 40 分钟。

## 安卓登录

1. 在 GitHub 仓库 Actions 中下载最新的 `jlc-login-assistant-apk` 构建产物并安装到安卓手机（首次安装允许安装未知来源应用）。
2. 手机和 Debian 小主机都连接 Tailscale。
3. 私聊机器人发送 `/jlc登录`。
4. 点击机器人返回的登录链接，在打开的页面点击“打开嘉立创登录助手”。
5. 在 APK 内的嘉立创官方页面输入账号密码并完成滑块验证。
6. 登录成功并触发嘉立创接口请求后，APK 会自动捕获 AccessToken 并回传小主机。
7. 机器人会私聊通知凭证是否保存成功。

APK 不保存账号密码。账号密码由嘉立创官方登录页面处理；APK 只读取登录后的 AccessToken。配对链接仅有效 10 分钟且只能使用一次。

## 指令

| 指令 | 作用 |
|---|---|
| `/jlc登录` | 创建一次性安卓登录配对链接 |
| `/jlc登录状态` | 查看登录状态 |
| `/jlc退出登录` | 清除保存的 AccessToken |
| `/jlc订单` | 立即查询订单 |
| `/jlc状态` | 查看轮询任务 |

## 安全说明

- 登录接收服务只绑定小主机的 Tailscale IPv4 地址，不监听公网网卡。
- 手机到小主机的传输走 Tailscale 加密隧道，并使用随机一次性密钥。
- AccessToken 保存在插件数据目录的 `auth.json`，目录权限为 700，文件权限为 600。
- 不要转发登录配对链接；不要将端口 18763 暴露到公网。
- APK 仅捕获嘉立创域名请求中的 `x-jlc-accesstoken`，并检查网页存储中的已知 Token 字段。

## 注意

嘉立创可能调整登录页面或凭证传递方式。当前实现仍需用真实账号验证；如果页面登录成功但 APK 未能捕获凭证，需要根据实际请求结构更新捕获逻辑。订单查询、定时轮询和 QQ 通知逻辑保持原样。
