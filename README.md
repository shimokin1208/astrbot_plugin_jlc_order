# astrbot_plugin_jlc_order

AstrBot 插件：定时查询嘉立创 PCB/FPC 订单进度，并推送到指定 QQ 群或私聊。

## 功能

- 默认每 40 分钟查询一次订单，支持仅状态变化时推送
- 支持通过 Tailscale 网页登录嘉立创，自动捕获请求中的 AccessToken
- 持久化浏览器会话，重启后保留登录状态
- 保留手动 AccessToken 配置作为备用方式
- 指令：\`/jlc登录\`、\`/jlc登录状态\`、\`/jlc退出登录\`、\`/jlc订单\`、\`/jlc状态\`

## 安装

在 AstrBot 插件目录安装：

\`\`\`bash
cd /root/bot/data/plugins
git clone -b feature/web-login https://github.com/shimokin1208/astrbot_plugin_jlc_order.git
\`\`\`

在 AstrBot 使用的 uv 环境中安装依赖（按实际 AstrBot 项目目录调整）：

\`\`\`bash
cd /root/bot
uv pip install -r data/plugins/astrbot_plugin_jlc_order/requirements.txt
uv run playwright install chromium
\`\`\`

Chromium 首次下载体积较大。此功能会在执行登录时才启动浏览器，登录完成后关闭浏览器；不会让 Chromium 常驻运行。

重载插件后，在插件配置中填写：

- \`admin_user_id\`：自己的 QQ 号，网页登录功能的唯一管理员
- \`notify_user_id\` 或 \`notify_group_id\`：订单推送目标，按原有规则配置
- \`access_token\`：可留空；如果网页登录无法使用，可手动填写备用 Token

## 网页登录步骤

1. 确保 Debian 小主机已安装并登录 Tailscale，且电脑也已连接同一个 Tailnet。
2. 在 QQ 私聊机器人发送 \`/jlc登录\`。
3. 插件会把一次性登录链接私聊发送给配置的管理员账号。
4. 在电脑浏览器打开链接，在远程浏览器画面中登录 \`m.jlc.com\`。
5. 登录后进入“我的订单”页面，让页面发起订单 API 请求。
6. 点击网页底部的“完成登录并保存凭证”。
7. 插件保存 AccessToken 和持久化浏览器会话，并关闭临时浏览器服务。
8. 发送 \`/jlc登录状态\` 检查状态，再用 \`/jlc订单\` 验证订单查询。

登录入口仅绑定小主机的 Tailscale IPv4 地址，使用一次性随机密钥保护。不要转发登录链接。凭证文件保存在插件数据目录，文件权限限制为当前系统用户。

## 指令

| 指令 | 说明 |
|---|---|
| \`/jlc登录\` | 启动临时远程浏览器，并私聊发送登录链接 |
| \`/jlc登录状态\` | 查看网页凭证、备用 Token 和浏览器状态 |
| \`/jlc退出登录\` | 删除插件保存的 Token 和浏览器会话 |
| \`/jlc订单\` | 立即查询订单 |
| \`/jlc状态\` | 查看订单轮询状态 |

## 注意

- 只用于查询自己的订单，不进行下单或支付。
- 建议轮询间隔不低于 30 分钟。
- 嘉立创可能调整登录流程、Token 传递方式或增加验证码；若没有捕获到 Token，请在登录后进入订单页面再点击完成。
- 当前版本会自动捕获请求头中的 \`x-jlc-accesstoken\`，但尚不能保证嘉立创会话一定支持无交互续期。若会话过期，需要重新执行网页登录。
- 登录页面使用 HTTP，但只监听 Tailscale 私有地址；不要将端口 18763 暴露到公网。

## License

MIT
