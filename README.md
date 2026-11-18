# 嘉立创订单进度（AstrBot 插件）

定时查询嘉立创 PCB/FPC 订单状态，并向指定 QQ 群或私聊推送。认证方式为 **Tailscale 网页登录**，不提供手动 Token 配置。

## 安装依赖

```bash
cd /root/bot/data/plugins
git clone https://github.com/shimokin1208/astrbot_plugin_jlc_order.git
cd /root/bot
uv pip install -r data/plugins/astrbot_plugin_jlc_order/requirements.txt
uv run playwright install chromium
```

如果 Chromium 缺少系统库：

```bash
uv run playwright install-deps chromium
```

## 配置

- `admin_user_id`：自己的 QQ 号，唯一网页登录管理员。
- `notify_group_id`：订单推送群号（可选）。
- `notify_user_id`：订单推送私聊 QQ 号（可选）。
- `interval_minutes`：轮询间隔，默认 40 分钟。

不再支持手动填写 AccessToken。插件只使用网页登录捕获并保存的凭证。

## 网页登录

1. Debian 小主机和电脑都连接同一个 Tailscale 网络。
2. 私聊机器人发送 `/jlc登录`。
3. 机器人会把临时登录地址私聊给管理员。
4. 在电脑浏览器打开地址，通过远程浏览器画面登录嘉立创。
5. 登录后进入“我的订单”，确保订单列表接口请求已经发生。
6. 点击“完成登录并保存凭证”。
7. 页面会显示实时诊断：Token 是否捕获、捕获次数、最近事件和错误信息。
8. 成功或失败都会向管理员 QQ 发送消息。

## 指令

| 指令 | 作用 |
|---|---|
| `/jlc登录` | 启动临时远程浏览器 |
| `/jlc登录状态` | 查看浏览器、Token 捕获和错误状态 |
| `/jlc退出登录` | 清除本地凭证及浏览器会话 |
| `/jlc订单` | 立即查询订单 |
| `/jlc状态` | 查看轮询任务 |

## 失败提示

登录入口启动失败、浏览器启动失败、没有捕获到 Token 等情况会在 QQ 中给出错误提示。登录页面也会显示捕获状态与最近错误。订单接口返回未授权或认证失败时会提示重新登录。

## 安全说明

登录入口绑定小主机 Tailscale IPv4 地址，使用随机一次性密钥；不要转发链接，也不要把端口 18763 暴露到公网。Token 保存在插件数据目录的受限权限文件中。退出登录会删除 Token 和持久化浏览器会话。

## 注意

嘉立创可能调整网页结构、登录验证或 Token 传递方式。当前版本需要真实账号验证；验证码、风控或认证流程变化可能导致登录失败。Token 过期后需要重新执行网页登录。
